import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from pycrdt import Array, Map

from ..outputs import OutputProcessor, OutputsManager
from ..ydocs import YNotebook


class OutputProcessorForTest(OutputProcessor):
    """Test subclass of OutputProcessor that overrides the settings property."""
    _test_settings = {}

    @property
    def settings(self):
        return self._test_settings


def _create_notebook_with_cell(cell_id, outputs=None):
    """Helper: create a YNotebook with one code cell and return notebook."""
    notebook = YNotebook()
    cell = Map({
        "id": cell_id,
        "cell_type": "code",
        "source": "print('hello')",
        "outputs": Array(outputs or []),
    })
    notebook.ycells.append(cell)
    return notebook


def _make_output_processor(outputs_manager, file_id):
    """Helper: create an OutputProcessor wired up with mocks for async methods."""
    op = OutputProcessorForTest()
    op._test_settings = {"outputs_manager": outputs_manager}
    op._file_id = file_id
    op.use_outputs_service = True
    op._get_file_info = AsyncMock(return_value=(file_id, f"/path/to/{file_id}.ipynb"))
    return op


class FakeNotebook:
    """Lightweight notebook stub that uses plain Python lists for outputs."""

    def __init__(self, cell_id):
        self._cell_id = cell_id
        self._outputs = []

    def find_cell(self, cell_id):
        if cell_id == self._cell_id:
            return 0, {"outputs": self._outputs}
        return -1, None


def _make_op(fake_nb, *, file_id="file-1", use_outputs_service=True):
    """Create an OutputProcessor wired to a FakeNotebook with all I/O mocked."""
    op = OutputProcessorForTest()
    op._file_id = file_id

    mock_room = MagicMock()
    mock_room.get_jupyter_ydoc = AsyncMock(return_value=fake_nb)

    mock_yroom_mgr = MagicMock()
    mock_yroom_mgr.get_room.return_value = mock_room

    mock_outputs_mgr = MagicMock()
    mock_outputs_mgr.write.side_effect = lambda **kw: kw["output"]
    mock_outputs_mgr.get_output_index.return_value = None

    mock_session_mgr = AsyncMock()
    mock_session_mgr.get_session.return_value = {"path": "nb.ipynb"}

    mock_file_id_mgr = MagicMock()
    mock_file_id_mgr.get_id.return_value = file_id

    op._test_settings = {
        "yroom_manager": mock_yroom_mgr,
        "outputs_manager": mock_outputs_mgr,
        "session_manager": mock_session_mgr,
        "file_id_manager": mock_file_id_mgr,
    }
    op.use_outputs_service = use_outputs_service
    return op, mock_outputs_mgr


@pytest.fixture
def output_processor():
    """Fixture that returns an instance of TestOutputProcessor."""
    return OutputProcessorForTest()


def create_incoming_message(cell_id):
    msg_id = str(uuid4())
    header = {"msg_id": msg_id, "msg_type": "execute_request"}
    parent_header = {}
    metadata = {"cellId": cell_id}
    msg = [json.dumps(item) for item in [header, parent_header, metadata]]
    return msg_id, msg


def test_instantiation(output_processor):
    """Test instantiation of the output processor."""
    op = output_processor
    assert isinstance(op, OutputProcessor)


