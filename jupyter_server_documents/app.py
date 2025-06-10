from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config
import asyncio

from traitlets import Instance, Type
from .handlers import RouteHandler, FileIDIndexHandler
from .websockets import YRoomWebsocket
from .rooms.yroom_manager import YRoomManager
from .outputs import OutputsManager, outputs_handlers
from .events import JSD_AWARENESS_EVENT_SCHEMA, JSD_ROOM_EVENT_SCHEMA
from .jcollab_api import JCollabAPI

class ServerDocsApp(ExtensionApp):
    name = "jupyter_server_documents"
    app_name = "Collaboration"
    description = "A new implementation of real-time collaboration (RTC) in JupyterLab."

    handlers = [  # type:ignore[assignment]
        # dummy handler that verifies the server extension is installed;
        # # this can be deleted prior to initial release.
        (r"jupyter-server-documents/get-example/?", RouteHandler),
        # # ydoc websocket
        (r"api/collaboration/room/(.*)", YRoomWebsocket),
        # # handler that just adds compatibility with Jupyter Collaboration's frontend
        # (r"api/collaboration/session/(.*)", YRoomSessionHandler),
        (r"api/fileid/index", FileIDIndexHandler),
        *outputs_handlers
    ]

    yroom_manager_class = Type(
        klass=YRoomManager,
        help="""YRoom Manager Class.""",
        default_value=YRoomManager,
    ).tag(config=True)

    @property
    def yroom_manager(self) -> YRoomManager | None:
        return self.settings.get("yroom_manager", None)

    outputs_manager_class = Type(
        klass=OutputsManager,
        help="Outputs manager class.",
        default_value=OutputsManager
    ).tag(config=True)

    outputs_manager = Instance(
        klass=OutputsManager,
        help="An instance of the OutputsManager",
        allow_none=True
    ).tag(config=True)

    def initialize(self):
        super().initialize()

    def initialize_settings(self):
        # Register event schemas
        self.serverapp.event_logger.register_event_schema(JSD_ROOM_EVENT_SCHEMA)
        self.serverapp.event_logger.register_event_schema(JSD_AWARENESS_EVENT_SCHEMA)

        # Get YRoomManager arguments from server extension context.
        # We cannot access the 'file_id_manager' key immediately because server
        # extensions initialize in alphabetical order. 'jupyter_server_documents' <
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
            event_logger=self.serverapp.event_logger,
            loop=loop,
            log=log
        )

        # Initialize OutputsManager
        self.outputs_manager = self.outputs_manager_class(config=self.config)
        self.settings["outputs_manager"] = self.outputs_manager

        # Serve Jupyter Collaboration API on
        # `self.settings["jupyter_server_ydoc"]` for compatibility with
        # extensions depending on Jupyter Collaboration
        self.settings["jupyter_server_ydoc"] = JCollabAPI(
            get_fileid_manager=get_fileid_manager,
            yroom_manager=self.settings["yroom_manager"]
        )
    
    def _link_jupyter_server_extension(self, server_app):
        """Setup custom config needed by this extension."""
        c = Config()
        c.ServerApp.kernel_websocket_connection_class = "jupyter_server_documents.kernels.websocket_connection.NextGenKernelWebsocketConnection"
        c.ServerApp.kernel_manager_class = "jupyter_server_documents.kernels.multi_kernel_manager.NextGenMappingKernelManager"
        c.MultiKernelManager.kernel_manager_class = "jupyter_server_documents.kernels.kernel_manager.NextGenKernelManager"
        c.ServerApp.session_manager_class = "jupyter_server_documents.session_manager.YDocSessionManager"
        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)
    
    async def stop_extension(self):
        self.log.info("Stopping `jupyter_server_documents` server extension.")
        if self.yroom_manager:
            await self.yroom_manager.stop()
        self.log.info("`jupyter_server_documents` server extension is shut down. Goodbye!")
