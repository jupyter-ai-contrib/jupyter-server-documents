try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode: https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings
    warnings.warn("Importing 'jupyter_rtc_core' outside a proper installation.")
    __version__ = "dev"

from traitlets.config import Config

from .handlers import setup_handlers
from .outputs.connection import RTCWebsocketConnection
from .outputs.handlers import setup_handlers as setup_output_handlers
from .outputs.manager import OutputsManager


def _jupyter_labextension_paths():
    return [{
        "src": "labextension",
        "dest": "@jupyter/rtc-core"
    }]


def _jupyter_server_extension_points():
    return [{
        "module": "jupyter_rtc_core"
    }]


def _link_jupyter_server_extension(server_app):
    """Setup custom config needed by this extension."""
    server_app.kernel_websocket_connection_class = RTCWebsocketConnection
    c = Config()
    c.ServerApp.kernel_websocket_connection_class = "jupyter_rtc_core.outputs.connection.RTCWebsocketConnection"
    server_app.update_config(c)


def _load_jupyter_server_extension(server_app):
    """Registers the API handler to receive HTTP requests from the frontend extension.

    Parameters
    ----------
    server_app: jupyterlab.labapp.LabApp
        JupyterLab application instance
    """
    setup_handlers(server_app.web_app)
    setup_output_handlers(server_app.web_app)
    om = OutputsManager(server_app.config)
    server_app.web_app.settings["outputs_manager"] = om

    name = "jupyter_rtc_core"
    server_app.log.info(f"Registered {name} server extension")
