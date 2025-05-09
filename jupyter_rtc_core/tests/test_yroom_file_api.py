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
def mock_plaintext_file(tmp_path):
    # Copy mock file to /tmp
    src_path = Path(__file__).parent / "mocks" / "mock_plaintext.txt"
    target_path = tmp_path / "mock_plaintext.txt"
    shutil.copy(src_path, target_path)

    # Yield the path to the tmp mock plaintext file as a str
    yield str(target_path)

    # Cleanup
    os.remove(target_path)

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

    file_id = fileid_manager.index(mock_plaintext_file)
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
    )
    return yroom_file_api


@pytest.mark.asyncio(loop_scope="module")
async def test_load_plaintext_file(plaintext_file_api: Awaitable[YRoomFileAPI], mock_plaintext_file: str):
    file_api = await plaintext_file_api
    jupyter_ydoc = file_api.jupyter_ydoc
    file_api.load_ydoc_content()
    await file_api.ydoc_content_loaded
    
    # Assert that `get_jupyter_ydoc()` returns a `jupyter_ydoc.YUnicode` object
    # for plaintext files
    assert isinstance(jupyter_ydoc, YUnicode)

    # Assert that the returned JupyterYDoc has the correct content.
    with open(mock_plaintext_file) as f:
        content = f.read()
    assert jupyter_ydoc.source == content

