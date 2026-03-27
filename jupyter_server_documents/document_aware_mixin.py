"""Mixin to add document-awareness capabilities to kernel clients.

This mixin provides YRoom integration, output processing, and document message
handling that can be applied to both ZMQ and Gateway kernel clients.
"""
import asyncio
import typing as t

from jupyter_server_documents.outputs import OutputProcessor
from jupyter_server_documents.rooms.yroom import YRoom
from nextgen_kernels_api.services.kernels.message_utils import extract_src_id, extract_channel


class DocumentAwareMixin:
    """Mixin that adds document-awareness to kernel clients.

    Provides:
    - YRoom management for collaborative editing
    - Output processing for document optimization
    - Cell execution state tracking
    - Document message handling (kernel_info, status, execute_input, outputs)

    Can be mixed into any kernel client (ZMQ or Gateway) to add collaborative
    document features.

    Requirements:
    - Must be mixed with a class that has self.session
    - Must be mixed with a class that has self.log
    - Must have add_listener() method (from JupyterServerKernelClientMixin)
    """

    def _init_document_aware_mixin(self):
        """Initialize document-aware functionality.

        This should be called from __init__ of the concrete class.
        """
        # Initialize as regular Python attributes (not traitlets)
        # Traitlets don't work properly in mixins
        self._yrooms: t.Set[YRoom] = set()

        # Track pending async tasks so they can be cancelled on cleanup
        self._pending_tasks: set[asyncio.Task] = set()

        # Create output processor with proper parent chain if not already set
        # The parent chain allows OutputProcessor to access kernel_manager via self.parent.parent
        if not hasattr(self, 'output_processor') or self.output_processor is None:
            try:
                # Create output processor with self as parent (kernel client)
                # This gives it access to:
                # - self.parent = kernel client
                # - self.parent.parent = kernel manager (set by kernel manager)
                config = getattr(self, 'config', None)
                self.output_processor = OutputProcessor(parent=self, config=config)
                self.log.debug("Created output processor for document-aware client")
            except Exception as e:
                self.log.warning(f"Could not create output processor: {e}")
                self.output_processor = None

        # Track last message ID per cell to detect re-executions
        self._cell_msg_ids: dict[str, str] = {}

        # Register listener for all kernel messages (no msg_types filter).
        # Core handlers dispatch via match/case; registered plugin handlers
        # are called for any message type they requested.
        self.add_listener(self._handle_document_messages)

    async def _handle_document_messages(self, channel_name: str, msg: list[bytes]):
        """Route kernel messages to document state and output handlers."""
        if channel_name not in ("iopub", "shell"):
            return

        # Deserialize message components
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
            self.log.error(f"Error deserializing document message: {e}", exc_info=True)
            return

        # Extract parent message context
        parent_msg_id = dmsg.get("parent_header", {}).get("msg_id")
        cell_id = extract_src_id(parent_msg_id) if parent_msg_id else None
        parent_channel = extract_channel(parent_msg_id) if parent_msg_id else None

        # Dispatch to core handlers
        msg_type = dmsg.get("msg_type")
        match msg_type:
            case "kernel_info_reply":
                await self._handle_kernel_info_reply(dmsg)
            case "status":
                await self._handle_status_message(dmsg, parent_channel, cell_id)
            case "execute_input":
                await self._handle_execute_input(dmsg, cell_id)
            case "stream" | "display_data" | "execute_result" | "error" | "update_display_data" | "clear_output":
                await self._handle_output_message(dmsg, msg_type, cell_id)

        # Dispatch to registered plugin handlers
        if cell_id:
            for yroom in self._yrooms:
                notebook = yroom.jupyter_ydoc
                if notebook is None:
                    break
                handlers = yroom.parent._cell_data_handlers
                for handler_msg_types, handler in handlers:
                    if msg_type in handler_msg_types:
                        try:
                            content = self.session.unpack(dmsg["content"])
                            self.log.debug(
                                f"Dispatching {msg_type} for cell {cell_id} to {handler.__name__}"
                            )
                            await handler(notebook, cell_id, msg_type, content, dmsg["header"])
                        except Exception as e:
                            self.log.warning(f"Cell data handler error: {e}", exc_info=True)
                break

    async def _handle_kernel_info_reply(self, msg: dict):
        """Update notebook metadata with kernel language info."""
        try:
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
        except Exception as e:
            self.log.error(f"Error in _handle_kernel_info_reply: {e}", exc_info=True)

    async def _handle_status_message(
        self, dmsg: dict, parent_channel: str | None, cell_id: str | None
    ):
        """Update kernel and cell execution states from status messages."""
        try:
            content = self.session.unpack(dmsg["content"])
            execution_state = content.get("execution_state")

            for yroom in self._yrooms:
                # Update document-level kernel status if from shell channel
                if parent_channel == "shell":
                    yroom.set_kernel_execution_state(execution_state)

                # Update cell execution state
                if cell_id:
                    notebook = yroom.jupyter_ydoc
                    if notebook and hasattr(notebook, 'set_cell_awareness'):
                        notebook.set_cell_awareness(cell_id, "execution_state", {"state": execution_state})
                    break
        except Exception as e:
            self.log.error(f"Error in _handle_status_message: {e}", exc_info=True)

    async def _handle_execute_input(self, dmsg: dict, cell_id: str | None):
        """Update cell execution count when execution begins."""
        if not cell_id:
            return

        try:
            content = self.session.unpack(dmsg["content"])
            execution_count = content.get("execution_count")

            if execution_count is not None:
                for yroom in self._yrooms:
                    notebook = yroom.jupyter_ydoc
                    if notebook is None:
                        continue
                    _, target_cell = notebook.find_cell(cell_id)
                    if target_cell:
                        target_cell["execution_count"] = execution_count
                        break
        except Exception as e:
            self.log.error(f"Error in _handle_execute_input: {e}", exc_info=True)

    async def _handle_output_message(self, dmsg: dict, msg_type: str, cell_id: str | None):
        """Process output messages through output processor."""
        if not cell_id:
            return

        if not self.output_processor:
            # Output processing is optional - only log at debug level
            return

        try:
            content = self.session.unpack(dmsg["content"])
            self.output_processor.process_output(msg_type, cell_id, content)
        except Exception as e:
            # Output processing errors are non-fatal - kernel still works
            # Log at debug level to avoid noise in logs
            self.log.debug(f"Output processing skipped for cell {cell_id}: {e}")

    async def add_yroom(self, yroom: YRoom):
        """Register a YRoom to receive kernel messages."""
        self._yrooms.add(yroom)

    async def remove_yroom(self, yroom: YRoom):
        """Unregister a YRoom from receiving kernel messages."""
        self._yrooms.discard(yroom)
        # Cancel pending tasks when no yrooms remain
        if not self._yrooms:
            for task in self._pending_tasks:
                task.cancel()
            self._pending_tasks.clear()

    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        """Handle messages from WebSocket clients before routing to kernel.

        Extends base implementation to:
        - Set cell awareness to 'busy' immediately on execute_request
        - Clear outputs when cell is re-executed
        """
        # Only process if mixin was properly initialized
        if not hasattr(self, '_cell_msg_ids'):
            # Mixin not initialized, skip document-aware processing
            super().handle_incoming_message(channel_name, msg)
            return

        try:
            header = self.session.unpack(msg[0])
            msg_id = header["msg_id"]
            msg_type = header.get("msg_type")
            metadata = self.session.unpack(msg[2])
            cell_id = metadata.get("cellId")

            if cell_id:
                # Clear outputs if this is a re-execution
                last_msg_id = self._cell_msg_ids.get(cell_id)
                if last_msg_id and last_msg_id != msg_id and self.output_processor:
                    task = asyncio.create_task(self.output_processor.clear_cell_outputs(cell_id))
                    self._pending_tasks.add(task)
                    task.add_done_callback(self._pending_tasks.discard)

                # Track this message ID
                self._cell_msg_ids[cell_id] = msg_id

                # Set awareness state immediately for queued cells
                if msg_type == "execute_request" and channel_name == "shell":
                    for yroom in self._yrooms:
                        notebook = yroom.jupyter_ydoc
                        if notebook is None or not hasattr(notebook, 'set_cell_awareness'):
                            break
                        notebook.set_cell_awareness(cell_id, "execution_state", {"state": "busy"})
                        # Call registered sync hooks for execute_request
                        for hook in yroom.parent._execute_request_hooks:
                            try:
                                hook(notebook, cell_id)
                            except Exception as e:
                                self.log.debug(f"execute_request hook error: {e}")
                        break
        except Exception as e:
            self.log.debug(f"Error handling awareness for incoming message: {e}")

        # Call parent's handle_incoming_message
        super().handle_incoming_message(channel_name, msg)
