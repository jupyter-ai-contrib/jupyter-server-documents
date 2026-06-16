"""
Integration tests for YRoom sync handshake behavior.

These tests use a FakeWebSocket client that simulates the client side of the
Yjs sync protocol against a real YRoom instance. They verify:

1. Normal sync handshake completes successfully.
2. Divergent client detection works correctly.
3. Divergent client handshake resolves content duplication.
4. Timeout fires if client never sends SS2.
5. Update buffer pauses/resumes correctly during divergent handshake.
6. No data loss when mutations occur during the sync handshake.
"""

from __future__ import annotations

import asyncio
import pycrdt
from pycrdt import Doc, Text
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom
    from jupyter_server_documents.rooms.yroom import YRoom


class FakeWebSocket:
    """A fake WebSocket that records messages sent by the server and can
    replay the client side of the Yjs sync handshake.

    Usage:
        ws = FakeWebSocket()
        # optionally pre-populate with divergent content:
        ws.doc["source"] += "hello world"

        client_id = yroom.clients.add(ws)
        # server processes SS1 via the message queue or handle_sync()
        # then inspect ws.messages for what the server sent
    """

    def __init__(self, doc: Doc | None = None):
        self.doc = doc or Doc()
        if "source" not in self.doc:
            self.doc["source"] = Text()
        self.messages: list[bytes] = []
        self.closed = False
        self.close_code: int | None = None
        # Required by YjsClientGroup.get() check
        self.ws_connection = True

    def write_message(self, message: bytes, binary: bool = True) -> None:
        """Called by the server to send a message to this client."""
        self.messages.append(message)

    def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = True
        self.close_code = code

    def build_ss1(self) -> bytes:
        """Build an SS1 message from this client's YDoc."""
        return pycrdt.create_sync_message(self.doc)

    def process_server_messages(self) -> bytes | None:
        """Process all messages from the server (SS2 + SS1) and return the
        SS2 reply to send back, or None if no SS1 was received."""
        ss2_reply = None
        for msg in self.messages:
            if len(msg) < 2:
                continue
            msg_type = msg[0]
            if msg_type == YMessageType.SYNC:
                reply = pycrdt.handle_sync_message(msg[1:], self.doc)
                if reply is not None:
                    # reply is an SS2 response to the server's SS1
                    ss2_reply = reply
        return ss2_reply

    @property
    def source(self) -> str:
        return str(self.doc["source"])


class TestNormalSync:
    """Tests for normal (non-divergent) sync handshake."""

    @pytest.mark.asyncio
    async def test_fresh_client_syncs_successfully(self, make_yroom: MakeYRoom):
        """A fresh client with an empty YDoc should complete the handshake."""
        yroom = await make_yroom()
        ws = FakeWebSocket()
        client_id = yroom.clients.add(ws)

        # Send SS1 via add_message (goes through the queue)
        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)

        # Give the message queue time to process SS1 and await SS2
        await asyncio.sleep(0.1)

        # Client processes server's SS2 + SS1, gets SS2 reply
        ss2_reply = ws.process_server_messages()
        assert ss2_reply is not None

        # Send SS2 reply back (bypasses queue via future)
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # Client should be synced
        client = yroom.clients.get(client_id)
        assert client.synced

    @pytest.mark.asyncio
    async def test_client_receives_existing_content(self, make_yroom: MakeYRoom):
        """A fresh client should receive the server's existing content."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        ws = FakeWebSocket()
        client_id = yroom.clients.add(ws)

        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        ss2_reply = ws.process_server_messages()
        assert ss2_reply is not None
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # Client should have the server's content
        assert ws.source == "hello world"


class TestDivergentSync:
    """Tests for divergent client sync (content deduplication)."""

    @pytest.mark.asyncio
    async def test_divergent_client_detected(self, make_yroom: MakeYRoom):
        """A client with unknown client IDs should be detected as divergent."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        # Client has same content but different CRDT history
        ws = FakeWebSocket()
        ws.doc["source"] += "hello world"

        ss1 = ws.build_ss1()
        assert yroom._has_divergent_history(ss1[1:], yroom._ydoc.get_state())


