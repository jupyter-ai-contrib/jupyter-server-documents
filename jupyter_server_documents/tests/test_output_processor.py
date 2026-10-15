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

import nbformat
from nbformat.sign import NotebookNotary
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


# ── Output trust ──────────────────────────────────────────────────────────────
#
# Jupyter sanitizes HTML output from notebooks it does not trust, which strips
# <style> and reduces a scikit-learn / XGBoost estimator repr to its plain-text
# fallback plus an unstyled parameter list. A cell holding rich output is only
# trusted if `metadata.trusted` is set, and the server writing outputs into the
# shared document is the only party that knows the output came from the room's
# kernel rather than from the file. These tests use real pycrdt-backed cells and
# read results back through `YNotebook.get()`, the path the contents manager
# saves from.


def _rich_output_content():
    """An execute_result whose HTML carries CSS — the case that breaks."""
    return {
        "data": {
            "text/html": "<style>#sk-1 {color: red}</style><div id='sk-1'>XGBRegressor</div>",
            "text/plain": "XGBRegressor(...)",
        },
        "metadata": {},
        "execution_count": 1,
    }


def _make_real_ycell(**metadata):
    """A code cell inside a real YNotebook, as the room holds it."""
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell(source="model.fit(X, y)")
    cell["metadata"].update(metadata)
    nb.cells.append(cell)
    notebook = YNotebook()
    notebook.set(nb)
    ycell = notebook.ycells[0]
    assert isinstance(ycell, Map) and isinstance(ycell["metadata"], Map)
    return notebook, ycell


def test_writing_output_marks_the_cell_trusted():
    """The load-time state: `NotebookNotary.mark_cells` writes `trusted: False`
    into every code cell of an unsigned notebook. Executing the cell must flip
    it in the shared model."""
    notebook, ycell = _make_real_ycell(trusted=False)
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())

    saved = notebook.get()["cells"][0]
    assert saved["metadata"]["trusted"] is True
    assert len(saved["outputs"]) == 1


def test_trust_is_written_once_and_preserves_other_metadata():
    """Every shared-type write is broadcast to every client, so the flag is
    written once per cell, not once per output nor again on a re-run."""
    notebook, ycell = _make_real_ycell(tags=["keep-me"])
    ymeta, events = ycell["metadata"], []
    subscription = ymeta.observe(events.append)  # dropped if not referenced
    op, _ = _make_processor(use_outputs_service=False)
    for _ in range(3):
        op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())
    # A re-run: the cell is cleared, then its first output lands again.
    op.process_output("clear_output", ycell, None, "cell-1", {"wait": False})
    op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())

    ymeta.unobserve(subscription)
    assert len(events) == 1
    saved = notebook.get()["cells"][0]
    assert saved["metadata"] == {"tags": ["keep-me"], "trusted": True}
    assert len(saved["outputs"]) == 1


def test_trust_survives_clear_output():
    """clear_output empties the outputs; it must not un-trust the cell."""
    notebook, ycell = _make_real_ycell()
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())
    op.process_output("clear_output", ycell, None, "cell-1", {"wait": False})

    saved = notebook.get()["cells"][0]
    assert saved["outputs"] == []
    assert saved["metadata"]["trusted"] is True


def test_trust_is_recorded_on_the_outputs_service_path():
    """The opt-in outputs-service path (`use_outputs_service=True` with a
    `file_id`) hands the output to the outputs manager, which here is mocked to
    return it unchanged; the flag must land on that path too."""
    notebook, ycell = _make_real_ycell()
    op, mock_om = _make_processor(use_outputs_service=True)
    op.process_output("execute_result", ycell, "file-1", "cell-1", _rich_output_content())

    mock_om.write.assert_called_once()
    saved = notebook.get()["cells"][0]
    assert len(saved["outputs"]) == 1
    assert saved["metadata"]["trusted"] is True


@pytest.mark.parametrize(
    "msg_type, content",
    [
        ("clear_output", {"wait": False}),
        ("clear_output", {"wait": True}),
        ("status", {"execution_state": "idle"}),  # transform_output -> None
    ],
    ids=["clear_output", "clear_output-wait", "unhandled-msg-type"],
)
def test_a_message_that_yields_no_output_marks_nothing(msg_type, content):
    """The mark is tied to an output landing, not to any message arriving."""
    notebook, ycell = _make_real_ycell()
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output(msg_type, ycell, None, "cell-1", content)

    saved = notebook.get()["cells"][0]
    assert saved["outputs"] == []
    assert "trusted" not in saved["metadata"]


@pytest.mark.parametrize(
    "metadata",
    [None, "not-a-map"],
    ids=["missing", "json-string"],
)
def test_a_cell_without_a_metadata_map_gets_its_output_and_no_mark(metadata):
    """`jupyter_ydoc` gives every cell a metadata Map; anything else was
    written by a misbehaving client. The output must still land, and the
    processor must neither raise nor create or replace the metadata slot: a
    plain value there is not something the frontend's `getMetadata()` reads."""
    notebook = YNotebook()
    fields = {"id": "cell-1", "cell_type": "code", "source": "", "outputs": Array([])}
    if metadata is not None:
        fields["metadata"] = metadata
    ycell = Map(fields)
    notebook.ycells.append(ycell)
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())

    assert len(ycell["outputs"]) == 1
    assert ycell.get("metadata") == metadata


def test_output_appended_to_file_output_does_not_vouch_for_it():
    """Outputs loaded from the file keep the trust they arrived with. A run
    that does not clear the cell first (`execute_cells` defaults to
    `clear_outputs=False`) appends next to them, and must not mark the cell,
    or the file's output would be signed on the next save."""
    nb = nbformat.v4.new_notebook()
    cell = nbformat.v4.new_code_cell(source="print('hi')")
    cell["metadata"]["trusted"] = False
    cell["outputs"].append(
        nbformat.v4.new_output("display_data", data={"text/html": "<script>alert(1)</script>"})
    )
    nb.cells.append(cell)
    notebook = YNotebook()
    notebook.set(nb)
    ycell = notebook.ycells[0]
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("stream", ycell, None, "cell-1", {"name": "stdout", "text": "hi\n"})

    saved = notebook.get()["cells"][0]
    assert len(saved["outputs"]) == 2
    assert saved["metadata"]["trusted"] is False


def test_notary_would_sign_the_notebook_after_server_execution():
    """The contract that actually matters: `ContentsManager.save` signs a
    notebook only when `NotebookNotary.check_cells` passes, and an unsigned
    notebook gets its HTML sanitized in the browser."""
    notebook, ycell = _make_real_ycell(trusted=False)
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("execute_result", ycell, None, "cell-1", _rich_output_content())

    # Fresh copies each time: `_check_cell` POPS `trusted`.
    with TemporaryDirectory() as tmp:
        notary = NotebookNotary(data_dir=tmp)
        assert notary.check_cells(nbformat.from_dict(notebook.get())) is True

        # And the same cell WITHOUT the flag (the pre-fix state) is refused,
        # so the notebook would not be signed.
        untrusted = nbformat.from_dict(notebook.get())
        untrusted.cells[0]["metadata"].pop("trusted", None)
        assert notary.check_cells(untrusted) is False
