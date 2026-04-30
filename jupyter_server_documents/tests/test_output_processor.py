"""Tests for OutputProcessor."""

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
    """Test subclass that stubs out ServerApp.instance() access.

    In production, OutputProcessor.settings delegates to the running
    Jupyter server. In tests we inject a plain dict instead.
    """
    _test_settings = {}

    @property
    def settings(self):
        return self._test_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_notebook_with_cell(cell_id, outputs=None):
    """Create a real YNotebook CRDT document with one code cell.

    Used by tests that need actual pycrdt Array/Map behavior (e.g. the
    OutputsManager display_id indexing tests).
    """
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
    """Create an OutputProcessor with a real OutputsManager but mocked I/O.

    ``_get_file_info`` is mocked to return immediately (no DB lookup).
    Used by upstream tests that exercise OutputsManager.write / get_output_index.
    """
    op = OutputProcessorForTest()
    op._test_settings = {"outputs_manager": outputs_manager}
    op._file_id = file_id
    op.use_outputs_service = True
    op._get_file_info = AsyncMock(return_value=(file_id, f"/path/to/{file_id}.ipynb"))
    return op


class FakeNotebook:
    """Lightweight notebook stub that uses plain Python lists for outputs.

    Avoids pycrdt CRDT overhead. Useful for tests that only need to observe
    whether outputs were appended or cleared, without caring about CRDT
    synchronization or Y.js document integration.
    """

    def __init__(self, cell_id):
        self._cell_id = cell_id
        self._outputs = []

    def find_cell(self, cell_id):
        if cell_id == self._cell_id:
            return 0, {"outputs": self._outputs}
        return -1, None


def _make_op(fake_nb, *, file_id="file-1", use_outputs_service=True):
    """Create an OutputProcessor wired to a FakeNotebook with all I/O mocked.

    The mock ``outputs_manager.write`` passes the output dict through unchanged
    (no disk write). ``get_output_index`` returns None (no display_id tracking).
    This isolates tests to just the clear/write logic in OutputProcessor.
    """
    op = OutputProcessorForTest()
    op._file_id = file_id

    mock_room = MagicMock()
    mock_room.get_jupyter_ydoc = AsyncMock(return_value=fake_nb)

    mock_yroom_mgr = MagicMock()
    mock_yroom_mgr.get_room.return_value = mock_room

    mock_outputs_mgr = MagicMock()
    # Pass through: outputs_manager.write(output=X) returns X unchanged
    mock_outputs_mgr.write.side_effect = lambda **kw: kw["output"]
    mock_outputs_mgr.get_output_index.return_value = None

    op._test_settings = {
        "yroom_manager": mock_yroom_mgr,
        "outputs_manager": mock_outputs_mgr,
    }
    op.use_outputs_service = use_outputs_service
    return op, mock_outputs_mgr


# ---------------------------------------------------------------------------
# Upstream tests (display_data, update_display_data, index bounds)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _get_file_info caching and clear_output race condition fix
#
# Background: the OutputProcessor handles two kinds of "clear" operations:
#
# 1. clear_cell_outputs — called on execute_request (cell re-execution).
#    Full pipeline: invalidate cached file_id, fresh DB lookup, clear YDoc,
#    delete output files from disk.
#
# 2. clear_output_task — called when the kernel sends clear_output
#    (e.g. progress bars, IPython.display.clear_output()).
#    Lightweight: only clears the YDoc output array. No DB lookup, no disk.
#
# The distinction matters because clear_output can fire hundreds of times
# per second. If each one triggered the full pipeline — especially the
# async DB lookup in _get_file_info — it creates a race condition:
#
#   Kernel sends:  stream("50%")  →  clear_output  →  stream("51%")
#   Server does:   output_task(write "50%" to YDoc + disk)
#                  clear_cell_outputs(DB lookup... 14s in cloud...)
#                  output_task(write "51%" to YDoc + disk)
#                  ...14s later: clear finishes, deletes "51%" from disk
#                  Frontend fetches output → 404 Not Found
#
# The tests below use FakeNotebook (plain Python lists for outputs) rather
# than a real YNotebook, since we only need to observe whether outputs were
# appended or cleared — not CRDT synchronization behavior.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _get_file_info caching
#
# _get_file_info resolves the notebook's file_id by querying the session
# manager (an async DB lookup). Without caching, every output_task and
# clear_output_task would repeat this lookup. In cloud environments the
# lookup can take seconds, which is the root cause of the race condition.
#
# The cache is invalidated only in clear_cell_outputs (execute_request),
# which handles the notebook-rename edge case.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_file_info_returns_cached_value():
    """When _file_id is already set, _get_file_info should return it
    immediately without any async DB lookup.

    Example: after the first output_task sets _file_id="abc", all
    subsequent calls return ("abc", None) with zero I/O.
    """
    op = OutputProcessorForTest()
    op._file_id = "cached-id"

    file_id, path = await op._get_file_info()

    assert file_id == "cached-id"
    # path is None when returning from cache (no session lookup happened)
    assert path is None


