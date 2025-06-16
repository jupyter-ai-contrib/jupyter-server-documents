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
    """A copy of the fixture from jupyter_server, to avoid duplicate runs
    due to parameters in the original fixture"""
    return AsyncFileContentsManager(root_dir=str(tmp_path), use_atomic_writing=False)


@pytest.fixture
def mock_plaintext_file(tmp_path):
    # Copy mock file to /tmp
    src_path = Path(__file__).parent / "mocks" / "mock_plaintext.txt"
    target_path = tmp_path / "mock_plaintext.txt"
    shutil.copy(src_path, target_path)

    # Yield the path to the tmp mock plaintext file as a str
    yield str(target_path)

    # Cleanup
    os.remove(target_path)

def noop():
    pass

@pytest_asyncio.fixture(loop_scope="module")
async def plaintext_file_api(mock_plaintext_file: str, jp_contents_manager: AsyncFileContentsManager):
    """
    Returns a `YRoomFileAPI` instance whose file ID refers to a file under
    `/tmp`. The mock file is the same as `mocks/mock_plaintext.txt` in this
    repo.
    """
    log = logging.Logger(name="PlaintextFileAPI")
    fileid_manager: BaseFileIdManager = ArbitraryFileIdManager()
    contents_manager = jp_contents_manager
    loop = asyncio.get_running_loop()

    filename = os.path.basename(mock_plaintext_file)
    file_id = fileid_manager.index(filename)
    room_id = f"text:file:{file_id}"
    ydoc = pycrdt.Doc()
    awareness = pycrdt.Awareness(ydoc=ydoc)
    jupyter_ydoc = YUnicode(ydoc, awareness)
    yroom_file_api = YRoomFileAPI(
        room_id=room_id,
        jupyter_ydoc=jupyter_ydoc,
        contents_manager=contents_manager,
        fileid_manager=fileid_manager,
        log=log,
        loop=loop,
        on_inband_deletion=noop,
        on_outofband_change=noop,
        on_outofband_move=noop
    )
    return yroom_file_api


@pytest.mark.asyncio(loop_scope="module")
async def test_load_plaintext_file(plaintext_file_api: Awaitable[YRoomFileAPI], mock_plaintext_file: str):
    file_api = await plaintext_file_api
    jupyter_ydoc = file_api.jupyter_ydoc
    file_api.load_content_into(jupyter_ydoc)
    await file_api.until_content_loaded
    
    # Assert that `get_jupyter_ydoc()` returns a `jupyter_ydoc.YUnicode` object
    # for plaintext files
    assert isinstance(jupyter_ydoc, YUnicode)

    # Assert that the returned JupyterYDoc has the correct content.
    with open(mock_plaintext_file) as f:
        content = f.read()
    assert jupyter_ydoc.source == content
    
    # stop file file api to avoid coroutine warnings
    file_api.stop()