class TestSyncTimeout:
    """Tests for handshake timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_when_ss2_never_arrives(self, make_yroom: MakeYRoom):
        """If the client never sends SS2, the handshake should time out and
        the source should be restored."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        ws = FakeWebSocket()
        ws.doc["source"] += "hello world"
        client_id = yroom.clients.add(ws)

        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)

        # Wait for timeout (5s + buffer)
        await asyncio.sleep(6)

        # Source should be restored
        assert jupyter_ydoc.source == "hello world"
        # Saves should be re-enabled
        assert yroom.file_api._reloading_content is False
        # Buffer should be unpaused
        assert yroom.update_channel._paused is False


async def _complete_handshake(yroom: YRoom, ws: FakeWebSocket) -> str:
    """Helper: add a FakeWebSocket client and complete the full sync handshake.
    Returns the client_id."""
    client_id = yroom.clients.add(ws)
    yroom.add_message(client_id, ws.build_ss1())
    await asyncio.sleep(0.1)
    ss2_reply = ws.process_server_messages()
    assert ss2_reply is not None, "Server did not send SS1 (no SS2 reply generated)"
    yroom.add_message(client_id, ss2_reply)
    await asyncio.sleep(0.1)
    return client_id


class TestSyncHandshakeStress:
    """
    Stress tests for data integrity when mutations occur during the sync
    handshake.

    These reproduce the scenario from jupyter-ai-contrib/jupyter-server-documents#197
    where an AI agent rapidly adds content via MCP tool calls while a second
    browser tab connects. Mutations that occur while a client is completing
    the handshake must not be lost.
    """

    @pytest.mark.asyncio
    async def test_mutations_before_handshake_not_lost(self, make_yroom: MakeYRoom):
        """Mutations between client connect and handshake must be received.

        Simulates: AI agent adds 20 lines while a second tab is connecting.
        """
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()

        # Sync client A (first browser tab)
        ws_a = FakeWebSocket()
        await _complete_handshake(yroom, ws_a)

        # Client B connects (second browser tab) — starts as desynced
        ws_b = FakeWebSocket()
        cid_b = yroom.clients.add(ws_b)

        # While B is desynced, AI agent rapidly mutates the doc
        expected = ""
        for i in range(20):
            expected += f"AI added line {i}\n"
            jupyter_ydoc.source = expected

        # Complete B's handshake
        yroom.add_message(cid_b, ws_b.build_ss1())
        await asyncio.sleep(0.1)
        ss2_reply = ws_b.process_server_messages()
        assert ss2_reply is not None
        yroom.add_message(cid_b, ss2_reply)
        await asyncio.sleep(0.1)

        # B must have the full content — no data loss
        assert ws_b.source == expected

    @pytest.mark.asyncio
    async def test_mutations_during_handshake_await(self, make_yroom: MakeYRoom):
        """Mutations during the SS2 reply await must be received.

        Simulates: AI agent adds content while the server is waiting for the
        client's SS2 reply (the async gap in handle_sync).
        """
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "initial"

        # Sync client A
        ws_a = FakeWebSocket()
        await _complete_handshake(yroom, ws_a)

        # Client B starts handshake
        ws_b = FakeWebSocket()
        cid_b = yroom.clients.add(ws_b)
        yroom.add_message(cid_b, ws_b.build_ss1())
        await asyncio.sleep(0.1)
        # handle_sync is now awaiting B's SS2 reply

        # Mutate doc while handle_sync is awaiting
        jupyter_ydoc.source = "initial\nmutated during handshake"

        # Complete B's handshake
        ss2_reply = ws_b.process_server_messages()
        assert ss2_reply is not None
        yroom.add_message(cid_b, ss2_reply)
        await asyncio.sleep(0.1)

        # Broadcasts are paused during the handshake, so the mutation made while
        # the server awaited B's SS2 is delivered via the batched catchup diff
        # broadcast on resume. Process the post-handshake messages to apply it.
        ws_b.process_server_messages()

        assert ws_b.source == "initial\nmutated during handshake"

    @pytest.mark.asyncio
    async def test_no_exception_during_concurrent_handshakes(self, make_yroom: MakeYRoom):
        """Multiple clients handshaking while doc is mutated must not crash."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "initial"

        # Sync client A
        ws_a = FakeWebSocket()
        await _complete_handshake(yroom, ws_a)

        # Connect 5 desynced clients
        desynced = []
        for _ in range(5):
            ws = FakeWebSocket()
            cid = yroom.clients.add(ws)
            desynced.append((ws, cid))

        # Rapid mutations while all 5 are desynced
        for i in range(50):
            jupyter_ydoc.source = f"mutation {i}"

        # Sync all clients sequentially — no exceptions should be raised
        for ws, cid in desynced:
            yroom.add_message(cid, ws.build_ss1())
            await asyncio.sleep(0.1)
            ss2_reply = ws.process_server_messages()
            assert ss2_reply is not None
            yroom.add_message(cid, ss2_reply)
            await asyncio.sleep(0.1)

        # All must have the final state
        for ws, _ in desynced:
            assert ws.source == "mutation 49"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("num_mutations", [10, 50, 100])
    @pytest.mark.parametrize("num_clients", [2, 5])
    async def test_concurrent_mutations_stress(
        self, make_yroom: MakeYRoom, num_mutations: int, num_clients: int
    ):
        """N clients connect while the doc undergoes M mutations.
        All clients must converge to the same final state."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()

        # Connect N desynced clients
        clients = []
        for _ in range(num_clients):
            ws = FakeWebSocket()
            cid = yroom.clients.add(ws)
            clients.append((ws, cid))

        # M mutations while all clients are desynced
        expected = ""
        for i in range(num_mutations):
            expected += f"line {i}\n"
            jupyter_ydoc.source = expected

        # Sync all clients
        for ws, cid in clients:
            yroom.add_message(cid, ws.build_ss1())
            await asyncio.sleep(0.1)
            ss2_reply = ws.process_server_messages()
            assert ss2_reply is not None
            yroom.add_message(cid, ss2_reply)
            await asyncio.sleep(0.1)

        # All must have the final content
        for ws, _ in clients:
            assert ws.source == expected


