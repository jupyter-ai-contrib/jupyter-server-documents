import pytest

pytest_plugins = ("pytest_jupyter.jupyter_server", "jupyter_server.pytest_plugin", "pytest_asyncio")


def pytest_configure(config):
    """Configure pytest settings."""
    # Set asyncio fixture loop scope to function to avoid warnings
    config.option.asyncio_default_fixture_loop_scope = "function"


@pytest.fixture
def jp_server_config(jp_server_config):
    return {"ServerApp": {"jpserver_extensions": {"jupyter_server_documents": True}}}
