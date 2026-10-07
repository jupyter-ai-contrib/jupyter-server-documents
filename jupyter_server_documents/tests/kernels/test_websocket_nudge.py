"""
Tests for KernelWebsocketConnection.nudge().

A freshly connected ZMQ SUB socket silently drops everything published before
its subscription reaches the kernel (the "slow joiner" race), so a new
connection's first requests can lose their IOPub replies with no error.
jupyter_server's ZMQChannelsWebsocketConnection.nudge() guards against this by
repeating kernel_info_request until a shell/control reply and one IOPub
message arrive; this bridge must do the same before its listeners start.

Critical invariants:
- The nudge is ready only after a shell-or-control reply AND an IOPub message.
- kernel_info_request is re-sent on every round until then.
- Requests go out on transient shell/control sockets that are closed with
  linger=0 afterwards, so their replies never reach the frontend.
- The proving IOPub message is forwarded to the WebSocket, never consumed.
- A busy kernel is not nudged.
- Timeouts and errors are logged and never raise into connect().
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import zmq
from jupyter_client.manager import AsyncKernelManager
from jupyter_server.services.kernels.connection.base import (
    deserialize_msg_from_ws_v1,
    serialize_msg_to_ws_v1,
)
from tornado.websocket import WebSocketClosedError

from jupyter_server_documents.websocket_connection import (
    KernelWebsocketConnection,
)

IOPUB_FRAMES = [b"<id>", b"<sig>", b"<header>", b"<parent>", b"<meta>", b"<content>"]
REPLY_FRAMES = [b"<sig>", b"<reply-header>", b"<parent>", b"<meta>", b"<content>"]


class FakeSocket:
    """A ZMQ-socket stand-in with a message queue and close bookkeeping."""

    def __init__(self, name):
        self.name = name
        self.queue = []
        self.close_linger = None

    async def recv_multipart(self):
        return self.queue.pop(0)

    def close(self, linger=None):
        self.close_linger = linger

    @property
    def closed(self):
        return self.close_linger is not None


class FakePoller:
    """Reports POLLIN for every registered FakeSocket with a queued message."""

    def __init__(self):
        self.sockets = []

    def register(self, socket, flags):
        self.sockets.append(socket)

    async def poll(self, timeout_ms):
        await asyncio.sleep(0)
        ready = [(s, zmq.POLLIN) for s in self.sockets if s.queue]
        if not ready:
            await asyncio.sleep(timeout_ms / 1000)
        return ready


class FakeKernel:
    """Scripts what the kernel does on each transient kernel_info_request.

    ``reply_on`` names which transient sockets answer ("shell", "control").
    ``iopub_after`` is the request count from which the IOPub subscription
    "has reached the kernel" and its status broadcast is delivered.
    """

    def __init__(self, reply_on=("shell", "control"), iopub_after=1):
        self.reply_on = reply_on
        self.iopub_after = iopub_after
        self.requests = []
        self.iopub_socket = FakeSocket("iopub")

    def on_send(self, socket, msg_type):
        assert msg_type == "kernel_info_request"
        self.requests.append(socket.name)
        if socket.name in self.reply_on:
            socket.queue.append(list(REPLY_FRAMES))
        if socket.name == "shell" and self.requests.count("shell") >= self.iopub_after:
            self.iopub_socket.queue.append(list(IOPUB_FRAMES))


def make_nudge_conn(kernel, execution_state=None, **traits):
    """Return (conn, client, ws_handler_patch) wired to a FakeKernel."""
    conn = KernelWebsocketConnection.__new__(KernelWebsocketConnection)
    conn._tasks = []
    conn.log = MagicMock()
    for name, value in traits.items():
        setattr(conn, name, value)

    client = MagicMock()
    client.connect_shell.side_effect = lambda: FakeSocket("shell")
    client.connect_control.side_effect = lambda: FakeSocket("control")
    client.iopub_channel.socket = kernel.iopub_socket
    client.session.send.side_effect = kernel.on_send
    client.session.feed_identities.side_effect = lambda frames: ([], frames[1:])
    conn._client = client

    km = MagicMock()
    km.kernel_id = "kernel-id"
    km.execution_state = execution_state
    return conn, client, km


async def run_nudge(conn, km, ws_handler=None):
    ws_handler = ws_handler or MagicMock()
    with patch.object(
        KernelWebsocketConnection, "kernel_manager",
        new_callable=PropertyMock, return_value=km,
    ), patch.object(
        KernelWebsocketConnection, "websocket_handler",
        new_callable=PropertyMock, return_value=ws_handler,
    ), patch(
        "jupyter_server_documents.websocket_connection.Poller", FakePoller
    ), patch(
        "jupyter_server_documents.websocket_connection.serialize_msg_to_ws_v1",
        side_effect=lambda parts, channel: (channel, parts),
    ):
        outcome = await conn.nudge()
    return outcome, ws_handler


FAST = dict(nudge_timeout=0.5, nudge_resend_interval=0.02)


# ── ready ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nudge_ready_after_reply_and_iopub_message():
    """One kernel_info reply plus one IOPub message proves the connection."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)

    outcome, ws_handler = await run_nudge(conn, km)

    assert outcome == "ready"
    assert kernel.requests == ["shell", "control"]
    # Only the IOPub message reaches the frontend; the replies are consumed.
    ws_handler.write_message.assert_called_once_with(
        ("iopub", IOPUB_FRAMES[2:]), binary=True
    )


