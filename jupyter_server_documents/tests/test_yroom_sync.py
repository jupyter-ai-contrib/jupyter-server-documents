"""
Integration tests for YRoom sync handshake behavior.

These tests use a FakeWebSocket client that simulates the client side of the
Yjs sync protocol against a real YRoom instance. They verify:

1. Normal sync handshake completes successfully.
2. Divergent client detection works correctly.
3. Divergent client handshake resolves content duplication.
4. Timeout fires if client never sends SS2.
5. Update buffer pauses/resumes correctly during divergent handshake.
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
        assert yroom._has_divergent_history(ss1[1:])

    @pytest.mark.asyncio
    async def test_divergent_client_no_duplication(self, make_yroom: MakeYRoom):
        """After a divergent handshake, content should not be duplicated."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        # Client with same content, different history
        ws = FakeWebSocket()
        ws.doc["source"] += "hello world"
        client_id = yroom.clients.add(ws)

        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        ss2_reply = ws.process_server_messages()
        assert ss2_reply is not None
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # No duplication on either side
        assert jupyter_ydoc.source == "hello world"
        assert ws.source == "hello world"

    @pytest.mark.asyncio
    async def test_divergent_client_no_save_during_handshake(self, make_yroom: MakeYRoom):
        """File saves should be suppressed during the divergent handshake."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        ws = FakeWebSocket()
        ws.doc["source"] += "hello world"
        client_id = yroom.clients.add(ws)

        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        # During handshake, saves should be suppressed
        assert yroom.file_api._reloading_content is True

        ss2_reply = ws.process_server_messages()
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # After handshake, saves should be re-enabled
        assert yroom.file_api._reloading_content is False

    @pytest.mark.asyncio
    async def test_update_buffer_paused_during_divergent_handshake(self, make_yroom: MakeYRoom):
        """The update buffer should be paused during a divergent handshake."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        ws = FakeWebSocket()
        ws.doc["source"] += "hello world"
        client_id = yroom.clients.add(ws)

        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        # Buffer should be paused during handshake
        assert yroom.update_buffer._paused is True

        ss2_reply = ws.process_server_messages()
        yroom.add_message(client_id, ss2_reply)
        await asyncio.sleep(0.1)

        # Buffer should be unpaused after handshake
        assert yroom.update_buffer._paused is False


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
        assert yroom.update_buffer._paused is False


class TestMultipleClients:
    """Tests for multiple clients syncing."""

    @pytest.mark.asyncio
    async def test_two_divergent_clients_sequential(self, make_yroom: MakeYRoom):
        """Two divergent clients syncing sequentially should both get correct
        content."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        for _ in range(2):
            ws = FakeWebSocket()
            ws.doc["source"] += "hello world"
            client_id = yroom.clients.add(ws)

            ss1 = ws.build_ss1()
            yroom.add_message(client_id, ss1)
            await asyncio.sleep(0.1)

            ss2_reply = ws.process_server_messages()
            assert ss2_reply is not None
            yroom.add_message(client_id, ss2_reply)
            await asyncio.sleep(0.1)

            assert jupyter_ydoc.source == "hello world"
            assert ws.source == "hello world"

    @pytest.mark.asyncio
    async def test_fresh_then_divergent_client(self, make_yroom: MakeYRoom):
        """A fresh client followed by a divergent client should both work."""
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world"

        # Fresh client
        ws1 = FakeWebSocket()
        cid1 = yroom.clients.add(ws1)
        yroom.add_message(cid1, ws1.build_ss1())
        await asyncio.sleep(0.1)
        ss2 = ws1.process_server_messages()
        yroom.add_message(cid1, ss2)
        await asyncio.sleep(0.1)
        assert ws1.source == "hello world"

        # Divergent client
        ws2 = FakeWebSocket()
        ws2.doc["source"] += "hello world"
        cid2 = yroom.clients.add(ws2)
        yroom.add_message(cid2, ws2.build_ss1())
        await asyncio.sleep(0.1)
        ss2 = ws2.process_server_messages()
        yroom.add_message(cid2, ss2)
        await asyncio.sleep(0.1)

        assert jupyter_ydoc.source == "hello world"
        assert ws2.source == "hello world"
