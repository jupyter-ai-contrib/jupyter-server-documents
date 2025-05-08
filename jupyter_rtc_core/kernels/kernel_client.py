import asyncio
import json
import typing as t
from traitlets import Set
from traitlets import Instance
from traitlets import Any
from .utils import LRUCache
from jupyter_client.asynchronous.client import AsyncKernelClient
import anyio

from jupyter_client.session import Session

class NextGenAsyncKernelClient(AsyncKernelClient): 
    """
    A ZMQ-based kernel client class that managers all listeners to a kernel.
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

    # A set of callables that are called when a
    # ZMQ message comes back from the kernel.
    _listeners = Set(allow_none=True)

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
        # If the listening task isn't defined yet
        # do nothing.
        if not self._listening_task:
            return
        
        # Attempt to cancel the task.
        self._listening_task.cancel()
        try:
            # Await cancellation.
            await self._listening_task
        except asyncio.CancelledError:
            self.log.info("Disconnected from client from the kernel.")
        # Log any exceptions that were raised.
        except Exception as err:
            self.log.error(err)
                        
    _listening_task: t.Optional[t.Awaitable] = Any(allow_none=True)

    def send_message(self, channel_name, msg):
        """Use the given session to send the message."""
        # Cache the message ID and its socket name so that
        # any response message can be mapped back to the
        # source channel.
        header = header = json.loads(msg[0])
        msg_id = header["msg_id"]
        self.message_source_cache[msg_id] = channel_name
        channel = getattr(self, f"{channel_name}_channel")
        channel.session.send_raw(channel.socket, msg)
    
    async def recv_message(self, channel_name, msg):
        """This is the main method that consumes every
        message coming back from the kernel. It parses the header
        (not the content, which might be large) and updates
        the last_activity, execution_state, and lifecycle_state
        when appropriate. Then, it routes the message
        to all listeners.
        """
        # Broadcast messages
        async with anyio.create_task_group() as tg:
            # Broadcast the message to all listeners.
            for listener in self._listeners:
                async def _wrap_listener(listener, channel_name, msg): 
                    """
                    Wrap the listener to ensure its async and 
                    logs (instead of raises) exceptions.
                    """
                    try:
                        listener(channel_name, msg)
                    except Exception as err:
                        self.log.error(err)
                
                tg.start_soon(_wrap_listener, listener, channel_name, msg)

    def add_listener(self, callback: t.Callable[[dict], None]):
        """Add a listener to the ZMQ Interface.

        A listener is a callable function/method that takes
        the deserialized (minus the content) ZMQ message.

        If the listener is already registered, it won't be registered again.
        """
        self._listeners.add(callback)

    def remove_listener(self, callback: t.Callable[[dict], None]):
        """Remove a listener to teh ZMQ interface. If the listener
        is not found, this method does nothing.
        """
        self._listeners.discard(callback)

    async def _listen_for_messages(self, channel_name):
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
            try:
                await self.recv_message(channel_name, raw_msg)
            except Exception as err:
                self.log.error(err)
    
    def kernel_info(self):
        msg = self.session.msg("kernel_info_request")
        # Send message, skipping the delimiter and signature
        msg = self.session.serialize(msg)[2:]
        self.send_message("shell", msg)