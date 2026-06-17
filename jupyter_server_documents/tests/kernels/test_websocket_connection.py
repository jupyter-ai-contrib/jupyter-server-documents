"""
Tests for KernelWebsocketConnection.

This class bridges each browser WebSocket to its own AsyncKernelClient.
Each connection owns four asyncio receive tasks (shell, control, stdin, iopub)
that forward kernel messages to the browser, and a synchronous handler that
forwards browser messages to the kernel.

Critical invariants:
- The connection must use the v1 wire protocol.
- Each connection creates its own client (not shared across tabs) so kernel
  message routing works correctly.
- disconnect() must cancel all tasks and stop channels, regardless of state.
- Incoming browser messages must be deserialized and forwarded to the correct
  ZMQ socket.
- Outgoing kernel messages must be serialized and written to the WebSocket.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from jupyter_server_documents.websocket_connection import (
    KernelWebsocketConnection,
)


def make_conn():
    """Return a connection instance with mocked infrastructure.

    Bypasses __init__ since it requires a full Tornado request context.
    Sets only the attributes used by the methods under test.
    """
    conn = KernelWebsocketConnection.__new__(KernelWebsocketConnection)
    conn._client = None
    conn._tasks = []
    conn.log = MagicMock()
    return conn


# ── protocol ──────────────────────────────────────────────────────────────────

def test_uses_v1_wire_protocol():
    """The connection must advertise the v1 kernel WebSocket protocol.

    JupyterLab negotiates this during the WebSocket handshake.  If the wrong
    protocol string is used, message framing breaks and the kernel is silent.
    """
    conn = make_conn()
    assert conn.kernel_ws_protocol == "v1.kernel.websocket.jupyter.org"


# ── connect / disconnect ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_connect_creates_client_and_starts_four_listeners():
    """connect() must start exactly four receive tasks — one per ZMQ channel.

    The four channels are shell, control, stdin, and iopub.  Each has an
    independent asyncio task so one slow channel cannot starve the others.
    Heartbeat is skipped (hb=False) because the server-side kernel manager
    handles liveness checking.
    """
    mock_km = MagicMock()
    mock_client = MagicMock()
    for ch in ("shell", "control", "stdin", "iopub"):
        # Each channel's recv_multipart should block until cancelled
        getattr(mock_client, f"{ch}_channel").socket.recv_multipart = AsyncMock(
            side_effect=asyncio.CancelledError
        )
    mock_km.client.return_value = mock_client
    mock_km.get_connection_info.return_value = {}

    conn = make_conn()
    with patch.object(
        KernelWebsocketConnection, "kernel_manager",
        new_callable=PropertyMock, return_value=mock_km,
    ):
        await conn.connect()

    assert conn._client is mock_client
    assert len(conn._tasks) == 4
    mock_client.start_channels.assert_called_once_with(hb=False)
    conn.disconnect()


def test_disconnect_cancels_tasks_and_stops_channels():
    """disconnect() must cancel all listener tasks and stop ZMQ channels.

    Tasks that are not cancelled hold open ZMQ sockets and leak memory.
    stop_channels() closes the underlying sockets so the kernel can reconnect.
    """
    conn = make_conn()
    task = MagicMock()
    conn._tasks = [task]
    mock_client = MagicMock()
    conn._client = mock_client

    conn.disconnect()

    task.cancel.assert_called_once()
    mock_client.stop_channels.assert_called_once()
    assert conn._client is None
    assert conn._tasks == []


def test_disconnect_before_connect_does_not_raise():
    """disconnect() on a fresh connection must be a no-op.

    Tornado can call on_close() before connect() completes (e.g. client
    disconnects immediately).  This must not raise.
    """
    conn = make_conn()
    conn.disconnect()  # no exception


# ── message routing ───────────────────────────────────────────────────────────

def test_incoming_message_routed_to_correct_channel():
    """Browser → kernel: message must be deserialized and sent to the right ZMQ socket.

    The v1 protocol encodes the channel name in the framing.  We must extract
    it and call session.send_raw on the matching channel socket.
    """
    conn = make_conn()
    mock_client = MagicMock()
    conn._client = mock_client
    parts = [b"frame1", b"frame2"]

    with patch(
        "jupyter_server_documents.websocket_connection.deserialize_msg_from_ws_v1",
        return_value=("shell", parts),
    ):
        conn.handle_incoming_message(b"<any-bytes>")

    mock_client.session.send_raw.assert_called_once_with(
        mock_client.shell_channel.socket, parts
    )


def test_incoming_message_with_no_client_does_not_raise():
    """Incoming messages before connect() (or after disconnect()) must be dropped.

    There is a race window between the WebSocket opening and connect()
    completing.  Raising here would crash the Tornado handler.
    """
    conn = make_conn()
    conn._client = None
    with patch(
        "jupyter_server_documents.websocket_connection.deserialize_msg_from_ws_v1",
        return_value=("shell", []),
    ):
        conn.handle_incoming_message(b"<any-bytes>")


@pytest.mark.asyncio
async def test_listener_forwards_kernel_message_to_websocket():
    """Kernel → browser: _listen must serialize and write each message.

    _listen reads from a ZMQ socket in a loop, strips the identity frame,
    serializes the remaining frames, and writes to the WebSocket handler.
    The first recv returns a real message; the second raises CancelledError
    to terminate the loop cleanly.
    """
    conn = make_conn()
    mock_client = MagicMock()
    mock_session = MagicMock()
    # feed_identities returns (identities, rest_of_frames)
    mock_session.feed_identities.return_value = (
        [], [b"<sig>", b"<header>", b"<parent>", b"<meta>", b"<content>"]
    )
    mock_client.session = mock_session
    conn._client = mock_client

    call_count = 0

    async def recv():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [b"<id>", b"<sig>", b"<header>", b"<parent>", b"<meta>", b"<content>"]
        raise asyncio.CancelledError()

    mock_client.shell_channel.socket.recv_multipart = AsyncMock(side_effect=recv)
    ws_handler = MagicMock()

    with patch.object(
        type(conn), "websocket_handler", new_callable=PropertyMock, return_value=ws_handler
    ), patch(
        "jupyter_server_documents.websocket_connection.serialize_msg_to_ws_v1",
        return_value=b"<serialized>",
    ):
        task = asyncio.create_task(conn._listen("shell"))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    ws_handler.write_message.assert_called_with(b"<serialized>", binary=True)
