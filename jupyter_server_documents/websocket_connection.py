"""
Per-connection kernel WebSocket bridge.

Each browser WebSocket connection owns its own AsyncKernelClient. Four asyncio
tasks drive the receive loop via await socket.recv_multipart(). The client is
always disposed in disconnect() regardless of how the connection ends.
"""
import asyncio
import json
import typing as t

import traitlets
from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
    deserialize_msg_from_ws_v1,
    serialize_msg_to_ws_v1,
)


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
        state = await self._nudge_kernel()
        self.log.debug("Kernel nudge result: %s", state)

        self._tasks = [
            asyncio.create_task(self._listen(ch))
            for ch in ("shell", "control", "stdin", "iopub")
        ]

        if state in ("busy", "idle") and self._client is not None:
            self._send_synthetic_status(state)

    async def _nudge_kernel(self) -> str:
        """Determine kernel busy/idle state using a two-path approach.

        **Fast path — JEP #65 XPUB (ipykernel >= 7.2.0)**:
        Listens on iopub for ``iopub_welcome``, sent by kernels that implement
        the XPUB socket.  Receiving it confirms the IOPub subscription is live.

        **Dual-channel shell + control nudge**:
        Sends ``kernel_info_request`` on both channels simultaneously.
        Control bypasses the execution queue; shell is blocked while executing.

          control + shell reply  → "idle"
          control reply only     → "busy"
          no reply within timeout → "unknown"

        Logic:
        1. Race all three tasks with the overall ``kernel_info_timeout``.
        2. As soon as any task completes, re-evaluate:
           - If control replied: wait up to ``kernel_info_reply_window`` more
             seconds for shell to also reply (idle confirmation), then return.
           - If only welcome arrived: keep waiting for control/shell.
           - If nothing arrived within ``kernel_info_timeout``: return "unknown".

        This avoids the brittle hard-coded 200 ms cutoff: on a high-latency
        kernel without XPUB support, welcome times out but we continue waiting
        for control/shell up to the full ``kernel_info_timeout``.

        Must be called BEFORE starting the listen tasks.
        """
        session = self._client.session
        total_timeout = self.kernel_info_timeout
        shell_window = self.kernel_info_reply_window

        shell_socket = self._client.shell_channel.socket
        control_socket = self._client.control_channel.socket
        iopub_socket = self._client.iopub_channel.socket

        session.send(shell_socket, session.msg("kernel_info_request"))
        session.send(control_socket, session.msg("kernel_info_request"))

        async def recv_reply(socket) -> bool:
            try:
                msg_list = await socket.recv_multipart()
                _, fed = session.feed_identities(msg_list)
                if len(fed) < 2:
                    return False
                return json.loads(fed[1]).get("msg_type") == "kernel_info_reply"
            except Exception:
                return False

        async def recv_welcome() -> bool:
            """Receive iopub_welcome with a short inner timeout.

            The timeout is capped at shell_window so it doesn't delay the
            probe on kernels that don't support XPUB (ipykernel < 7.2.0).
            """
            try:
                msg_list = await asyncio.wait_for(
                    iopub_socket.recv_multipart(),
                    timeout=shell_window,
                )
                _, fed = session.feed_identities(msg_list)
                if len(fed) < 2:
                    return False
                return json.loads(fed[1]).get("msg_type") == "iopub_welcome"
            except (asyncio.TimeoutError, Exception):
                return False

        shell_task = asyncio.create_task(recv_reply(shell_socket))
        control_task = asyncio.create_task(recv_reply(control_socket))
        welcome_task = asyncio.create_task(recv_welcome())
        # Register so disconnect() can cancel them if the WebSocket closes
        # before the nudge finishes.
        self._nudge_tasks = {shell_task, control_task, welcome_task}

        deadline = asyncio.get_event_loop().time() + total_timeout
        active = {shell_task, control_task, welcome_task}

        while active:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            done, active = await asyncio.wait(
                active,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                break  # deadline reached

            if control_task.done():
                # Control replied — wait up to shell_window for shell to also
                # reply (idle confirmation), then we have enough information.
                if not shell_task.done():
                    shell_remaining = min(
                        shell_window,
                        deadline - asyncio.get_event_loop().time(),
                    )
                    if shell_remaining > 0:
                        await asyncio.wait(
                            [t for t in active if t is shell_task],
                            timeout=shell_remaining,
                        )
                break  # we have a result; exit regardless

            # Only welcome (or nothing useful) arrived so far — keep waiting.

        for t in active:
            t.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        self._nudge_tasks.clear()

        def result(task) -> bool:
            if task.done() and not task.cancelled():
                try:
                    return bool(task.result())
                except Exception:
                    return False
            return False

        if result(welcome_task):
            self.log.debug("Received iopub_welcome (XPUB kernel, protocol >= 5.4)")

        control_replied = result(control_task)
        shell_replied = result(shell_task)

        if control_replied and shell_replied:
            return "idle"
        elif control_replied:
            return "busy"
        else:
            return "unknown"

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
        # closed before _nudge_kernel() completed.
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
