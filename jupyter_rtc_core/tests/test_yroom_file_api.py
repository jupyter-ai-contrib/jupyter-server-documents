import pytest
import logging
import shutil
from pathlib import Path
import os

from ..rooms import YRoomFileAPI
from jupyter_server_fileid.manager import ArbitraryFileIdManager

@pytest.fixture
def mock_plaintext_file(tmp_path):
    # Copy mock file to /tmp
    src_path = Path(__file__).parent / "mock_plaintext.txt"
    target_path = tmp_path / "mock_plaintext.txt"
    shutil.copy(src_path, target_path)

    # Yield the path to the tmp mock plaintext file
    yield target_path

    # Cleanup
    os.remove(target_path)

@pytest.fixture
def plaintext_file_api():
    log = logging.Logger(name="PlaintextFileAPI")
    fileid_manager = ArbitraryFileIdManager()

# TODO
