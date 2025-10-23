from jupyter_server.extension.application import ExtensionApp
from traitlets.config import Config
from traitlets import Instance, Type

from nextgen_kernels_api.services.kernels.client_manager import KernelClientManager

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

    client_manager = Instance(klass=KernelClientManager, allow_none=True)

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

        # Initialize KernelClientRegistry as singleton
        # The KernelClientWebsocketConnection from nextgen-kernels-api will access this via .instance()
        self.client_manager = KernelClientManager.instance(
            parent=self,
            multi_kernel_manager=self.serverapp.kernel_manager
        )
        self.settings["client_manager"] = self.client_manager

        # Register event listener for client management
        self.client_manager.register_event_listener(self.serverapp.event_logger)

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
        # Use nextgen-kernels-api's multi-kernel manager
        # This manager disables activity watching and buffering (which we don't need)
        c.ServerApp.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.MultiKernelManager"
        c.ServerApp.kernel_websocket_connection_class = 'nextgen_kernels_api.services.kernels.connection.kernel_client_connection.KernelClientWebsocketConnection'

        # Configure MultiKernelManager to use nextgen's KernelManager
        c.MultiKernelManager.kernel_manager_class = "nextgen_kernels_api.services.kernels.kernelmanager.KernelManager"

        # Configure the KernelManager to use DocumentAwareKernelClient
        c.KernelManager.client_class = "jupyter_server_documents.kernel_client.DocumentAwareKernelClient"
        c.KernelManager.client_factory = "jupyter_server_documents.kernel_client.DocumentAwareKernelClient"

        # Use custom session manager for YRoom integration
        c.ServerApp.session_manager_class = "jupyter_server_documents.session_manager.YDocSessionManager"

        # Configure websocket connection to exclude output messages
        # Output messages are handled by DocumentAwareKernelClient's output processor
        # and should not be sent to websocket clients to avoid duplicate processing
        c.KernelClientWebsocketConnection.exclude_msg_types = [
            ("status", "iopub"),
            ("stream", "iopub"),
            ("display_data", "iopub"),
            ("execute_result", "iopub"),
            ("error", "iopub"),
            ("update_display_data", "iopub"),
            ("clear_output", "iopub")
        ]

        server_app.update_config(c)
        super()._link_jupyter_server_extension(server_app)
    
    async def stop_extension(self):
        self.log.info("Stopping `jupyter_server_documents` server extension.")
        if self.yroom_manager:
            await self.yroom_manager.stop()
        self.log.info("`jupyter_server_documents` server extension is shut down. Goodbye!")
