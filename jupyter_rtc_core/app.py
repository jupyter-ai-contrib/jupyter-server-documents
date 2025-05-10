from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config
from traitlets import Instance
from traitlets import Type
from .handlers import RouteHandler
from .websockets import GlobalAwarenessWebsocket, YRoomWebsocket
from .rooms.yroom_manager import YRoomManager

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

    yroom_manager_class = Type(
        klass=YRoomManager,
        help="""YRoom Manager Class.""",
        default_value=YRoomManager,
    ).tag(config=True)

    yroom_manager = Instance(
        klass=YRoomManager,
        help="An instance of the YRoom Manager.",
        allow_none=True
    ).tag(config=True)

    def initialize_settings(self):
        self.yroom_manager = self.yroom_manager_class(parent=self)
        self.settings.update({"yroom_manager": self.yroom_manager})

    def initialize(self):
        super().initialize()

    def _link_jupyter_server_extension(self, server_app):
        """Setup custom config needed by this extension."""
        c = Config()
        c.ServerApp.kernel_websocket_connection_class = "jupyter_rtc_core.kernels.websocket_connection.NextGenKernelWebsocketConnection"
        c.ServerApp.kernel_manager_class = "jupyter_rtc_core.kernels.multi_kernel_manager.NextGenMappingKernelManager"
        c.MultiKernelManager.kernel_manager_class = "jupyter_rtc_core.kernels.kernel_manager.NextGenKernelManager"
        c.ServerApp.session_manager_class = "jupyter_rtc_core.session_manager.YDocSessionManager"
        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)
