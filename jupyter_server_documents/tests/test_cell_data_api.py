from __future__ import annotations
import json
import pytest
import pytest_asyncio
import os
from jupyter_server_documents.rooms.yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from jupyter_server_documents.rooms import YRoomManager


@pytest.fixture
def mock_notebook_path(tmp_path: Path):
    """Create a minimal notebook file with one code cell."""
    path = tmp_path / "test.ipynb"
    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "cells": [
            {
                "id": "test-cell-1",
                "cell_type": "code",
                "source": "print('hello')",
                "metadata": {},
                "outputs": [],
                "execution_count": None,
            }
        ],
    }
    path.write_text(json.dumps(notebook))
    yield path
    if path.exists():
        os.remove(path)


@pytest_asyncio.fixture
async def notebook_yroom(mock_yroom_manager: YRoomManager, mock_notebook_path: Path):
    """YRoom serving a notebook file with one cell (id: test-cell-1)."""
    file_id = mock_yroom_manager.fileid_manager.index(str(mock_notebook_path))
    room_id = f"notebook:file:{file_id}"
    room = YRoom(parent=mock_yroom_manager, room_id=room_id)
    await room.file_api.until_content_loaded
    yield room
    room.stop(immediately=True)


class TestCellMetadataAPI:
    """Tests for the generic cell metadata API on YRoom."""

    @pytest.mark.asyncio
    async def test_set_cell_metadata(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        await yroom.set_cell_metadata("test-cell-1", "execution", {"start": "T1"})

        result = await yroom.get_cell_metadata("test-cell-1", "execution")
        assert result == {"start": "T1"}

    @pytest.mark.asyncio
    async def test_update_cell_metadata_merges(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        await yroom.set_cell_metadata("test-cell-1", "execution", {"start": "T1"})
        await yroom.update_cell_metadata("test-cell-1", "execution", end="T2")

        result = await yroom.get_cell_metadata("test-cell-1", "execution")
        assert result == {"start": "T1", "end": "T2"}

    @pytest.mark.asyncio
    async def test_update_cell_metadata_ignores_none(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        await yroom.set_cell_metadata("test-cell-1", "ns", {"a": "1", "b": "2"})
        await yroom.update_cell_metadata("test-cell-1", "ns", a="new", b=None)

        result = await yroom.get_cell_metadata("test-cell-1", "ns")
        assert result == {"a": "new", "b": "2"}

    @pytest.mark.asyncio
    async def test_remove_cell_metadata(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        await yroom.set_cell_metadata("test-cell-1", "ns", {"data": True})
        await yroom.remove_cell_metadata("test-cell-1", "ns")

        result = await yroom.get_cell_metadata("test-cell-1", "ns")
        assert result == {}

    @pytest.mark.asyncio
    async def test_nonexistent_cell_returns_empty(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        result = await yroom.get_cell_metadata("no-such-cell", "ns")
        assert result == {}

    @pytest.mark.asyncio
    async def test_namespaces_isolated(self, notebook_yroom: YRoom):
        yroom = notebook_yroom
        await yroom.set_cell_metadata("test-cell-1", "ns_a", {"a": True})
        await yroom.set_cell_metadata("test-cell-1", "ns_b", {"b": True})

        assert await yroom.get_cell_metadata("test-cell-1", "ns_a") == {"a": True}
        assert await yroom.get_cell_metadata("test-cell-1", "ns_b") == {"b": True}
