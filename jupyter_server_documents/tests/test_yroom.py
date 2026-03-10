from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import Mock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom, MakeYRoomManager, MakeRoomFile


class TestYRoomCallbacks():
    """
    Tests for `YRoom` on_reset and on_stop callback behavior.
    """

    @pytest.mark.asyncio
    async def test_on_reset_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that the `on_reset()` callback passed to
        `YRoom.get_{awareness,jupyter_ydoc,ydoc}()` methods are each called with
        the expected object when the YDoc is reset.
        """
        yroom = await make_yroom()
        
        # Create mock callbacks
        awareness_reset_mock = Mock()
        jupyter_ydoc_reset_mock = Mock()
        ydoc_reset_mock = Mock()
        
        # Call get methods while passing `on_reset` callbacks
        yroom.get_awareness(on_reset=awareness_reset_mock)
        await yroom.get_jupyter_ydoc(on_reset=jupyter_ydoc_reset_mock)
        await yroom.get_ydoc(on_reset=ydoc_reset_mock)
        
        # Assert that each callback has not been called yet
        awareness_reset_mock.assert_not_called()
        jupyter_ydoc_reset_mock.assert_not_called()
        ydoc_reset_mock.assert_not_called()
        
        # Reset the ydoc and get the new expected objects
        yroom._reset_ydoc()
        new_awareness = yroom.get_awareness()
        new_jupyter_ydoc = await yroom.get_jupyter_ydoc()
        new_ydoc = await yroom.get_ydoc()
        
        # Assert that each callback was called exactly once with the expected
        # object
        awareness_reset_mock.assert_called_once_with(new_awareness)
        jupyter_ydoc_reset_mock.assert_called_once_with(new_jupyter_ydoc)
        ydoc_reset_mock.assert_called_once_with(new_ydoc)

    @pytest.mark.asyncio
    async def test_on_stop_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks registered via `add_stop_callback()`
        are called when the room is stopped.
        """
        yroom = await make_yroom()

        stop_mock_1 = Mock()
        stop_mock_2 = Mock()

        yroom.add_stop_callback(stop_mock_1)
        yroom.add_stop_callback(stop_mock_2)

        stop_mock_1.assert_not_called()
        stop_mock_2.assert_not_called()

        yroom.stop()

        stop_mock_1.assert_called_once()
        stop_mock_2.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_does_not_fire_on_stop(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks are not called when the room is
        restarted (since restarting passes `restarting=True` to `stop()`).
        """
        yroom = await make_yroom()

        stop_mock = Mock()
        yroom.add_stop_callback(stop_mock)

        yroom.restart()

        stop_mock.assert_not_called()


class TestCellAwarenessAPI():
    """
    Tests for the cell awareness API on YNotebook (accessed via YRoom.jupyter_ydoc).
    """

    @pytest.mark.asyncio
    async def test_set_cell_awareness(self, make_yroom: MakeYRoom):
        """Set data for a cell in a namespace and read it back."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "execution_state", {"status": "running"})
        result = notebook.get_cell_awareness("cell-1", "execution_state")
        assert result == {"status": "running"}

    @pytest.mark.asyncio
    async def test_update_cell_awareness_merges_fields(self, make_yroom: MakeYRoom):
        """Set initial data, then update with partial fields and verify merge."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "execution_state", {"status": "running", "count": 1})
        notebook.update_cell_awareness("cell-1", "execution_state", count=2, new_field="hello")
        result = notebook.get_cell_awareness("cell-1", "execution_state")
        assert result == {"status": "running", "count": 2, "new_field": "hello"}

    @pytest.mark.asyncio
    async def test_update_cell_awareness_ignores_none(self, make_yroom: MakeYRoom):
        """Verify that None values are not merged into existing data."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "ns", {"a": 1, "b": 2})
        notebook.update_cell_awareness("cell-1", "ns", a=None, b=3)
        result = notebook.get_cell_awareness("cell-1", "ns")
        assert result == {"a": 1, "b": 3}

    @pytest.mark.asyncio
    async def test_remove_cell_awareness(self, make_yroom: MakeYRoom):
        """Set data, remove it, and verify it returns empty dict."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "ns", {"data": True})
        notebook.remove_cell_awareness("cell-1", "ns")
        result = notebook.get_cell_awareness("cell-1", "ns")
        assert result == {}

    @pytest.mark.asyncio
    async def test_namespaces_are_isolated(self, make_yroom: MakeYRoom):
        """Two namespaces for the same cell don't interfere."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "ns_a", {"x": 1})
        notebook.set_cell_awareness("cell-1", "ns_b", {"y": 2})
        assert notebook.get_cell_awareness("cell-1", "ns_a") == {"x": 1}
        assert notebook.get_cell_awareness("cell-1", "ns_b") == {"y": 2}

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty_dict(self, make_yroom: MakeYRoom):
        """Reading data for a missing cell/namespace returns {}."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        assert notebook.get_cell_awareness("no-such-cell", "no-such-ns") == {}

    @pytest.mark.asyncio
    async def test_awareness_structure(self, make_yroom: MakeYRoom):
        """Verify data is stored under the 'cell_data' top-level awareness key."""
        room = await make_yroom()
        notebook = room.jupyter_ydoc
        notebook.set_cell_awareness("cell-1", "execution_state", {"status": "idle"})
        awareness = room.get_awareness()
        local_state = awareness.get_local_state()
        assert "cell_data" in local_state
        assert "execution_state" in local_state["cell_data"]
        assert "cell-1" in local_state["cell_data"]["execution_state"]
        assert local_state["cell_data"]["execution_state"]["cell-1"] == {"status": "idle"}


class TestYRoomInactivity():
    """
    Tests for `YRoom` inactivity timeout behavior.
    """

    @pytest.mark.asyncio
    async def test_custom_inactivity_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that `inactivity_timeout` can be set via the constructor.
        """
        room = await make_yroom(inactivity_timeout=10)
        assert room.inactivity_timeout == 10

    @pytest.mark.asyncio
    async def test_basic_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that a room becomes inactive only after `inactivity_timeout`
        elapses.
        """
        room = await make_yroom(inactivity_timeout=1)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is True

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_execution_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_awareness_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_restart_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.restart()
        await asyncio.sleep(0.6)
        assert room.inactive is False


class TestYRoomAutoRestart():
    """Tests that stopped/freed rooms auto-restart when accessed."""

    async def _make_stopped_room(self, manager, make_room_file):
        """Helper: creates a room via the manager, loads it, then deletes it."""
        room_id = make_room_file()
        room = manager.create_room(room_id)
        await room.file_api.until_content_loaded
        await manager.delete_room(room_id)
        assert room.stopped
        assert not manager.has_room(room_id)
        return room, room_id

    @pytest.mark.asyncio
    async def test_get_jupyter_ydoc_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        await room.get_jupyter_ydoc()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_get_ydoc_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        await room.get_ydoc()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_get_awareness_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.get_awareness()
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.set_cell_execution_state("cell-1", "busy")
        assert not room.stopped
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_restarts_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        manager = make_yroom_manager()
        room, room_id = await self._make_stopped_room(manager, make_room_file)
        room.set_cell_awareness_state("cell-1", "busy")
        assert not room.stopped
        assert manager.has_room(room_id)