class TestSyncUpdateChannel:
    """Invariants on the update channel during the sync handshake."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "divergent", [False, True], ids=["normal", "divergent"]
    )
    async def test_update_channel_paused_during_sync(
        self, make_yroom: MakeYRoom, divergent: bool
    ):
        """The update channel must be paused for the duration of *any* sync
        handshake (normal or divergent), then resumed once it completes.

        The backend treats all syncs equivalently: broadcasts are paused so
        that mutations during the handshake gap are batched into a single
        catchup diff on resume rather than streamed individually (see
        YRoomUpdateChannel and #197).
        """
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        ws = FakeWebSocket()
        if divergent:
            # Same content, authored under a different client ID, so the
            # client's state vector contains an ID the server doesn't know.
            ws.doc["source"] += "hello world"
            assert yroom._has_divergent_history(
                ws.build_ss1()[1:], yroom._ydoc.get_state()
            )

        client_id = yroom.clients.add(ws)
        yroom.add_message(client_id, ws.build_ss1())
        await asyncio.sleep(0.1)

        # Mid-handshake: the server has sent SS2 + SS1 and is awaiting the
        # client's SS2 reply, so broadcasts must be paused.
        assert yroom.update_channel._paused is True

        ss2_reply = ws.process_server_messages()
        assert ss2_reply is not None
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # Handshake complete: the channel must be resumed.
        assert yroom.update_channel._paused is False