@pytest.mark.asyncio
async def test_nudge_forwards_iopub_message_like_listen_task():
    """The proving IOPub message must go through the listen task's exact path.

    feed_identities strips the identity, the signature frame is dropped, the
    remainder is serialized for the iopub channel and written as binary.
    """
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)

    _, ws_handler = await run_nudge(conn, km)

    client.session.feed_identities.assert_called_once_with(IOPUB_FRAMES)
    ws_handler.write_message.assert_called_once_with(
        ("iopub", [b"<header>", b"<parent>", b"<meta>", b"<content>"]), binary=True
    )
    assert kernel.iopub_socket.queue == []  # consumed from ZMQ, not left behind


@pytest.mark.asyncio
async def test_nudge_resends_until_iopub_subscription_is_established():
    """A slow-joining IOPub subscription is retried, not given up on.

    The kernel answers shell immediately each time but its IOPub broadcast
    only reaches this SUB socket from the third request on.  The nudge must
    keep re-sending kernel_info_request and become ready once the IOPub
    message arrives, forwarding exactly one IOPub message.
    """
    kernel = FakeKernel(iopub_after=3)
    conn, client, km = make_nudge_conn(kernel, **FAST)

    outcome, ws_handler = await run_nudge(conn, km)

    assert outcome == "ready"
    assert kernel.requests.count("shell") == 3
    assert kernel.requests.count("control") == 3
    assert ws_handler.write_message.call_count == 1


@pytest.mark.asyncio
async def test_nudge_accepts_control_reply_when_shell_is_silent():
    """Upstream resolves on a shell *or* control reply; so must this nudge."""
    kernel = FakeKernel(reply_on=("control",))
    conn, client, km = make_nudge_conn(kernel, **FAST)

    outcome, _ = await run_nudge(conn, km)

    assert outcome == "ready"


@pytest.mark.asyncio
async def test_nudge_not_ready_on_reply_alone():
    """A shell reply without any IOPub message does not prove the subscription."""
    kernel = FakeKernel(iopub_after=10_000)
    conn, client, km = make_nudge_conn(kernel, nudge_timeout=0.1, nudge_resend_interval=0.02)

    outcome, ws_handler = await run_nudge(conn, km)

    assert outcome == "timeout"
    assert kernel.requests.count("shell") > 1
    ws_handler.write_message.assert_not_called()


# ── transient sockets ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nudge_closes_transient_sockets_and_keeps_iopub_open():
    """Transient shell/control sockets are closed with linger=0 on success."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)

    await run_nudge(conn, km)

    shell_socket = client.session.send.call_args_list[0][0][0]
    control_socket = client.session.send.call_args_list[1][0][0]
    assert (shell_socket.name, control_socket.name) == ("shell", "control")
    assert shell_socket.close_linger == 0
    assert control_socket.close_linger == 0
    assert not kernel.iopub_socket.closed


@pytest.mark.asyncio
async def test_nudge_closes_transient_sockets_on_timeout():
    """Transient sockets are released even when the kernel never answers."""
    kernel = FakeKernel(reply_on=(), iopub_after=10_000)
    conn, client, km = make_nudge_conn(kernel, nudge_timeout=0.1, nudge_resend_interval=0.02)

    outcome, _ = await run_nudge(conn, km)

    assert outcome == "timeout"
    for call in client.session.send.call_args_list:
        assert call[0][0].close_linger == 0


# ── skips and failures ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_nudge_skips_busy_kernel():
    """A busy kernel queues kernel_info behind the running execution.

    Upstream skips it (its subscriptions are long established); nudging would
    block the connection for the length of the execution.
    """
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, execution_state="busy", **FAST)

    outcome, ws_handler = await run_nudge(conn, km)

    assert outcome == "busy-skipped"
    client.connect_shell.assert_not_called()
    client.connect_control.assert_not_called()
    client.session.send.assert_not_called()
    ws_handler.write_message.assert_not_called()


@pytest.mark.asyncio
async def test_nudge_disabled_by_zero_timeout():
    """nudge_timeout=0 opts out entirely without touching the kernel."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, nudge_timeout=0)

    outcome, _ = await run_nudge(conn, km)

    assert outcome == "disabled"
    client.connect_shell.assert_not_called()


@pytest.mark.asyncio
async def test_nudge_times_out_without_raising_and_warns():
    """A silent kernel bounds the wait; connect() must still proceed."""
    kernel = FakeKernel(reply_on=(), iopub_after=10_000)
    conn, client, km = make_nudge_conn(kernel, nudge_timeout=0.1, nudge_resend_interval=0.02)

    outcome, ws_handler = await run_nudge(conn, km)

    assert outcome == "timeout"
    conn.log.warning.assert_called_once()
    assert "timed out" in conn.log.warning.call_args[0][0]
    assert kernel.requests.count("shell") >= 2  # kept re-sending until the deadline
    ws_handler.write_message.assert_not_called()


