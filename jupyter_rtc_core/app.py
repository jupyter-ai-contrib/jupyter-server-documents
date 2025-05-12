from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config

from .handlers import RouteHandler
from .websockets import GlobalAwarenessWebsocket, YRoomWebsocket
from .rooms import YRoomManager

class RtcExtensionApp(ExtensionApp):
    name = "jupyter_rtc_core"
    app_name = "Collaboration"
    description = "A new implementation of real-time collaboration (RTC) in JupyterLab."

    handlers = [  # type:ignore[assignment]
        # dummy handler that verifies the server extension is installed;
        # this can be deleted prior to initial release.
        (r"jupyter-rtc-core/get-example/?", RouteHandler),
        # global awareness websocket
        # (r"api/collaboration/room/JupyterLab:globalAwareness/?", GlobalAwarenessWebsocket),
        # # ydoc websocket
        # (r"api/collaboration/room/(.*)", YRoomWebsocket)
    ]

    def initialize(self):
        super().initialize()


    def initialize_settings(self):
        # Initialize YRoomManager
        self.settings["yroom_manager"] = YRoomManager()
    

    def _link_jupyter_server_extension(self, server_app):
        """Setup custom config needed by this extension."""
        c = Config()
        c.ServerApp.kernel_websocket_connection_class = "jupyter_rtc_core.kernels.websocket_connection.NextGenKernelWebsocketConnection"
        c.ServerApp.kernel_manager_class = "jupyter_rtc_core.kernels.multi_kernel_manager.NextGenMappingKernelManager"
        c.MultiKernelManager.kernel_manager_class = "jupyter_rtc_core.kernels.kernel_manager.NextGenKernelManager"
        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)