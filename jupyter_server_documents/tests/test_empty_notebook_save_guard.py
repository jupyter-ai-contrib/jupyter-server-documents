"""Tests for the empty-notebook save guard in `YRoomFileAPI.save()`.

If a notebook room's YDoc source is empty (an empty ``{}`` document), saving it
would overwrite good on-disk content with a 0-byte / empty notebook. `save()`
must skip the write (and warn) instead of truncating.
"""
import logging

import pytest
from traitlets.config import LoggingConfigurable
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from jupyter_server_fileid.manager import ArbitraryFileIdManager

from ..rooms import YRoomFileAPI

GOOD_NB = (
    '{"cells": [{"cell_type": "code", "source": "1 + 1", "metadata": {}, '
    '"outputs": [], "execution_count": null}], "metadata": {}, '
    '"nbformat": 4, "nbformat_minor": 5}'
)


class _EmptyNotebook:
    """Stand-in for an empty/unloaded YNotebook whose source is ``{}``."""
    source = {}
    dirty = True


def _make_notebook_file_api(tmp_path):
    contents_manager = AsyncFileContentsManager(
        root_dir=str(tmp_path), use_atomic_writing=True
    )
    fileid_manager = ArbitraryFileIdManager(db_path=str(tmp_path / "file_id_manager.db"))
    nb_path = tmp_path / "n.ipynb"
    nb_path.write_text(GOOD_NB)
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

    return YRoomFileAPI(parent=MockYRoom()), nb_path


@pytest.mark.asyncio
async def test_save_skips_empty_notebook(tmp_path, caplog):
    file_api, nb_path = _make_notebook_file_api(tmp_path)

    with caplog.at_level(logging.WARNING):
        await file_api.save(_EmptyNotebook())

    # The good on-disk notebook must be left untouched (not truncated).
    assert nb_path.read_text() == GOOD_NB
    assert any(
        "notebook content is empty" in r.getMessage() for r in caplog.records
    )
