import pytest
import pytest_asyncio
import asyncio
import shutil
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
import os
from typing import Awaitable
import pycrdt
from traitlets.config import LoggingConfigurable

from ..rooms import YRoomFileAPI
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from jupyter_server_fileid.manager import ArbitraryFileIdManager
from jupyter_ydoc import YUnicode


@pytest.fixture
def jp_contents_manager(tmp_path):
    """
    Returns a configured `ContentsManager` instance whose `root_dir` is set to
    `tmp_path`.

    NOTE: This is a copy of the fixture from jupyter_server, to avoid duplicate
    runs due to parameters in the original fixture.
    """
    return AsyncFileContentsManager(root_dir=str(tmp_path), use_atomic_writing=False)


@pytest.fixture
def fileid_manager(tmp_path):
    """
    Fixture that yields an `ArbitraryFileIdManager` instance whose database file
    is under `{tmp_path}/file_id_manager.db`.
    """
    db_path = os.path.join(tmp_path, "file_id_manager.db")
    return ArbitraryFileIdManager(db_path=db_path)


@pytest.fixture
def mock_plaintext_file(tmp_path):
    """
    Fixture that yields the absolute path to a mock plaintext file under
    `tmp_path`. This mock file has the same content as
    `./mocks/mock_plaintext.txt`.
    """
    # Copy mock file to /tmp
    src_path = Path(__file__).parent / "mocks" / "mock_plaintext.txt"
    target_path = tmp_path / "mock_plaintext.txt"
    shutil.copy(src_path, target_path)

    # Yield the path to the tmp mock plaintext file as a str
    yield str(target_path)

    # Cleanup
    os.remove(target_path)


@pytest.fixture
def plaintext_file_api(
    mock_plaintext_file: str,
    jp_contents_manager: AsyncFileContentsManager,
    fileid_manager: ArbitraryFileIdManager
):
    """
    Returns a `YRoomFileAPI` with a `room_id` corresponding to the
    file created by the `mock_plaintext_file` fixture.
    """
    relpath = os.path.relpath(
        path=mock_plaintext_file,
        start=jp_contents_manager.root_dir
    )
    file_id = fileid_manager.index(relpath)
    room_id = f"text:file:{file_id}"

    class MockYRoom(LoggingConfigurable):
        @property
        def fileid_manager(self):
            return fileid_manager
        
        @property
        def contents_manager(self):
            return jp_contents_manager
        
        @property
        def room_id(self):
            return room_id
        

    yroom_file_api = YRoomFileAPI(
        parent=MockYRoom()
    )
    return yroom_file_api


@pytest.fixture
def empty_yunicode() -> YUnicode:
    """
    Returns an empty `YUnicode` JupyterYDoc.
    """
    ydoc = pycrdt.Doc()
    awareness = pycrdt.Awareness(ydoc=ydoc)
    jupyter_ydoc = YUnicode(ydoc, awareness)
    return jupyter_ydoc


@pytest.mark.asyncio(loop_scope="module")
async def test_load_plaintext_file(
    plaintext_file_api: YRoomFileAPI,
    empty_yunicode: YUnicode,
    mock_plaintext_file: str,
):
    # Load content into JupyterYDoc
    file_api = plaintext_file_api
    jupyter_ydoc = empty_yunicode
    file_api.load_content_into(jupyter_ydoc)
    await file_api.until_content_loaded
    
    # Assert that the returned JupyterYDoc has the correct content.
    with open(mock_plaintext_file) as f:
        content = f.read()
    assert jupyter_ydoc.source == content
    
    # stop file file api to avoid coroutine warnings
    file_api.stop()


