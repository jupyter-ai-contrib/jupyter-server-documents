"""
Per-connection kernel WebSocket bridge.

Each browser WebSocket connection owns its own AsyncKernelClient. Four asyncio
tasks drive the receive loop via await socket.recv_multipart(). The client is
always disposed in disconnect() regardless of how the connection ends.
"""
import asyncio
import typing as t

import traitlets
from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
    deserialize_msg_from_ws_v1,
    serialize_msg_to_ws_v1,
)
from .nudge import nudge_kernel


class KernelWebsocketConnection(BaseKernelWebsocketConnection):
    """WebSocket bridge that owns its own AsyncKernelClient per connection."""

    kernel_ws_protocol = "v1.kernel.websocket.jupyter.org"

    kernel_info_timeout = traitlets.Float(
        5.0,
        config=True,
        help=(
            "Seconds to wait for kernel_info_request replies during the "
            "busy/idle nudge that runs on every new WebSocket connection. "
            "Increase for high-latency or slow-starting remote kernels. "
            "Only affects the 'unknown' / unreachable case; idle and busy "
            "kernels are detected much faster."
        ),
    )

    kernel_info_reply_window = traitlets.Float(
        0.2,
        config=True,
        help=(
            "After the control channel replies, how many additional seconds "
            "to wait for the shell channel before declaring the kernel 'busy'. "
            "An idle kernel replies on both channels nearly simultaneously "
            "(<50 ms locally); this window only needs to cover network jitter."
        ),
    )

    _client: t.Any = None
    _tasks: t.List[asyncio.Task] = []
    _nudge_tasks: t.Set[asyncio.Task] = set()

    async def connect(self) -> None:
        self._client = self.kernel_manager.client()
        self._client.load_connection_info(self.kernel_manager.get_connection_info())
        self._client.start_channels(hb=False)

        # Probe kernel state on shell + control channels BEFORE starting the
        # listen tasks so there is no race for messages.  The result is
        # delivered to the browser as a synthetic status iopub message so the
        # execution indicator immediately shows the correct state rather than
        # staying at "unknown" after a page refresh mid-execution.
        #
        # Also listens for iopub_welcome (JEP #65 / ipykernel >= 7.2.0).
        state = await nudge_kernel(
            self._client,
            kernel_info_timeout=self.kernel_info_timeout,
            kernel_info_reply_window=self.kernel_info_reply_window,
            pending_tasks=self._nudge_tasks,
        )
        self.log.debug("Kernel nudge result: %s", state)

        self._tasks = [
            asyncio.create_task(self._listen(ch))
            for ch in ("shell", "control", "stdin", "iopub")
        ]

        if state in ("busy", "idle") and self._client is not None:
            self._send_synthetic_status(state)

    def _send_synthetic_status(self, execution_state: str) -> None:
        """Send a synthetic status iopub message to the browser WebSocket."""
        try:
            msg = self._client.session.msg("status", {"execution_state": execution_state})
            msg_list = self._client.session.serialize(msg, self._client.session.bsession)
            _, fed = self._client.session.feed_identities(msg_list)
            parts = fed[1:]  # strip signature frame
            bin_msg = serialize_msg_to_ws_v1(parts, "iopub")
            self.websocket_handler.write_message(bin_msg, binary=True)
        except Exception as err:
            self.log.warning("Could not send synthetic status:%s: %s", execution_state, err)

    def disconnect(self) -> None:
        # Cancel nudge tasks first — they may still be running if the WebSocket
        # closed before nudge_kernel() completed.
        for task in self._nudge_tasks:
            task.cancel()
        self._nudge_tasks.clear()
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
