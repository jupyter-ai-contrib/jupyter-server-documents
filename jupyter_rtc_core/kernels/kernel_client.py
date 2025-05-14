"""
A new Kernel client that is aware of ydocuments.
"""
import asyncio
import json
import typing as t
from traitlets import Set
from traitlets import Instance
from traitlets import Any
from .utils import LRUCache
from jupyter_client.asynchronous.client import AsyncKernelClient
import anyio
from jupyter_rtc_core.rooms.yroom import YRoom


class DocumentAwareKernelClient(AsyncKernelClient): 
    """
    A kernel client 
    """
    # Having this message cache is not ideal.
    # Unfortunately, we don't include the parent channel
    # in the messages that generate IOPub status messages, thus,
    # we can't differential between the control channel vs.
    # shell channel status. This message cache gives us
    # the ability to map status message back to their source.
    message_source_cache = Instance(
        default_value=LRUCache(maxsize=1000), klass=LRUCache
    )

    # A set of callables that are called when a kernel
    # message is received.
    _listeners = Set(allow_none=True)

    # A set of YRooms that will intercept output and kernel
    # status messages.
    _yrooms: t.Set[YRoom] = Set(trait=Instance(YRoom), default_value=set())

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
        if not self._listening_task:
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

    _listening_task: t.Optional[t.Awaitable] = Any(allow_none=True)

    def handle_incoming_message(self, channel_name: str, msg: list[bytes]):
        """Use the given session to send the message."""
        # Cache the message ID and its socket name so that
        # any response message can be mapped back to the
        # source channel.
        header = header = json.loads(msg[0])
        msg_id = header["msg_id"]
        self.message_source_cache[msg_id] = channel_name
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
                        listener_to_wrap(channel_name, msg)
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

        # Intercept messages that are IOPub focused.
        if channel_name == "iopub":
            message_returned = await self.handle_iopub_message(msg)
            # TODO: If the message is not returned by the iopub handler, then
            # return here and do not forward to listeners.
            if not message_returned:
                self.log.warn(f"If message is handled donot forward after adding output manager")
                return

        # Update the last activity.
        # self.last_activity = self.session.msg_time

        await self.send_message_to_listeners(channel_name, msg)

    async def handle_iopub_message(self, msg: list[bytes]) -> t.Optional[list[bytes]]:
        """
        Handle messages
        
        Parameters
        ----------
        dmsg: dict
            Deserialized message (except concept)
            
        Returns
        ------- 
        Returns the message if it should be forwarded to listeners. Otherwise,
        returns `None` and keeps (i.e. intercepts) the message from going
        to listeners.
        """
        # NOTE: Here's where we will inject the kernel state
        # into the awareness of a document.

        try:
            dmsg = self.session.deserialize(msg, content=False)
        except Exception as e:
            self.log.error(f"Error deserializing message: {e}")
            raise

        # NOTE: Inject display data into ydoc.
        if dmsg["msg_type"] == "display_data":
            # Forward to all yrooms.
            for yroom in self._yrooms:
                update_document_message = b""
                # yroom.add_message(update_document_message)

        # TODO: returning message temporarily to not break UI
        # If the message isn't handled above, return it and it will
        # be forwarded to all listeners
        return msg

    def send_kernel_awareness(self, kernel_status: dict):
        """
        Send kernel status awareness messages to all yrooms
        """
        for yroom in self._yrooms:
            awareness = yroom.get_awareness()
            if awareness is None:
                self.log.error(f"awareness cannot be None. room_id: {yroom.room_id}")
                continue
            self.log.debug(f"current state: {awareness.get_local_state()} room_id: {yroom.room_id}. kernel status: {kernel_status}")
            awareness.set_local_state_field("kernel", kernel_status)    
            self.log.debug(f"current state: {awareness.get_local_state()} room_id: {yroom.room_id}")


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
