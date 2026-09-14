
from jupyter_server.extension.application import ExtensionApp

from traitlets import Instance, Type
from .handlers import FileIDIndexHandler
from .websockets import YRoomWebsocket
from .rooms.yroom_manager import YRoomManager
from .rooms.ynotebook_room import YNotebookRoom
from .outputs import OutputsManager, outputs_handlers
from .events import JSD_AWARENESS_EVENT_SCHEMA, JSD_ROOM_EVENT_SCHEMA
from .jcollab_api import JCollabAPI
from .execution_handlers import executions_handlers

class ServerDocsApp(ExtensionApp):
    name = "jupyter_server_documents"
    app_name = "Collaboration"
    description = "A new implementation of real-time collaboration (RTC) in JupyterLab."

    handlers = [  # type:ignore[assignment]
        # ydoc websocket
        (r"api/collaboration/room/(.*)", YRoomWebsocket),
        (r"api/fileid/index", FileIDIndexHandler),
        *outputs_handlers,
        *executions_handlers,
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

        # Initialize OutputsManager (only if outputs service is enabled via config)
        outputs_service_enabled = self.config.get("OutputProcessor", {}).get("use_outputs_service", False)
        if outputs_service_enabled:
            self.outputs_manager = self.outputs_manager_class(parent=self)
        else:
            self.outputs_manager = None
        self.settings["outputs_manager"] = self.outputs_manager

        # Pass outputs service status and enable server-side execution in frontend
        page_config = self.serverapp.web_app.settings.setdefault("page_config_data", {})
        page_config["outputsServiceEnabled"] = str(outputs_service_enabled).lower()
        page_config["serverSideExecution"] = "true"

        # Serve Jupyter Collaboration API on
        # `self.settings["jupyter_server_ydoc"]` for compatibility with
        # extensions depending on Jupyter Collaboration
        self.settings["jupyter_server_ydoc"] = JCollabAPI(
            get_fileid_manager=get_fileid_manager,
            yroom_manager=self.settings["yroom_manager"]
        )

        # React to kernel restart / interrupt / shutdown for connected rooms
        # (see _register_kernel_action_listener).
        self._register_kernel_action_listener()

    # ── kernel_actions/v1 handling (restart / interrupt) ──────────────────────

    KERNEL_ACTIONS_SCHEMA = "https://events.jupyter.org/jupyter_server/kernel_actions/v1"

    def _register_kernel_action_listener(self):
        """Subscribe to jupyter_server's ``kernel_actions/v1`` events.

        A restart preserves the kernel_id, so a room's lazy execute-time
        binding can't tell its client went stale; and an interrupt must drop
        cells queued behind the running one. The document<->kernel binding is
        established lazily by the execute endpoint, so these events are handled
        here rather than at session-creation time.
        """
        el = getattr(self.serverapp, "event_logger", None)
        if el is None:
            return
        el.add_listener(
            schema_id=self.KERNEL_ACTIONS_SCHEMA,
            listener=self._on_kernel_action,
        )

    def _unregister_kernel_action_listener(self):
        el = getattr(self.serverapp, "event_logger", None)
        if el is None:
            return
        try:
            el.remove_listener(listener=self._on_kernel_action)
        except Exception:
            self.log.debug("Failed to remove kernel_actions listener", exc_info=True)

    def _rooms_for_kernel(self, kernel_id):
        """The loaded YNotebookRooms currently bound to ``kernel_id``."""
        ym = self.yroom_manager
        if ym is None:
            return []
        return [
            room
            for room in ym.get_rooms()
            if isinstance(room, YNotebookRoom) and room.connected_kernel_id == kernel_id
        ]

    async def _on_kernel_action(self, logger, schema_id, data):
        """React to kernel lifecycle events for bound rooms:

        - restart (keeps the same kernel_id, so lazy execute-time binding can't
          tell the client went stale) -> reconnect the room's client
        - interrupt -> drop cells queued behind the running one
        - shutdown (e.g. culled) -> disconnect the room's client so it doesn't
          hold channels on a kernel whose zmq context is being torn down
        """
        action = data.get("action")
        kernel_id = data.get("kernel_id")
        if not action or not kernel_id:
            return
        try:
            if action == "restart" and data.get("status") == "success":
                for room in self._rooms_for_kernel(kernel_id):
                    await room.handle_kernel_restart()
            elif action == "interrupt":
                for room in self._rooms_for_kernel(kernel_id):
                    room.abort_pending_executions()
            elif action == "shutdown":
                for room in self._rooms_for_kernel(kernel_id):
                    await room.disconnect_kernel()
        except Exception as e:
            self.log.warning("kernel_actions handler for %r failed: %s", action, e)

    async def stop_extension(self):
        self.log.info("Stopping `jupyter_server_documents` server extension.")
        self._unregister_kernel_action_listener()
        if self.yroom_manager:
            await self.yroom_manager.stop()
        self.log.info("`jupyter_server_documents` server extension is shut down. Goodbye!")
