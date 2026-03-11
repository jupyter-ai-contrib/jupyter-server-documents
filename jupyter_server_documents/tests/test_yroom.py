from __future__ import annotations
import asyncio
import pytest
import pytest_asyncio
import os
from unittest.mock import Mock
from jupyter_server_documents.rooms.yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Callable, Coroutine
    from jupyter_server_documents.rooms import YRoomManager

    MakeYRoom = Callable[..., Coroutine[None, None, YRoom]]

@pytest.fixture
def mock_textfile_path(tmp_path: Path):
    """
    Returns the path of a mock text file under `/tmp`.

    Automatically creates the file before each test & deletes the file after
    each test.
    """
    # Create file before test and yield the path
    path: Path = tmp_path / "test.txt"
    path.touch()
    yield path

    # Cleanup after test
    os.remove(path)


@pytest_asyncio.fixture
async def make_yroom(mock_yroom_manager: YRoomManager, mock_textfile_path: Path):
    """
    Factory fixture that returns a configured `YRoom` instance.
    Accepts optional kwargs passed to the `YRoom` constructor (e.g.
    `inactivity_timeout`).

    Uses the `mock_yroom_manager` fixture defined in `conftest.py`.
    """
    rooms: list[YRoom] = []

    async def _make_yroom(**kwargs) -> YRoom:
        file_id = mock_yroom_manager.fileid_manager.index(str(mock_textfile_path))
        room_id = f"text:file:{file_id}"
        room = YRoom(parent=mock_yroom_manager, room_id=room_id, **kwargs)
        await room.file_api.until_content_loaded
        rooms.append(room)
        return room

    yield _make_yroom

    for room in rooms:
        room.stop(immediately=True)


@pytest_asyncio.fixture
async def default_yroom(make_yroom: MakeYRoom):
    """
    Returns a configured `YRoom` instance that serves an empty text file under
    `/tmp`, using default settings.
    """
    yield await make_yroom()

class TestDefaultYRoom():
    """
    Tests that assert against the `default_yroom` fixture defined above.
    """

    @pytest.mark.asyncio
    async def test_on_reset_callbacks(self, default_yroom: YRoom):
        """
        Asserts that the `on_reset()` callback passed to
        `YRoom.get_{awareness,jupyter_ydoc,ydoc}()` methods are each called with
        the expected object when the YDoc is reset.
        """
        yroom = default_yroom
        
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


class TestYRoomTimeout():
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
    async def test_get_awareness_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.get_awareness()
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_get_ydoc_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        await room.get_ydoc()
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_get_jupyter_ydoc_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        await room.get_jupyter_ydoc()
        await asyncio.sleep(0.6)
        assert room.inactive is False

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