@pytest.mark.anyio
async def test_clear_cell_outputs_invalidates_cache():
    """clear_cell_outputs (the execute_request path) must reset _file_id
    to None before looking it up again. This handles the case where the
    notebook was renamed between executions.

    Example: user renames "Untitled.ipynb" to "Analysis.ipynb", then
    re-runs a cell. The old cached file_id is stale — clear_cell_outputs
    invalidates it so the fresh lookup resolves the new path.
    """
    fake_nb = FakeNotebook("cell-1")
    op, mock_outputs_mgr = _make_op(fake_nb, file_id="old-id")

    mock_session_mgr = AsyncMock()
    mock_session_mgr.get_session.return_value = {"path": "nb.ipynb"}
    mock_file_id_mgr = MagicMock()
    mock_file_id_mgr.get_id.return_value = "new-id"

    op._test_settings["session_manager"] = mock_session_mgr
    op._test_settings["file_id_manager"] = mock_file_id_mgr

    # patch the traitlets `parent` property to avoid Configurable validation
    with patch.object(type(op), "parent", new_callable=lambda: property(lambda self: MagicMock(parent=MagicMock(kernel_id="k1")))):
        await op.clear_cell_outputs("cell-1")

    # Cache should now hold the fresh value
    assert op._file_id == "new-id"
    # Session manager was actually called (not served from cache)
    mock_session_mgr.get_session.assert_called_once()


# ---------------------------------------------------------------------------
# clear_output_task (kernel clear_output) vs clear_cell_outputs (execute_request)
#
# These two tests verify the core invariant of the fix:
#   - clear_output from kernel  → YDoc only (no disk I/O)
#   - clear_cell_outputs        → YDoc + disk
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_output_task_does_not_clear_disk():
    """When the kernel sends clear_output (e.g. a progress bar updating),
    we should only clear the YDoc output array. The outputs_manager.clear
    method (which deletes files from disk) must NOT be called.

    Example: a tqdm progress bar sends clear_output + stream 100 times
    per second. Each clear should be a cheap YDoc array clear, not a
    disk delete that could race with the next output write.
    """
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "hello"})

    op, mock_outputs_mgr = _make_op(fake_nb)

    await op.clear_output_task("cell-1", {"wait": False})

    # YDoc outputs should be cleared
    assert len(fake_nb._outputs) == 0
    # Disk should NOT be touched
    mock_outputs_mgr.clear.assert_not_called()


