import asyncio
import pytest
import pytest_asyncio
import shutil
from pathlib import Path
import os
from typing import Awaitable
import pycrdt
from tornado.web import HTTPError
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
async def test_load_retries_transient_failure(
    plaintext_file_api: YRoomFileAPI,
    empty_yunicode: YUnicode,
    mock_plaintext_file: str,
    jp_contents_manager: AsyncFileContentsManager,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Asserts that the content load retries and succeeds when the first read
    fails transiently, e.g. when the load races a concurrent write to a
    newly-created file (#267).
    """
    file_api = plaintext_file_api
    file_api.load_retry_delay = 0.01

    original_get = jp_contents_manager.get
    call_count = {"total": 0}

    async def flaky_get(*args, **kwargs):
        call_count["total"] += 1
        if call_count["total"] == 1:
            raise HTTPError(400, "simulated transient read failure")
        return await original_get(*args, **kwargs)

    monkeypatch.setattr(jp_contents_manager, "get", flaky_get)

    file_api.load_content_into(empty_yunicode)
    await asyncio.wait_for(file_api.until_content_loaded, timeout=5)

    with open(mock_plaintext_file) as f:
        assert empty_yunicode.source == f.read()
    assert call_count["total"] == 2

    file_api.stop()


@pytest.mark.asyncio(loop_scope="module")
async def test_load_failure_is_observable_and_recoverable(
    plaintext_file_api: YRoomFileAPI,
    empty_yunicode: YUnicode,
    jp_contents_manager: AsyncFileContentsManager,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Asserts that when every load attempt fails, the exception is observable
    on `content_load_task` and the file API allows a later
    `load_content_into()` call to retry, instead of reporting
    "already loading" forever (#267).
    """
    file_api = plaintext_file_api
    file_api.load_retry_count = 1
    file_api.load_retry_delay = 0.01

    async def failing_get(*args, **kwargs):
        raise HTTPError(400, "simulated permanent read failure")

    monkeypatch.setattr(jp_contents_manager, "get", failing_get)

    file_api.load_content_into(empty_yunicode)
    assert file_api.content_load_task is not None
    with pytest.raises(HTTPError):
        await asyncio.wait_for(file_api.content_load_task, timeout=5)

    assert not file_api.content_loaded
    # A new `load_content_into()` call must be able to start a fresh attempt.
    monkeypatch.undo()
    file_api.load_content_into(empty_yunicode)
    await asyncio.wait_for(file_api.until_content_loaded, timeout=5)

    file_api.stop()

