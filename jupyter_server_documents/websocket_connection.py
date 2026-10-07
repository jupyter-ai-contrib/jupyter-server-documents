"""
Per-connection kernel WebSocket bridge.

Each browser WebSocket connection owns its own AsyncKernelClient. Four asyncio
tasks drive the receive loop via await socket.recv_multipart(). The client is
always disposed in disconnect() regardless of how the connection ends.

Before the receive tasks start, connect() "nudges" the kernel the way
jupyter_server's ZMQChannelsWebsocketConnection does: it repeats
kernel_info_request on transient shell and control sockets until a reply and
at least one IOPub message have arrived. A freshly connected ZMQ SUB socket
silently drops everything the kernel publishes before its subscription reaches
the kernel (the "slow joiner" race), so without this step a client's first
requests can lose their IOPub replies with no error anywhere.
"""
import asyncio
import typing as t

import zmq
from zmq.asyncio import Poller
from tornado.websocket import WebSocketClosedError
from traitlets import Float
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
    deserialize_msg_from_ws_v1,
    serialize_msg_to_ws_v1,
)


class KernelWebsocketConnection(BaseKernelWebsocketConnection):
    """WebSocket bridge that owns its own AsyncKernelClient per connection."""

    kernel_ws_protocol = "v1.kernel.websocket.jupyter.org"

    nudge_timeout = Float(
        10.0,
        config=True,
        help=(
            "Seconds to wait for a kernel_info reply and one IOPub message "
            "proving a new connection's ZMQ subscriptions before forwarding "
            "traffic anyway. Set to 0 to skip the nudge."
        ),
    )

    nudge_resend_interval = Float(
        0.5,
        config=True,
        help="Seconds between repeated kernel_info_request nudges.",
    )

    _client: t.Any = None
    _tasks: t.List[asyncio.Task] = []

    async def connect(self) -> None:
        self._client = self.kernel_manager.client()
        self._client.load_connection_info(self.kernel_manager.get_connection_info())
        self._client.start_channels(hb=False)
        # Prove the bridge end-to-end before any traffic is forwarded. The
        # nudge bounds itself and never raises; on timeout or error the
        # connection proceeds unproven, as it did before the nudge existed.
        await self.nudge()
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

    async def nudge(self) -> str:
        """Nudge the kernel until this connection's ZMQ sockets are proven.

        Mirrors ``ZMQChannelsWebsocketConnection.nudge()`` in jupyter_server:
        ``kernel_info_request`` is re-sent every ``nudge_resend_interval``
        seconds on transient shell and control sockets (so their replies never
        leak to the frontend) until a shell or control reply *and* at least
        one IOPub message have arrived. The IOPub message is forwarded to the
        WebSocket exactly as the listen task would forward it, so no real
        broadcast is consumed.

        Returns the outcome for logging and tests: ``"ready"`` (the bridge is
        proven), ``"busy-skipped"``, ``"disabled"``, ``"timeout"``, or
        ``"error"``. The connection is usable after every outcome; only
        ``"ready"`` proves it. Never raises.
        """
        if self.nudge_timeout <= 0:
            return "disabled"
        # Do not nudge busy kernels: kernel_info_requests sent to shell queue
        # behind execution requests, and a busy kernel has long since
        # established its subscriptions.
        if getattr(self.kernel_manager, "execution_state", None) == "busy":
            self.log.debug("Nudge: not nudging busy kernel %s", self.kernel_id)
            return "busy-skipped"
        client = self._client
        shell_socket = None
        control_socket = None
        try:
            shell_socket = client.connect_shell()
            control_socket = client.connect_control()
            iopub_socket = client.iopub_channel.socket
            poller = Poller()
            poller.register(shell_socket, zmq.POLLIN)
            poller.register(control_socket, zmq.POLLIN)
            poller.register(iopub_socket, zmq.POLLIN)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.nudge_timeout
            reply_seen = False
            iopub_seen = False
            attempt = 0
            while not (reply_seen and iopub_seen):
                now = loop.time()
                if now >= deadline:
                    self.log.warning(
                        "Nudge: timed out after %.1fs on kernel %s "
                        "(shell/control reply: %s, iopub message: %s); "
                        "continuing without proof of the connection",
                        self.nudge_timeout,
                        self.kernel_id,
                        reply_seen,
                        iopub_seen,
                    )
                    return "timeout"
                attempt += 1
                self.log.debug("Nudge: attempt %d on kernel %s", attempt, self.kernel_id)
                # Re-send every round: each request also triggers the IOPub
                # status broadcast that proves the subscription.
                client.session.send(shell_socket, "kernel_info_request")
                client.session.send(control_socket, "kernel_info_request")
                round_deadline = min(now + self.nudge_resend_interval, deadline)
                while not (reply_seen and iopub_seen):
                    wait_seconds = round_deadline - loop.time()
                    if wait_seconds <= 0:
                        break
                    events = dict(await poller.poll(max(1, int(wait_seconds * 1000))))
                    if events.get(shell_socket, 0) & zmq.POLLIN:
                        await shell_socket.recv_multipart()
                        reply_seen = True
                    if events.get(control_socket, 0) & zmq.POLLIN:
                        await control_socket.recv_multipart()
                        reply_seen = True
                    if events.get(iopub_socket, 0) & zmq.POLLIN:
                        self._forward_message("iopub", await iopub_socket.recv_multipart())
                        iopub_seen = True
            self.log.debug("Nudge: kernel %s ready after %d attempt(s)", self.kernel_id, attempt)
            return "ready"
        except Exception:
            self.log.exception(
                "Nudge: failed on kernel %s; continuing without it", self.kernel_id
            )
            return "error"
        finally:
            for transient_socket in (shell_socket, control_socket):
                if transient_socket is not None:
                    transient_socket.close(linger=0)

    def _forward_message(self, channel_name: str, msg_list: t.List[bytes]) -> bool:
        """Serialize one raw ZMQ message and write it to the WebSocket.

        Returns False once the WebSocket is closed; any other forwarding error
        is logged and the message dropped.
        """
        _, fed = self._client.session.feed_identities(msg_list)
        parts = fed[1:]  # strip signature frame
        try:
            bin_msg = serialize_msg_to_ws_v1(parts, channel_name)
            self.websocket_handler.write_message(bin_msg, binary=True)
        except WebSocketClosedError:
            return False
        except Exception as err:
            self.log.error("Error forwarding kernel message: %s", err)
        return True

    async def _listen(self, channel_name: str) -> None:
        """Read from one ZMQ channel and forward all messages to the WebSocket."""
        channel = getattr(self._client, f"{channel_name}_channel")
        socket = channel.socket
        try:
            while True:
                msg_list = await socket.recv_multipart()
                if not self._forward_message(channel_name, msg_list):
                    return
        except asyncio.CancelledError:
            pass
