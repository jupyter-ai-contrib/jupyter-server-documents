from __future__ import annotations
import pytest
import pytest_asyncio
import os
from unittest.mock import Mock
from jupyter_server_documents.rooms.yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from jupyter_server_documents.rooms import YRoomManager

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
async def default_yroom(mock_yroom_manager: YRoomManager, mock_textfile_path: Path):
    """
    Returns a configured `YRoom` instance that serves an empty text file under
    `/tmp`.

    Uses the `mock_yroom_manager` fixture defined in `conftest.py`.
    """
    # Get room ID
    file_id = mock_yroom_manager.fileid_manager.index(str(mock_textfile_path))
    room_id = f"text:file:{file_id}"

    # Initialize room and wait until its content is loaded
    room: YRoom = YRoom(parent=mock_yroom_manager, room_id=room_id)
    await room.file_api.until_content_loaded

    # Yield configured `YRoom`
    yield room

    # Cleanup
    room.stop(immediately=True)

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

