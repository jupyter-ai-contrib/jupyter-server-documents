from __future__ import annotations
import pytest

import asyncio
import logging
from traitlets.config import Config, LoggingConfigurable
from jupyter_server.services.contents.filemanager import AsyncFileContentsManager
from typing import TYPE_CHECKING
from jupyter_server_documents.rooms.yroom_manager import YRoomManager

if TYPE_CHECKING:
    from jupyter_server.serverapp import ServerApp


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
        "ContentsManager": {"root_dir": str(tmp_path)}
    })

class MockServerDocsApp(LoggingConfigurable):
    """Mock `ServerDocsApp` class for testing purposes."""
    
    serverapp: ServerApp

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
def mock_yroom_manager(mock_server_docs_app) -> YRoomManager:
    """
    Returns a mocked `YRoomManager` which can be passed as the `parent` argument
    to `YRoom` for testing purposes.
    """

    return YRoomManager(parent=mock_server_docs_app)