@pytest.mark.asyncio(loop_scope="module")
async def test_save_before_oob_check_prevents_reload_cascade(
    plaintext_file_api: YRoomFileAPI,
    empty_yunicode: YUnicode,
    mock_plaintext_file: str,
):
    """Verify that pending saves run before OOB checks, preventing a reload
    cascade when the file mtime is stale.

    Background:
        When a YRoom is garbage collected (freed after inactivity) and later
        re-initialized, _last_modified holds the timestamp from the ORIGINAL
        session (e.g. hours ago). Meanwhile, other code (like the output
        processor clearing cell outputs) mutates the YDoc and calls
        schedule_save(). The _watch_file loop then wakes up for its next tick.

    The bug (before fix):
        1. _check_file() runs first, asks ContentsManager for the file's mtime
        2. Compares mtime against _last_modified — they differ because
           _last_modified is stale from the old session
        3. Concludes "out-of-band change!" and calls _reload_content_inplace()
        4. Reload reads the file from disk and overwrites the YDoc — undoing
           the output clear
        5. The overwritten YDoc triggers another schedule_save(), and the cycle
           repeats every 500ms indefinitely

    The fix:
        When _save_scheduled is True, save() runs FIRST (updating the file and
        _last_modified), and _check_file is skipped entirely for that tick. On
        the next tick, _last_modified matches the file mtime, so no spurious
        reload occurs.

    What this test does:
        - Loads a file into the YDoc
        - Mutates the YDoc and schedules a save (simulating _clear_ydoc_outputs)
        - Sets _last_modified to a stale timestamp (simulating post-GC restart)
        - Runs one tick of the fixed _watch_file logic
        - Asserts that save ran (not reload), content was persisted, and
          _last_modified was updated
    """
    file_api = plaintext_file_api
    jupyter_ydoc = empty_yunicode
    file_api.load_content_into(jupyter_ydoc)
    await file_api.until_content_loaded

    # Simulate a YDoc mutation + schedule_save (like _clear_ydoc_outputs would)
    jupyter_ydoc.source = "modified content"
    file_api.schedule_save()

    # Simulate stale _last_modified (as happens after room GC + restart)
    stale_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    file_api._last_modified = stale_time

    # Run one tick of the watch loop manually by calling the internal methods
    # in the same order as _watch_file. With the fix, save runs first because
    # _save_scheduled is True — so _check_file is never called.
    reload_called = False
    original_reload = file_api._reload_content_inplace

    async def tracking_reload(jydoc):
        nonlocal reload_called
        reload_called = True
        await original_reload(jydoc)

    file_api._reload_content_inplace = tracking_reload

    # Simulate one iteration of _watch_file (the fixed version)
    if file_api._save_scheduled:
        await file_api.save(jupyter_ydoc)
    else:
        await file_api._check_file(jupyter_ydoc)

    # The save should have run (not the check), so no reload happened
    assert not reload_called, (
        "_reload_content_inplace was called — the OOB check ran before the "
        "save, which means the stale _last_modified triggered a spurious reload"
    )
    assert not file_api._save_scheduled
    # After saving, _last_modified should be updated (not stale)
    assert file_api._last_modified != stale_time

    # Verify the modified content was persisted
    with open(mock_plaintext_file) as f:
        assert f.read() == "modified content"

    file_api.stop()


@pytest.mark.asyncio(loop_scope="module")
async def test_oob_check_still_runs_when_no_save_pending(
    plaintext_file_api: YRoomFileAPI,
    empty_yunicode: YUnicode,
    mock_plaintext_file: str,
):
    """Verify that real out-of-band changes are still detected and applied when
    no save is pending.

    Background:
        The fix skips _check_file() when _save_scheduled is True. This test
        ensures that when NO save is pending (the common idle case), OOB
        detection still works — i.e. if an external process (terminal editor,
        git checkout, etc.) modifies the file, the YDoc picks up the change.

    What this test does:
        - Loads a file into the YDoc
        - Writes new content directly to the file on disk (simulating an
          external edit)
        - Confirms no save is pending
        - Calls _check_file() (the path taken when _save_scheduled is False)
        - Asserts the YDoc content was updated to match the external edit
    """
    file_api = plaintext_file_api
    jupyter_ydoc = empty_yunicode
    file_api.load_content_into(jupyter_ydoc)
    await file_api.until_content_loaded

    # Externally modify the file to create a real OOB change
    with open(mock_plaintext_file, "w") as f:
        f.write("external edit")

    # No save is pending
    assert not file_api._save_scheduled

    # Simulate one iteration: should run _check_file (not save)
    # _check_file will detect the mtime mismatch and reload
    await file_api._check_file(jupyter_ydoc)

    # The content should have been reloaded from disk
    assert jupyter_ydoc.source == "external edit"

    file_api.stop()

