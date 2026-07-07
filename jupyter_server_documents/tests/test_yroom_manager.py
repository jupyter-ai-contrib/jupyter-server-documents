from __future__ import annotations
import asyncio
import pytest
from tornado.web import HTTPError
from traitlets.config import Config
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
    async def test_failed_room_is_discarded_and_recreated(
        self,
        make_yroom_manager: MakeYRoomManager,
        make_room_file: MakeRoomFile,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """
        Asserts that a room whose content load fails (after retries) is
        stopped and discarded from the manager, and that the next
        `get_room()` call creates a fresh room that loads successfully
        instead of returning the dead room (#267).
        """
        config = Config()
        config.YRoomFileAPI.load_retry_count = 1
        config.YRoomFileAPI.load_retry_delay = 0.01
        manager = make_yroom_manager(config=config)
        room_id = make_room_file()

        # Fail the first 2 reads (initial attempt + 1 retry), then recover.
        original_get = manager.contents_manager.get
        failures_left = {"count": 2}

        async def flaky_get(*args, **kwargs):
            if failures_left["count"] > 0:
                failures_left["count"] -= 1
                raise HTTPError(400, "simulated transient read failure")
            return await original_get(*args, **kwargs)

        monkeypatch.setattr(manager.contents_manager, "get", flaky_get)

        room = manager.get_room(room_id)
        assert room is not None
        with pytest.raises(HTTPError):
            await asyncio.wait_for(room.file_api.content_load_task, timeout=5)

        # Let the done-callback stop the room and discard it from the manager.
        await asyncio.sleep(0.1)
        assert manager.has_room(room_id) is False

        # The next connection creates a fresh room, which loads successfully.
        new_room = manager.get_room(room_id)
        assert new_room is not None
        assert new_room is not room
        await asyncio.wait_for(new_room.file_api.until_content_loaded, timeout=5)
        new_room.stop(immediately=True)
