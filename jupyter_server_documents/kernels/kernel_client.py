"""
A new Kernel client that is aware of ydocuments.
"""
import anyio
import asyncio
import json
import typing as t

from traitlets import Set, Instance, Any, Type, default
from jupyter_client.asynchronous.client import AsyncKernelClient

from .message_cache import KernelMessageCache
from jupyter_server_documents.rooms.yroom import YRoom
from jupyter_server_documents.outputs import OutputProcessor
from jupyter_server.utils import ensure_async

from .kernel_client_abc import AbstractDocumentAwareKernelClient


class DocumentAwareKernelClient(AsyncKernelClient):
    """
    A kernel client that routes messages to registered ydocs.
    """
    # Having this message cache is not ideal.
    # Unfortunately, we don't include the parent channel
    # in the messages that generate IOPub status messages, thus,
    # we can't differential between the control channel vs.
    # shell channel status. This message cache gives us
    # the ability to map status message back to their source.
    message_cache = Instance(
        klass=KernelMessageCache
    )

    @default('message_cache')
    def _default_message_cache(self):
        return KernelMessageCache(parent=self)

    # A set of callables that are called when a kernel
    # message is received.
    _listeners = Set(allow_none=True)

    # A set of YRooms that will intercept output and kernel
    # status messages.
    _yrooms: t.Set[YRoom] = Set(trait=Instance(YRoom), default_value=set())


    output_processor = Instance(
        OutputProcessor,
        allow_none=True
    )

    output_process_class = Type(
        klass=OutputProcessor,
        default_value=OutputProcessor
    ).tag(config=True)

    @default("output_processor")
    def _default_output_processor(self) -> OutputProcessor:
        self.log.info("Creating output processor")
        return self.output_process_class(parent=self, config=self.config)

    async def start_listening(self):
        """Start listening to messages coming from the kernel.
        
        Use anyio to setup a task group for listening.
        """
        # Wrap a taskgroup so that it can be backgrounded.
        async def _listening():
            async with anyio.create_task_group() as tg:
                for channel_name in ["shell", "control", "stdin", "iopub"]:
                    tg.start_soon(
                        self._listen_for_messages, channel_name
                    )

        # Background this task.
        self._listening_task = asyncio.create_task(_listening())

    async def stop_listening(self):
        """Stop listening to the kernel.
        """
        # If the listening task isn't defined yet
        # do nothing.
        if not hasattr(self, '_listening_task') or not self._listening_task:
            return

        # Attempt to cancel the task.
        try:
            self._listening_task.cancel()
            # Await cancellation.
            await self._listening_task
        except asyncio.CancelledError:
            self.log.info("Disconnected from client from the kernel.")
        # Log any exceptions that were raised.
        except Exception as err:
            self.log.error(err)
        finally:
            # Clear the task reference
            self._listening_task = None

    _listening_task: t.Optional[t.Awaitable] = Any(allow_none=True)

    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        """
        Handle incoming kernel messages and set up immediate cell execution state tracking.
        
        This method processes incoming kernel messages and caches them for response mapping.
        Importantly, it detects execute_request messages and immediately sets the corresponding
        cell state to 'busy' to provide real-time feedback for queued cell executions.
        
        This ensures that when multiple cells are executed simultaneously, all queued cells
        show a '*' prompt immediately, not just the currently executing cell.
        
        Args:
            channel_name: The kernel channel name (shell, iopub, etc.)
            msg: The raw kernel message as bytes
        """
        # Cache the message ID and its socket name so that
        # any response message can be mapped back to the
        # source channel.
        header = self.session.unpack(msg[0])
        msg_id = header["msg_id"]
        msg_type = header.get("msg_type")                
        metadata = self.session.unpack(msg[2])
        cell_id = metadata.get("cellId")
        
        # Clear cell outputs if cell is re-executed
        if cell_id:
            existing = self.message_cache.get(cell_id=cell_id)
            if existing and existing['msg_id'] != msg_id:
                asyncio.create_task(self.output_processor.clear_cell_outputs(cell_id))
        
        # IMPORTANT: Set cell to 'busy' immediately when execute_request is received
        # This ensures queued cells show '*' prompt even before kernel starts processing them
        if msg_type == "execute_request" and channel_name == "shell" and cell_id:
            for yroom in self._yrooms:
                yroom.set_cell_awareness_state(cell_id, "busy")
        
        self.message_cache.add({
            "msg_id": msg_id,
            "channel": channel_name,
            "cell_id": cell_id
        })
        channel = getattr(self, f"{channel_name}_channel")
        channel.session.send_raw(channel.socket, msg)

    def send_kernel_info(self):
        """Sends a kernel info message on the shell channel. Useful 
        for determining if the kernel is busy or idle.
        """
        msg = self.session.msg("kernel_info_request")
        # Send message, skipping the delimiter and signature
        msg = self.session.serialize(msg)[2:]
        self.handle_incoming_message("shell", msg)

    def add_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        """Add a listener to the ZMQ Interface.

        A listener is a callable function/method that takes
        the deserialized (minus the content) ZMQ message.

        If the listener is already registered, it won't be registered again.
        """
        self._listeners.add(callback)

    def remove_listener(self, callback: t.Callable[[str, list[bytes]], None]):
        """Remove a listener. If the listener
        is not found, this method does nothing.
        """
        self._listeners.discard(callback)

    async def _listen_for_messages(self, channel_name: str):
        """The basic polling loop for listened to kernel messages
        on a ZMQ socket.
        """
        # Wire up the ZMQ sockets
        # Setup up ZMQSocket broadcasting.
        channel = getattr(self, f"{channel_name}_channel")
        while True:
            # Wait for a message
            await channel.socket.poll(timeout=float("inf"))
            raw_msg = await channel.socket.recv_multipart()
            # Drop identities and delimit from the message parts.
            _, fed_msg_list = self.session.feed_identities(raw_msg)
            msg = fed_msg_list
            try:
                await self.handle_outgoing_message(channel_name, msg)
            except Exception as err:
                self.log.error(err)

    async def send_message_to_listeners(self, channel_name: str, msg: list[bytes]):
        """
        Sends message to all registered listeners.
        """
        async with anyio.create_task_group() as tg:
            # Broadcast the message to all listeners.
            for listener in self._listeners:
                async def _wrap_listener(listener_to_wrap, channel_name, msg):
                    """
                    Wrap the listener to ensure its async and 
                    logs (instead of raises) exceptions.
                    """
                    try:
                        await ensure_async(listener_to_wrap(channel_name, msg))
                    except Exception as err:
                        self.log.error(err)

                tg.start_soon(_wrap_listener, listener, channel_name, msg)    

    async def handle_outgoing_message(self, channel_name: str, msg: list[bytes]):
        """This is the main method that consumes every
        message coming back from the kernel. It parses the header
        (not the content, which might be large) and updates
        the last_activity, execution_state, and lifecycsle_state
        when appropriate. Then, it routes the message
        to all listeners.
        """
        if channel_name in ('iopub', 'shell'):
            msg = await self.handle_document_related_message(msg)
            # If msg has been cleared by the handler, escape this method.
            if msg is None:
                return
        
        await self.send_message_to_listeners(channel_name, msg)

    async def handle_document_related_message(self, msg: t.List[bytes]) -> t.Optional[t.List[bytes]]:
        """
        Processes document-related messages received from a Jupyter kernel.
        
        Messages are deserialized and handled based on their type. Supported message types
        include updating language info, kernel status, execution state, execution count,
        and various output types. Some messages may be processed by an output processor
        before deciding whether to forward them.

        Returns the original message if it is not processed further, otherwise None to indicate
        that the message should not be forwarded.
        """
        # Begin to deserialize the message safely within a try-except block
        try:
            dmsg = self.session.deserialize(msg, content=False)
        except Exception as e:
            self.log.error(f"Error deserializing message: {e}")
            raise
        
        parent_msg_id = dmsg["parent_header"]["msg_id"]
        parent_msg_data = self.message_cache.get(parent_msg_id)
        cell_id = parent_msg_data.get('cell_id')

        # Handle different message types using pattern matching
        match dmsg["msg_type"]:
            case "kernel_info_reply":
                # Unpack the content to extract language info
                content = self.session.unpack(dmsg["content"])
                language_info = content["language_info"]
                # Update the language info metadata for each collaborative room
                for yroom in self._yrooms:
                    notebook = await yroom.get_jupyter_ydoc()
                    # The metadata ydoc is not exposed as a
                    # public property.
                    metadata = notebook.ymeta
                    metadata["metadata"]["language_info"] = language_info

            case "status":
                # Handle kernel status messages and update cell execution states
                # This provides real-time feedback about cell execution progress
                content = self.session.unpack(dmsg["content"])
                execution_state = content.get("execution_state")
                
                # Update status across all collaborative rooms
                for yroom in self._yrooms:
                    awareness = yroom.get_awareness()
                    if awareness is not None:
                        # If this status came from the shell channel, update
                        # the notebook kernel status.
                        if parent_msg_data and parent_msg_data.get("channel") == "shell":                     
                            # Update the kernel execution state at the top document level
                            awareness.set_local_state_field("kernel", {"execution_state": execution_state})
                        
                        # Store cell execution state for persistence across client connections
                        # This ensures that cell execution states survive page refreshes
                        if cell_id:
                            for yroom in self._yrooms:
                                yroom.set_cell_execution_state(cell_id, execution_state)
                                yroom.set_cell_awareness_state(cell_id, execution_state)
                            break

            case "execute_input":
                if cell_id:
                    # Extract execution count and update each collaborative room's notebook
                    content = self.session.unpack(dmsg["content"])
                    execution_count = content["execution_count"]
                    for yroom in self._yrooms:
                        notebook = await yroom.get_jupyter_ydoc()
                        _, target_cell = notebook.find_cell(cell_id)
                        if target_cell:
                            target_cell["execution_count"] = execution_count
                            break

            case "stream" | "display_data" | "execute_result" | "error" | "update_display_data" | "clear_output":
                if cell_id: 
                    # Process specific output messages through an optional processor
                    if self.output_processor:
                        content = self.session.unpack(dmsg["content"])
                        self.output_processor.process_output(dmsg['msg_type'], cell_id, content)
                        
                        # Suppress forwarding of processed messages by returning None
                        return None

        # Default return if message is processed and does not need forwarding
        return msg

    async def add_yroom(self, yroom: YRoom):
        """
        Register a YRoom with this kernel client. YRooms will
        intercept display and kernel status messages.
        """
        self._yrooms.add(yroom)

    async def remove_yroom(self, yroom: YRoom):
        """
        De-register a YRoom from handling kernel client messages.
        """
        self._yrooms.discard(yroom)


AbstractDocumentAwareKernelClient.register(DocumentAwareKernelClient)
