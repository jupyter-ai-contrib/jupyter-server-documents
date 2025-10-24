"""Document-aware kernel client for collaborative notebook editing.

This module extends nextgen-kernels-api's JupyterServerKernelClient to add
notebook-specific functionality required for real-time collaboration:

- Routes kernel messages to collaborative YRooms for document state synchronization
- Processes and separates large outputs to optimize document size
- Tracks cell execution states and updates awareness for real-time UI feedback
- Manages notebook metadata updates from kernel info
"""
import asyncio
import typing as t

from nextgen_kernels_api.services.kernels.client import JupyterServerKernelClient
from traitlets import Instance, Set, Type, default

from jupyter_server_documents.outputs import OutputProcessor
from jupyter_server_documents.rooms.yroom import YRoom


class DocumentAwareKernelClient(JupyterServerKernelClient):
    """Kernel client with collaborative document awareness and output processing.

    Extends the base JupyterServerKernelClient to integrate with YRooms for
    real-time collaboration, process outputs for optimization, and track cell
    execution states across connected clients.
    """

    _yrooms: t.Set[YRoom] = Set(trait=Instance(YRoom), default_value=set())

    output_processor = Instance(OutputProcessor, allow_none=True)

    output_processor_class = Type(
        klass=OutputProcessor, default_value=OutputProcessor
    ).tag(config=True)

    @default("output_processor")
    def _default_output_processor(self) -> OutputProcessor:
        return self.output_processor_class(parent=self, config=self.config)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Register listener for document-related messages
        # Combines state updates and outputs to share deserialization logic
        self.add_listener(
            self._handle_document_messages,
            msg_types=[
                ("kernel_info_reply", "shell"),
                ("status", "iopub"),
                ("execute_input", "iopub"),
                ("stream", "iopub"),
                ("display_data", "iopub"),
                ("execute_result", "iopub"),
                ("error", "iopub"),
                ("update_display_data", "iopub"),
                ("clear_output", "iopub"),
            ],
        )
        
    async def _handle_document_messages(self, channel_name: str, msg: list[bytes]):
        """Route kernel messages to document state and output handlers.

        Deserializes kernel protocol messages and dispatches them to appropriate
        handlers based on message type. Extracts parent message and cell ID context
        needed by most handlers.
        """
        if channel_name not in ("iopub", "shell"):
            return

        # Deserialize message components
        # Base client strips signature, leaving [header, parent_header, metadata, content, ...buffers]
        try:
            if len(msg) < 4:
                self.log.debug(f"Message too short: {len(msg)} parts")
                return

            header = self.session.unpack(msg[0])
            parent_header = self.session.unpack(msg[1])
            metadata = self.session.unpack(msg[2])

            dmsg = {
                "header": header,
                "parent_header": parent_header,
                "metadata": metadata,
                "content": msg[3],  # Keep as bytes, unpack in handlers
                "buffers": msg[4:] if len(msg) > 4 else [],
                "msg_id": header["msg_id"],
                "msg_type": header["msg_type"],
            }
        except Exception as e:
            self.log.debug(f"Skipping message that can't be deserialized: {e}")
            return

        # Extract parent message context for cell ID lookup
        parent_msg_id = dmsg.get("parent_header", {}).get("msg_id")
        parent_msg_data = self.message_cache.get(parent_msg_id) if parent_msg_id else None
        cell_id = parent_msg_data.get("cell_id") if parent_msg_data else None

        # Dispatch to appropriate handler
        msg_type = dmsg.get("msg_type")
        match msg_type:
            case "kernel_info_reply":
                await self._handle_kernel_info_reply(dmsg)
            case "status":
                await self._handle_status_message(dmsg, parent_msg_data, cell_id)
            case "execute_input":
                await self._handle_execute_input(dmsg, cell_id)
            case "stream" | "display_data" | "execute_result" | "error" | "update_display_data" | "clear_output":
                await self._handle_output_message(dmsg, msg_type, cell_id)

    async def _handle_kernel_info_reply(self, msg: dict):
        """Update notebook metadata with kernel language info."""
        content = self.session.unpack(msg["content"])
        language_info = content.get("language_info")

        if language_info:
            for yroom in self._yrooms:
                try:
                    notebook = await yroom.get_jupyter_ydoc()
                    metadata = notebook.ymeta
                    metadata["metadata"]["language_info"] = language_info
                except Exception as e:
                    self.log.warning(f"Failed to update language info for yroom: {e}")

    async def _handle_status_message(
        self, dmsg: dict, parent_msg_data: dict | None, cell_id: str | None
    ):
        """Update kernel and cell execution states from status messages.

        Updates both document-level kernel status and cell-specific execution states,
        storing them persistently and in awareness for real-time UI updates.
        """
        content = self.session.unpack(dmsg["content"])
        execution_state = content.get("execution_state")

        for yroom in self._yrooms:
            awareness = yroom.get_awareness()
            if awareness is None:
                continue

            # Update document-level kernel status if this is a top-level status message
            if parent_msg_data and parent_msg_data.get("channel") == "shell":
                awareness.set_local_state_field(
                    "kernel", {"execution_state": execution_state}
                )

            # Update cell execution state for persistence and awareness
            if cell_id:
                yroom.set_cell_execution_state(cell_id, execution_state)
                yroom.set_cell_awareness_state(cell_id, execution_state)
                break

    async def _handle_execute_input(self, dmsg: dict, cell_id: str | None):
        """Update cell execution count when execution begins."""
        if not cell_id:
            return

        content = self.session.unpack(dmsg["content"])
        execution_count = content.get("execution_count")

        if execution_count is not None:
            for yroom in self._yrooms:
                notebook = await yroom.get_jupyter_ydoc()
                _, target_cell = notebook.find_cell(cell_id)
                if target_cell:
                    target_cell["execution_count"] = execution_count
                    break

    async def _handle_output_message(self, dmsg: dict, msg_type: str, cell_id: str | None):
        """Process output messages through output processor."""
        if not cell_id:
            return

        if self.output_processor:
            content = self.session.unpack(dmsg["content"])
            self.output_processor.process_output(msg_type, cell_id, content)
        else:
            self.log.warning("No output processor configured")

    async def add_yroom(self, yroom: YRoom):
        """Register a YRoom to receive kernel messages."""
        self._yrooms.add(yroom)

    async def remove_yroom(self, yroom: YRoom):
        """Unregister a YRoom from receiving kernel messages."""
        self._yrooms.discard(yroom)

    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        """Handle messages from WebSocket clients before routing to kernel.

        Extends base implementation to:
        - Set cell awareness to 'busy' immediately on execute_request
        - Clear outputs when cell is re-executed

        This ensures UI updates happen immediately rather than waiting for
        kernel processing, providing better UX for queued executions.
        """
        try:
            header = self.session.unpack(msg[0])
            msg_id = header["msg_id"]
            msg_type = header.get("msg_type")
            metadata = self.session.unpack(msg[2])
            cell_id = metadata.get("cellId")

            if cell_id:
                # Clear outputs if this is a re-execution of the same cell
                existing = self.message_cache.get(cell_id=cell_id)
                if existing and existing["msg_id"] != msg_id:
                    asyncio.create_task(self.output_processor.clear_cell_outputs(cell_id))

                # Set awareness state immediately for queued cells
                if msg_type == "execute_request" and channel_name == "shell":
                    for yroom in self._yrooms:
                        yroom.set_cell_awareness_state(cell_id, "busy")
        except Exception as e:
            self.log.debug(f"Error handling awareness for incoming message: {e}")

        super().handle_incoming_message(channel_name, msg)
