from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config
import asyncio

from traitlets import Instance, Type
from .handlers import RouteHandler, YRoomSessionHandler, FileIDIndexHandler
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
        (r"api/collaboration/room/(.*)", YRoomWebsocket),
        # # handler that just adds compatibility with Jupyter Collaboration's frontend
        # (r"api/collaboration/session/(.*)", YRoomSessionHandler),
        (r"api/fileid/index", FileIDIndexHandler)
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


    def initialize(self):
        super().initialize()

    def initialize_settings(self):
        # Get YRoomManager arguments from server extension context.
        # We cannot access the 'file_id_manager' key immediately because server
        # extensions initialize in alphabetical order. 'jupyter_rtc_core' <
        # 'jupyter_server_fileid'.
        def get_fileid_manager():
            return self.serverapp.web_app.settings["file_id_manager"]
        contents_manager = self.serverapp.contents_manager
        loop = asyncio.get_event_loop_policy().get_event_loop()
        log = self.log

        # Initialize YRoomManager
        self.settings["yroom_manager"] = YRoomManager(
            get_fileid_manager=get_fileid_manager,
            contents_manager=contents_manager,
            loop=loop,
            log=log
        )
        pass
    

    def _link_jupyter_server_extension(self, server_app):
        """Setup custom config needed by this extension."""
        c = Config()
        c.ServerApp.kernel_websocket_connection_class = "jupyter_rtc_core.kernels.websocket_connection.NextGenKernelWebsocketConnection"
        c.ServerApp.kernel_manager_class = "jupyter_rtc_core.kernels.multi_kernel_manager.NextGenMappingKernelManager"
        c.MultiKernelManager.kernel_manager_class = "jupyter_rtc_core.kernels.kernel_manager.NextGenKernelManager"
        c.ServerApp.session_manager_class = "jupyter_rtc_core.session_manager.YDocSessionManager"
        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)
