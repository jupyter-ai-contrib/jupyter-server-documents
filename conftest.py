import pytest

pytest_plugins = ("pytest_jupyter.jupyter_server", "jupyter_server.pytest_plugin")


@pytest.fixture
def jp_server_config(jp_server_config):
    return {"ServerApp": {"jpserver_extensions": {"jupyter_server_documents": True}}}