@pytest.mark.anyio
async def test_clear_cell_outputs_does_clear_disk():
    """When a cell is re-executed (execute_request), the full clear
    pipeline should run: YDoc clear AND disk delete.

    Example: user presses Shift+Enter on a cell that already has output.
    The old output files need to be deleted from disk so they don't
    accumulate, and the YDoc array needs to be emptied for new output.
    """
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "old"})

    # Start with file_id=None to force a fresh lookup (simulates
    # the cache invalidation that clear_cell_outputs does internally)
    op, mock_outputs_mgr = _make_op(fake_nb, file_id=None)

    mock_session_mgr = AsyncMock()
    mock_session_mgr.get_session.return_value = {"path": "nb.ipynb"}
    mock_file_id_mgr = MagicMock()
    mock_file_id_mgr.get_id.return_value = "file-1"

    op._test_settings["session_manager"] = mock_session_mgr
    op._test_settings["file_id_manager"] = mock_file_id_mgr

    with patch.object(type(op), "parent", new_callable=lambda: property(lambda self: MagicMock(parent=MagicMock(kernel_id="k1")))):
        await op.clear_cell_outputs("cell-1")

    # YDoc outputs should be cleared
    assert len(fake_nb._outputs) == 0
    # Disk outputs SHOULD also be cleared
    mock_outputs_mgr.clear.assert_called_once_with(file_id="file-1", cell_id="cell-1")


# ---------------------------------------------------------------------------
# Simulated progress bar pattern (clear_output + stream cycle)
#
# This is the pattern that triggered the original bug. Kernels that update
# output in-place (progress bars, streaming logs) send alternating
# clear_output and stream messages:
#
#   clear_output  →  stream("Progress: 1/10")
#   clear_output  →  stream("Progress: 2/10")
#   clear_output  →  stream("Progress: 3/10")
#   ...
#
# Each clear_output should wipe the *previous* output, and the stream
# that follows should be visible to the user. The clear must not race
# with or delete the *next* output.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_clear_output_does_not_wipe_subsequent_output():
    """Simulate one iteration of the progress bar pattern:

      1. Output "Progress: 1/10" is in the cell
      2. Kernel sends clear_output → wipes "1/10"
      3. Kernel sends stream "Progress: 2/10" → should be visible

    The key assertion: after step 3, the cell has exactly one output
    ("Progress: 2/10"), and no disk clear was triggered.
    """
    fake_nb = FakeNotebook("cell-1")
    op, mock_outputs_mgr = _make_op(fake_nb)

    # Step 1: cell already has one output
    fake_nb._outputs.append({"output_type": "stream", "text": "Progress: 1/10"})

    # Step 2: clear_output arrives (kernel is about to send updated progress)
    await op.clear_output_task("cell-1", {"wait": False})
    assert len(fake_nb._outputs) == 0

    # Step 3: new output arrives with updated progress
    await op.output_task("stream", "cell-1", {
        "text": "Progress: 2/10",
        "name": "stdout",
    })
    assert len(fake_nb._outputs) == 1
    assert fake_nb._outputs[0]["text"] == "Progress: 2/10"

    # No disk operations at any point
    mock_outputs_mgr.clear.assert_not_called()


@pytest.mark.anyio
async def test_clear_output_wait_defers_to_next_output():
    """Test the clear_output protocol's ``wait=True`` mode.

    When ``wait=True``, the kernel is saying: "don't clear yet — wait
    until the next output message arrives, then clear before displaying
    it." This avoids a visible flicker between clearing and redrawing.

    Example: IPython.display.clear_output(wait=True) followed by print().

    Timeline:
      1. Cell has output "old"
      2. Kernel sends clear_output(wait=True) → cell still shows "old"
      3. Kernel sends stream("new") → output_task sees the pending clear,
         clears "old", then writes "new"
      4. Cell now shows "new" — no intermediate empty state
    """
    fake_nb = FakeNotebook("cell-1")
    fake_nb._outputs.append({"output_type": "stream", "text": "old"})

    op, _ = _make_op(fake_nb)

    # Step 2: clear_output with wait=True — should NOT clear yet
    await op.clear_output_task("cell-1", {"wait": True})
    assert len(fake_nb._outputs) == 1  # "old" is still there
    assert "cell-1" in op._pending_clear_output_cells

    # Step 3: next output arrives — should clear first, then write
    await op.output_task("stream", "cell-1", {
        "text": "new",
        "name": "stdout",
    })
    assert len(fake_nb._outputs) == 1
    assert fake_nb._outputs[0]["text"] == "new"
    assert "cell-1" not in op._pending_clear_output_cells
