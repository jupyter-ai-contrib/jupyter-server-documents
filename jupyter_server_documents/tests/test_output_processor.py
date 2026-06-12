"""
Tests for OutputProcessor.

The new API takes ycell (a live pycrdt.Map reference) and file_id directly,
eliminating all async session/file/cell lookups that the previous version
performed.
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from uuid import uuid4

from pycrdt import Array, Map

from ..outputs import OutputProcessor, OutputsManager
from ..ydocs import YNotebook


class OutputProcessorForTest(OutputProcessor):
    _test_settings = {}

    @property
    def settings(self):
        return self._test_settings

    @property
    def outputs_manager(self):
        return self._test_settings.get("outputs_manager")


def _make_processor(*, file_id="file-1", use_outputs_service=True):
    """Create an OutputProcessor with a mocked OutputsManager."""
    mock_outputs_mgr = MagicMock()
    mock_outputs_mgr.write.side_effect = lambda **kw: kw["output"]
    mock_outputs_mgr.get_output_index.return_value = None

    op = OutputProcessorForTest()
    op._test_settings = {"outputs_manager": mock_outputs_mgr}
    op.use_outputs_service = use_outputs_service
    return op, mock_outputs_mgr


def _make_ycell(outputs=None):
    """Make a plain-dict ycell mock whose outputs slot is a Python list."""
    outs = outputs if outputs is not None else []
    cell = {"outputs": outs, "cell_type": "code"}
    return cell


def test_instantiation():
    op = OutputProcessorForTest()
    assert isinstance(op, OutputProcessor)



def test_output_task_update_display_data():
    """update_display_data replaces an existing output by index."""
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "test-display-1"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        # Build a real YNotebook cell so pycrdt Array semantics apply
        notebook = YNotebook()
        ycell = Map({
            "id": cell_id,
            "cell_type": "code",
            "source": "",
            "outputs": Array([]),
        })
        notebook.ycells.append(ycell)

        op = OutputProcessorForTest()
        op._test_settings = {"outputs_manager": om}
        op.use_outputs_service = True

        content1 = {
            "data": {"text/plain": "v1"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("display_data", ycell, file_id, cell_id, content1)
        assert len(ycell["outputs"]) == 1

        content2 = {
            "data": {"text/plain": "v2"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("update_display_data", ycell, file_id, cell_id, content2)
        assert len(ycell["outputs"]) == 1



def test_output_task_update_display_after_clear_no_index_error():
    """Stale display_id index after clear_output must not raise IndexError."""
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "racy-display"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        notebook = YNotebook()
        ycell = Map({
            "id": cell_id,
            "cell_type": "code",
            "source": "",
            "outputs": Array([]),
        })
        notebook.ycells.append(ycell)

        op = OutputProcessorForTest()
        op._test_settings = {"outputs_manager": om}
        op.use_outputs_service = True

        content_initial = {
            "data": {"text/plain": "initial"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("display_data", ycell, file_id, cell_id, content_initial)
        assert len(ycell["outputs"]) == 1

        # Simulate a clear_output race
        del ycell["outputs"][:]
        assert len(ycell["outputs"]) == 0
        assert om.get_output_index(display_id) == 0  # stale index

        content_update = {
            "data": {"text/plain": "updated"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        # Must not raise IndexError — falls back to append
        op._write_output("update_display_data", ycell, file_id, cell_id, content_update)
        assert len(ycell["outputs"]) == 1



def test_clear_output_task_clears_ycell():
    ycell = _make_ycell([{"output_type": "stream", "text": "hello"}])
    op, mock_om = _make_processor()
    op._handle_clear_output(ycell, "file-1", "cell-1", {"wait": False})
    assert len(ycell["outputs"]) == 0
    # The outputs service must also be cleared to stay in sync with the YDoc.
    mock_om.clear.assert_called_once_with(file_id="file-1", cell_id="cell-1")



def test_clear_output_wait_defers_to_next_output():
    """clear_output(wait=True) defers clearing until the next output."""
    ycell = _make_ycell([{"output_type": "stream", "text": "old"}])
    op, _ = _make_processor()

    op._handle_clear_output(ycell, "file-1", "cell-1", {"wait": True})
    assert len(ycell["outputs"]) == 1
    assert "cell-1" in op._pending_clear_output_cells

    op._write_output("stream", ycell, "file-1", "cell-1", {
        "text": "new", "name": "stdout",
    })
    assert len(ycell["outputs"]) == 1
    assert ycell["outputs"][0]["text"] == "new"
    assert "cell-1" not in op._pending_clear_output_cells



def test_output_appended_to_ycell_directly():
    """With use_outputs_service=False outputs are written as Map objects."""
    ycell = _make_ycell()
    op, _ = _make_processor(use_outputs_service=False)

    op._write_output("stream", ycell, None, "cell-1", {
        "text": "hello\n", "name": "stdout",
    })
    assert len(ycell["outputs"]) == 1
    assert ycell["outputs"][0]["output_type"] == "stream"


def test_process_output_dispatches_stream():
    """process_output writes synchronously — no task needed."""
    ycell = _make_ycell()
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("stream", ycell, None, "cell-1", {"text": "hi", "name": "stdout"})
    assert len(ycell["outputs"]) == 1


def test_process_output_dispatches_clear():
    """process_output clears synchronously — no task needed."""
    ycell = _make_ycell([{"output_type": "stream", "text": "old"}])
    op, _ = _make_processor()
    op.process_output("clear_output", ycell, None, "cell-1", {"wait": False})
    assert len(ycell["outputs"]) == 0
