from __future__ import annotations
import pytest
import pytest_asyncio

import asyncio
import logging
import os
import uuid
import weakref
from traitlets.config import Config, LoggingConfigurable
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from typing import TYPE_CHECKING
from jupyter_server_documents.rooms.yroom_manager import YRoomManager
from jupyter_server_documents.rooms.yroom import YRoom

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Callable, Coroutine
    from jupyter_server.serverapp import ServerApp

    MakeRoomFile = Callable[..., str]
    MakeYRoomManager = Callable[..., YRoomManager]
    MakeYRoom = Callable[..., Coroutine[None, None, YRoom]]


pytest_plugins = ("pytest_jupyter.jupyter_server", "jupyter_server.pytest_plugin", "pytest_asyncio")


def pytest_configure(config):
    """Configure pytest settings."""
    # Set asyncio fixture loop scope to function to avoid warnings
    config.option.asyncio_default_fixture_loop_scope = "function"


@pytest.fixture
def jp_server_config(jp_server_config, tmp_path):
    """
    Fixture that defines the traitlets configuration used in unit tests.
    """

    return Config({
        "ServerApp": {
            "jpserver_extensions": {
                "jupyter_server_documents": True,
                "jupyter_server_fileid": True
            },
            "root_dir": str(tmp_path)
        },
        "ContentsManager": {"root_dir": str(tmp_path)},
        # Keep the file ID database inside tmp_path so CI runners that restrict
        # writes to the home directory don't fail with OperationalError.
        "ArbitraryFileIdManager": {"db_path": str(tmp_path / "file_id_manager.db")}
    })

class MockServerDocsApp(LoggingConfigurable):
    """Mock `ServerDocsApp` class for testing purposes."""

    serverapp: ServerApp

    # Mirror `ServerDocsApp` with the outputs service disabled (the default): the
    # attribute exists and is `None`. `YRoomManager.outputs_manager` checks for the
    # attribute's presence, so without this a notebook room's content load raises
    # "Outputs manager is not available".
    outputs_manager = None

    def __init__(self, *args, serverapp: ServerApp, **kwargs):
        super().__init__(*args, **kwargs)
        self.serverapp = serverapp
        self._log = None
        
    @property
    def log(self) -> logging.Logger:
        return self.serverapp.log
        
    @property
    def event_loop(self) -> asyncio.AbstractEventLoop:
        return self.serverapp.io_loop.asyncio_loop
    
    @property
    def contents_manager(self) -> AsyncFileContentsManager:
        return self.serverapp.contents_manager


@pytest.fixture
def mock_server_docs_app(jp_server_config, jp_configurable_serverapp) -> MockServerDocsApp:
    """
    Returns a mocked `MockServerDocsApp` object that can be passed as the `parent`
    argument to objects normally initialized by `ServerDocsApp` in `app.py`.
    This should be passed to most of the "manager singletons" like
    `YRoomManager`.

    See `MockServerDocsApp` in `conftest.py` for a complete description of the
    attributes, properties, and methods available. If something is missing,
    please feel free to add to it in your PR.
    
    Returns:
        A `MockServerDocsApp` instance that can be passed as the `parent` argument
        to objects normally initialized by `ServerDocsApp`.
    """
    serverapp = jp_configurable_serverapp()
    return MockServerDocsApp(config=jp_server_config, serverapp=serverapp)

@pytest.fixture
def make_yroom_manager(mock_server_docs_app: MockServerDocsApp) -> MakeYRoomManager:
    """
    Factory fixture that returns a configured `YRoomManager` instance.
    Accepts optional kwargs passed to the `YRoomManager` constructor.
    """
    def _make_yroom_manager(**kwargs) -> YRoomManager:
        return YRoomManager(parent=mock_server_docs_app, **kwargs)

    return _make_yroom_manager


@pytest_asyncio.fixture
async def make_yroom(make_yroom_manager: MakeYRoomManager, make_room_file: MakeRoomFile):
    """
    Factory fixture that returns a configured `YRoom` instance.

    Accepts:
      - `file_type`: one of `"file"` (default), `"notebook"`, or `"chat"`, passed
        through to `make_room_file` to select the document type.
      - any other kwargs are passed to the `YRoom` constructor (e.g.
        `inactivity_timeout`).
    """
    manager = make_yroom_manager()
    # Track rooms weakly so this fixture never pins a room alive -- GC tests rely on
    # dropping their own reference and asserting the room is collected.
    rooms: weakref.WeakSet[YRoom] = weakref.WeakSet()

    async def _make_yroom(file_type: str = "file", **kwargs) -> YRoom:
        room_id = make_room_file(file_type=file_type)
        # Use the manager's factory so the correct room class is chosen per file
        # type (e.g. `YNotebookRoom` for notebooks) and the room is registered in
        # the manager, matching real usage.
        room = manager.create_room(room_id, **kwargs)
        await room.file_api.until_content_loaded
        rooms.add(room)
        return room

    yield _make_yroom

    # Best-effort cleanup of any rooms still alive (and not already stopped).
    for room in list(rooms):
        if not room.stopped:
            room.stop(immediately=True)


# Per-file-type parameters for `make_room_file` / `make_yroom`. Each entry maps a
# `file_type` to the file extension, the room ID's `{file_format}:{file_type}`
# prefix (see `YRoom` room ID docs), and the initial on-disk content the
# corresponding Jupyter YDoc expects to load.
_ROOM_FILE_TYPES = {
    "file": {"ext": "txt", "prefix": "text:file", "content": ""},
    "notebook": {
        "ext": "ipynb",
        "prefix": "json:notebook",
        "content": '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}',
    },
    "chat": {"ext": "chat", "prefix": "text:chat", "content": "{}"},
}


@pytest.fixture
def make_room_file(tmp_path: Path, make_yroom_manager: MakeYRoomManager, request: pytest.FixtureRequest) -> MakeRoomFile:
    """
    Factory fixture that creates a document file and returns its room ID.

    Accepts:
      - `file_type`: one of `"file"` (default), `"notebook"`, or `"chat"`. Selects
        the file extension, room ID prefix, and initial content.
      - `filename`: an optional explicit filename (overrides the generated one).

    The file is created under `tmp_path` and cleaned up after the test.
    """
    manager = make_yroom_manager()
    created_files: list[Path] = []

    def _make_room_file(file_type: str = "file", filename: str | None = None) -> str:
        try:
            spec = _ROOM_FILE_TYPES[file_type]
        except KeyError:
            raise ValueError(
                f"unknown file_type {file_type!r}; "
                f"expected one of {sorted(_ROOM_FILE_TYPES)}"
            )
        if filename is None:
            filename = f"{uuid.uuid4()}.{spec['ext']}"
        path = tmp_path / filename
        path.write_text(spec["content"])
        created_files.append(path)
        file_id = manager.fileid_manager.index(str(path))
        return f"{spec['prefix']}:{file_id}"

    def _cleanup():
        for path in created_files:
            if path.exists():
                os.remove(path)

    request.addfinalizer(_cleanup)
    return _make_room_file