@pytest.mark.asyncio
async def test_nudge_error_is_logged_and_does_not_raise():
    """Any exception inside the nudge is logged and swallowed."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)
    client.session.send.side_effect = RuntimeError("boom")

    outcome, _ = await run_nudge(conn, km)

    assert outcome == "error"
    conn.log.exception.assert_called_once()
    # Sockets created before the failure are still released.
    assert client.connect_shell.call_count == 1
    assert client.connect_control.call_count == 1


@pytest.mark.asyncio
async def test_nudge_error_creating_sockets_does_not_raise():
    """Failing to even open the transient sockets is also non-fatal."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)
    client.connect_shell.side_effect = zmq.ZMQError()

    outcome, _ = await run_nudge(conn, km)

    assert outcome == "error"
    conn.log.exception.assert_called_once()


@pytest.mark.asyncio
async def test_nudge_tolerates_closed_websocket():
    """A client that vanished mid-nudge must not turn into an error."""
    kernel = FakeKernel()
    conn, client, km = make_nudge_conn(kernel, **FAST)
    ws_handler = MagicMock()
    ws_handler.write_message.side_effect = WebSocketClosedError()

    outcome, _ = await run_nudge(conn, km, ws_handler)

    assert outcome == "ready"
    conn.log.exception.assert_not_called()


# ── connect() integration ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_awaits_nudge_after_channels_start_and_before_listeners():
    """connect() must nudge between start_channels() and the listener tasks.

    Listeners started earlier would race the nudge for the IOPub socket;
    started later, traffic forwarded before the nudge could be lost.
    """
    mock_km = MagicMock()
    mock_client = MagicMock()
    for ch in ("shell", "control", "stdin", "iopub"):
        getattr(mock_client, f"{ch}_channel").socket.recv_multipart = AsyncMock(
            side_effect=asyncio.CancelledError
        )
    mock_km.client.return_value = mock_client
    mock_km.get_connection_info.return_value = {}

    conn = KernelWebsocketConnection.__new__(KernelWebsocketConnection)
    conn._client = None
    conn._tasks = []
    conn.log = MagicMock()
    seen = {}

    async def fake_nudge():
        seen["channels_started"] = mock_client.start_channels.called
        seen["tasks_when_nudged"] = list(conn._tasks)
        return "ready"

    with patch.object(
        KernelWebsocketConnection, "kernel_manager",
        new_callable=PropertyMock, return_value=mock_km,
    ), patch.object(conn, "nudge", side_effect=fake_nudge) as nudge:
        await conn.connect()

    nudge.assert_awaited_once()
    assert seen == {"channels_started": True, "tasks_when_nudged": []}
    assert len(conn._tasks) == 4
    conn.disconnect()


# ── live kernel (requires ipykernel) ──────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_nudge_against_live_kernel_proves_iopub_before_traffic():
    """Against a real ipykernel, connect() forwards an IOPub message first.

    The first WebSocket write after connect() must be the IOPub status the
    nudge provoked, proving the subscription, and a subsequent request sent
    through the bridge must get both its shell reply and its IOPub replies.
    """
    pytest.importorskip("ipykernel")

    km = AsyncKernelManager(kernel_name="python3")
    await km.start_kernel()
    km.kernel_id = "live-kernel"
    writes = []
    got_write = asyncio.Event()
    ws_handler = MagicMock()

    def record(bin_msg, binary):
        channel, msg_list = deserialize_msg_from_ws_v1(bin_msg)
        writes.append((channel, json.loads(msg_list[0])["msg_type"]))
        got_write.set()

    ws_handler.write_message.side_effect = record
    conn = KernelWebsocketConnection(parent=km)

    async def wait_for(predicate):
        while not predicate():
            got_write.clear()
            await asyncio.wait_for(got_write.wait(), 30)

    try:
        with patch.object(
            KernelWebsocketConnection, "websocket_handler",
            new_callable=PropertyMock, return_value=ws_handler,
        ):
            await conn.connect()
            assert writes, "nudge forwarded no IOPub message"
            assert writes[0][0] == "iopub"
            # Only IOPub reached the frontend: transient replies were consumed.
            assert all(channel == "iopub" for channel, _ in writes)

            # The v1 wire format carries [header, parent, metadata, content];
            # serialize() prefixes the <IDS|MSG> delimiter and the signature.
            request = conn._client.session.msg("kernel_info_request")
            parts = conn._client.session.serialize(request)[2:]
            conn.handle_incoming_message(serialize_msg_to_ws_v1(parts, "shell"))
            await wait_for(lambda: ("shell", "kernel_info_reply") in writes)
            await wait_for(lambda: writes.count(("iopub", "status")) >= 2)
    finally:
        conn.disconnect()
        await km.shutdown_kernel(now=True)
