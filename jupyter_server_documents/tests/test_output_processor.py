import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
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
