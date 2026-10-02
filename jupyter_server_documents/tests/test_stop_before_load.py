"""Regression test: stopping a YRoomFileAPI before the initial load must not raise.

If a room is stopped before `_load_content()` has started the watch-file task,
`stop()` used to raise ``AttributeError: 'YRoomFileAPI' object has no attribute
'_watch_file_task'``, which broke `YRoomManager.delete_room`.
"""
from traitlets.config import LoggingConfigurable
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from jupyter_server_fileid.manager import ArbitraryFileIdManager

from ..rooms import YRoomFileAPI


def _make_notebook_file_api(tmp_path):
    contents_manager = AsyncFileContentsManager(
        root_dir=str(tmp_path), use_atomic_writing=True
    )
    fileid_manager = ArbitraryFileIdManager(db_path=str(tmp_path / "file_id_manager.db"))
    (tmp_path / "n.ipynb").write_text("{}")
    file_id = fileid_manager.index("n.ipynb")
    room_id = f"json:notebook:{file_id}"

    class MockYRoom(LoggingConfigurable):
        @property
        def fileid_manager(self):
            return fileid_manager

        @property
        def contents_manager(self):
            return contents_manager

        @property
        def outputs_manager(self):
            return None

        @property
        def room_id(self):
            return room_id

    return YRoomFileAPI(parent=MockYRoom())


def test_stop_before_load_does_not_raise(tmp_path):
    file_api = _make_notebook_file_api(tmp_path)
    # No content has been loaded, so the watch-file task was never started.
    file_api.stop()  # must not raise AttributeError
    assert file_api.stopped is True