@pytest.mark.asyncio
async def test_output_task_update_display_data():
    """Test that update_display_data replaces an existing output by index."""
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "test-display-1"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        notebook = _create_notebook_with_cell(cell_id)
        op = _make_output_processor(om, file_id)
        op.get_jupyter_ydoc = AsyncMock(return_value=notebook)

        # First: display_data with display_id
        content1 = {
            "data": {"text/plain": "v1"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        await op.output_task("display_data", cell_id, content1)

        _, cell = notebook.find_cell(cell_id)
        assert len(cell["outputs"]) == 1

        # Second: update_display_data with the same display_id should replace
        content2 = {
            "data": {"text/plain": "v2"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        await op.output_task("update_display_data", cell_id, content2)

        _, cell = notebook.find_cell(cell_id)
        assert len(cell["outputs"]) == 1


@pytest.mark.asyncio
async def test_output_task_update_display_after_clear_no_index_error():
    """Regression test for #216: update_display_data after clear_output must not raise IndexError.

    When clear_output races with update_display_data, the outputs array is
    emptied but the OutputsManager still maps the display_id to the old index.
    The fix ensures we fall back to append when the index is out of range.
    """
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "racy-display"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        notebook = _create_notebook_with_cell(cell_id)
        op = _make_output_processor(om, file_id)
        op.get_jupyter_ydoc = AsyncMock(return_value=notebook)

        # Step 1: write initial display_data output (index 0)
        content_initial = {
            "data": {"text/plain": "initial"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        await op.output_task("display_data", cell_id, content_initial)

        _, cell = notebook.find_cell(cell_id)
        assert len(cell["outputs"]) == 1

        # Step 2: clear the ydoc outputs (simulating clear_output race)
        cell["outputs"].clear()
        assert len(cell["outputs"]) == 0

        # The OutputsManager still thinks display_id -> index 0
        assert om.get_output_index(display_id) == 0

        # Step 3: update_display_data arrives — before the fix this raised IndexError
        content_update = {
            "data": {"text/plain": "updated"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        await op.output_task("update_display_data", cell_id, content_update)

        _, cell = notebook.find_cell(cell_id)
        assert len(cell["outputs"]) == 1


@pytest.mark.anyio
async def test_clear_output_task_does_not_clear_disk():
    """clear_output from kernel should only clear YDoc, not disk."""
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "hello"})

    op, mock_outputs_mgr = _make_op(fake_nb)

    await op.clear_output_task("cell-1", {"wait": False})

    assert len(fake_nb._outputs) == 0
    mock_outputs_mgr.clear.assert_not_called()


@pytest.mark.anyio
async def test_clear_cell_outputs_does_clear_disk():
    """clear_cell_outputs (execute_request) should clear both YDoc and disk."""
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "old"})

    op, mock_outputs_mgr = _make_op(fake_nb)

    with patch.object(type(op), "parent", new_callable=lambda: property(lambda self: MagicMock(parent=MagicMock(kernel_id="k1")))):
        await op.clear_cell_outputs("cell-1")

    assert len(fake_nb._outputs) == 0
    mock_outputs_mgr.clear.assert_called_once_with(file_id="file-1", cell_id="cell-1")


@pytest.mark.anyio
async def test_clear_output_does_not_wipe_subsequent_output():
    """Simulate one progress bar iteration: output → clear → new output."""
    fake_nb = FakeNotebook("cell-1")
    op, mock_outputs_mgr = _make_op(fake_nb)

    fake_nb._outputs.append({"output_type": "stream", "text": "Progress: 1/10"})

    await op.clear_output_task("cell-1", {"wait": False})
    assert len(fake_nb._outputs) == 0

    with patch.object(type(op), "parent", new_callable=lambda: property(lambda self: MagicMock(parent=MagicMock(kernel_id="k1")))):
        await op.output_task("stream", "cell-1", {
            "text": "Progress: 2/10",
            "name": "stdout",
        })
    assert len(fake_nb._outputs) == 1
    assert fake_nb._outputs[0]["text"] == "Progress: 2/10"

    mock_outputs_mgr.clear.assert_not_called()


@pytest.mark.anyio
async def test_clear_output_wait_defers_to_next_output():
    """clear_output(wait=True) should defer clearing until next output."""
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "old"})

    op, _ = _make_op(fake_nb)

    await op.clear_output_task("cell-1", {"wait": True})
    assert len(fake_nb._outputs) == 1
    assert "cell-1" in op._pending_clear_output_cells

    with patch.object(type(op), "parent", new_callable=lambda: property(lambda self: MagicMock(parent=MagicMock(kernel_id="k1")))):
        await op.output_task("stream", "cell-1", {
            "text": "new",
            "name": "stdout",
        })
    assert len(fake_nb._outputs) == 1
    assert fake_nb._outputs[0]["text"] == "new"
    assert "cell-1" not in op._pending_clear_output_cells
