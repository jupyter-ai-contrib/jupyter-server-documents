"""
Per-connection kernel WebSocket bridge.

Each browser WebSocket connection owns its own AsyncKernelClient. Four asyncio
tasks drive the receive loop via await socket.recv_multipart(). The client is
always disposed in disconnect() regardless of how the connection ends.
"""
import asyncio
import typing as t

from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
    deserialize_msg_from_ws_v1,
    serialize_msg_to_ws_v1,
)


class KernelWebsocketConnection(BaseKernelWebsocketConnection):
    """WebSocket bridge that owns its own AsyncKernelClient per connection."""

    kernel_ws_protocol = "v1.kernel.websocket.jupyter.org"

    _client: t.Any = None
    _tasks: t.List[asyncio.Task] = []

    async def connect(self) -> None:
        self._client = self.kernel_manager.client()
        self._client.load_connection_info(self.kernel_manager.get_connection_info())
        self._client.start_channels(hb=False)
        self._tasks = [
            asyncio.create_task(self._listen(ch))
            for ch in ("shell", "control", "stdin", "iopub")
        ]

    def disconnect(self) -> None:
        # Cancel background recv tasks. They handle CancelledError gracefully.
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        if self._client is not None:
            self._client.stop_channels()
            self._client = None

    def handle_incoming_message(self, incoming_msg: bytes) -> None:
        """Forward a WebSocket message to the appropriate ZMQ channel."""
        if self._client is None:
            self.log.warning("Received message on closed WebSocket connection")
            return
        channel_name, msg_list = deserialize_msg_from_ws_v1(incoming_msg)
        channel = getattr(self._client, f"{channel_name}_channel")
        self._client.session.send_raw(channel.socket, msg_list)

    async def _listen(self, channel_name: str) -> None:
        """Read from one ZMQ channel and forward all messages to the WebSocket."""
        channel = getattr(self._client, f"{channel_name}_channel")
        socket = channel.socket
        try:
            while True:
                msg_list = await socket.recv_multipart()
                _, fed = self._client.session.feed_identities(msg_list)
                parts = fed[1:]  # strip signature frame
                try:
                    bin_msg = serialize_msg_to_ws_v1(parts, channel_name)
                    self.websocket_handler.write_message(bin_msg, binary=True)
                except WebSocketClosedError:
                    return
                except Exception as err:
                    self.log.error("Error forwarding kernel message: %s", err)
        except asyncio.CancelledError:
            pass
