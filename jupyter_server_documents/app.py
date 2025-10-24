from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config
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
        config=True,
    )

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

    yroom_manager = Instance(klass=YRoomManager, allow_none=True)

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

        # Initialize YRoomManager
        YRoomManagerClass = self.yroom_manager_class
        self.yroom_manager = YRoomManagerClass(parent=self)
        self.settings["yroom_manager"] = self.yroom_manager

        # Initialize OutputsManager
        self.outputs_manager = self.outputs_manager_class(parent=self)
        self.settings["outputs_manager"] = self.outputs_manager

        # Serve Jupyter Collaboration API on
        # `self.settings["jupyter_server_ydoc"]` for compatibility with
        # extensions depending on Jupyter Collaboration
        self.settings["jupyter_server_ydoc"] = JCollabAPI(
            get_fileid_manager=get_fileid_manager,
            yroom_manager=self.settings["yroom_manager"]
        )
    
    def _link_jupyter_server_extension(self, server_app):
        """Setup custom config needed by this extension.

        Only applies configuration if not already set by user config.
        """
        c = Config()

        # Configure kernel manager classes to use nextgen-kernels-api
        if not server_app.config.ServerApp.get("kernel_manager_class"):
            c.ServerApp.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.MultiKernelManager"

        if not server_app.config.ServerApp.get("kernel_websocket_connection_class"):
            c.ServerApp.kernel_websocket_connection_class = "nextgen_kernels_api.services.kernels.connection.kernel_client_connection.KernelClientWebsocketConnection"

        if not server_app.config.ServerApp.get("session_manager_class"):
            c.ServerApp.session_manager_class = "jupyter_server_documents.session_manager.YDocSessionManager"

        # Configure kernel manager hierarchy
        if not server_app.config.MultiKernelManager.get("kernel_manager_class"):
            c.MultiKernelManager.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.KernelManager"

        # Configure kernel client
        if not server_app.config.KernelManager.get("client_class"):
            c.KernelManager.client_class = "jupyter_server_documents.kernel_client.DocumentAwareKernelClient"
            c.KernelManager.client_factory = "jupyter_server_documents.kernel_client.DocumentAwareKernelClient"

        # Configure websocket message filtering
        if not server_app.config.KernelClientWebsocketConnection.get("exclude_msg_types"):
            c.KernelClientWebsocketConnection.exclude_msg_types = [
                ("status", "iopub"),
                ("stream", "iopub"),
                ("display_data", "iopub"),
                ("execute_result", "iopub"),
                ("error", "iopub"),
                ("update_display_data", "iopub"),
                ("clear_output", "iopub"),
            ]

        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)
    
    async def stop_extension(self):
        self.log.info("Stopping `jupyter_server_documents` server extension.")
        if self.yroom_manager:
            await self.yroom_manager.stop()
        self.log.info("`jupyter_server_documents` server extension is shut down. Goodbye!")
