from __future__ import annotations
import pytest
from jupyter_server_documents.rooms.yroom_manager import YRoomManager
from jupyter_server_documents.rooms.yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeRoomFile, MakeYRoomManager


class TestYRoomManager():
    """
    Tests for `YRoomManager` basic methods.
    """

    @pytest.mark.asyncio
    async def test_get_room_creates_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that `get_room()` creates a new room if one doesn't exist."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        room = manager.get_room(room_id)
        assert room is not None
        assert isinstance(room, YRoom)

    @pytest.mark.asyncio
    async def test_get_room_returns_cached_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that `get_room()` returns the same instance on subsequent calls."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        room1 = manager.get_room(room_id)
        room2 = manager.get_room(room_id)
        assert room1 is room2

    @pytest.mark.asyncio
    async def test_has_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that `has_room()` returns correct values before and after room creation."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        assert manager.has_room(room_id) is False
        manager.get_room(room_id)
        assert manager.has_room(room_id) is True

    @pytest.mark.asyncio
    async def test_delete_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that `delete_room()` removes the room and stops it."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        room = manager.get_room(room_id)
        await room.file_api.until_content_loaded
        result = await manager.delete_room(room_id)
        assert result is True
        assert manager.has_room(room_id) is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent_room(self, make_yroom_manager: MakeYRoomManager):
        """Asserts that `delete_room()` returns True for a nonexistent room."""
        manager = make_yroom_manager()
        result = await manager.delete_room("text:file:nonexistent")
        assert result is True

    @pytest.mark.asyncio
    async def test_add_room_re_registers_stopped_room(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that add_room() re-registers a room that was deleted."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        room = manager.create_room(room_id)
        await room.file_api.until_content_loaded
        await manager.delete_room(room_id)
        assert not manager.has_room(room_id)
        manager.add_room(room)
        assert manager.has_room(room_id)

    @pytest.mark.asyncio
    async def test_add_room_noop_if_already_registered(self, make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
        """Asserts that add_room() is a no-op if the room is already in the manager."""
        manager = make_yroom_manager()
        room_id = make_room_file()
        room = manager.create_room(room_id)
        await room.file_api.until_content_loaded
        manager.add_room(room)
        assert manager.has_room(room_id)
