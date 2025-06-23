import pytest
import pytest_asyncio
import logging
import shutil
from pathlib import Path
import os
import asyncio
from typing import Awaitable
import pycrdt

from ..rooms import YRoomFileAPI
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from jupyter_server_fileid.manager import ArbitraryFileIdManager, BaseFileIdManager
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


@pytest_asyncio.fixture(loop_scope="module")
async def plaintext_file_api(
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
    log = logging.Logger(name="PlaintextFileAPI")
    contents_manager = jp_contents_manager
    loop = asyncio.get_running_loop()
    def noop():
        pass

    yroom_file_api = YRoomFileAPI(
        room_id=room_id,
        contents_manager=contents_manager,
        fileid_manager=fileid_manager,
        log=log,
        loop=loop,
        on_inband_deletion=noop,
        on_outofband_change=noop,
        on_outofband_move=noop
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
    plaintext_file_api: Awaitable[YRoomFileAPI],
    empty_yunicode: YUnicode,
    mock_plaintext_file: str,
):
    # Load content into JupyterYDoc
    file_api = await plaintext_file_api
    jupyter_ydoc = empty_yunicode
    file_api.load_content_into(jupyter_ydoc)
    await file_api.until_content_loaded
    
    # Assert that the returned JupyterYDoc has the correct content.
    with open(mock_plaintext_file) as f:
        content = f.read()
    assert jupyter_ydoc.source == content
    
    # stop file file api to avoid coroutine warnings
    file_api.stop()

