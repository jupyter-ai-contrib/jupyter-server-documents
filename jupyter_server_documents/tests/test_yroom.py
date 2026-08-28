from __future__ import annotations
import asyncio
import pytest
from unittest.mock import Mock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom, MakeYRoomManager, MakeRoomFile


class TestYRoomCallbacks():
    """
    Tests for `YRoom` on_stop callback behavior.
    """

    @pytest.mark.asyncio
    async def test_on_stop_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks registered via `add_stop_callback()`
        are called when the room is stopped.
        """
        yroom = await make_yroom()

        stop_mock_1 = Mock()
        stop_mock_2 = Mock()

        yroom.add_stop_callback(stop_mock_1)
        yroom.add_stop_callback(stop_mock_2)

        stop_mock_1.assert_not_called()
        stop_mock_2.assert_not_called()

        yroom.stop()

        stop_mock_1.assert_called_once()
        stop_mock_2.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_emits_clean_room_event(self, make_yroom: MakeYRoom):
        """
        Asserts that stopping a room emits a 'clean' room event, which
        jupyterlab-chat relies on to release the chat for that room.
        """
        yroom = await make_yroom()
        yroom.events_api.emit_room_event = Mock()

        yroom.stop()

        yroom.events_api.emit_room_event.assert_called_once_with("clean")


class TestYRoomMessageQueue():
    """
    Tests for the `YRoom._process_message_queue()` background task.
    """

    @pytest.mark.asyncio
    async def test_queue_continues_after_handle_message_error(self):
        """
        Asserts that an exception raised by `handle_message()` neither
        terminates the `_process_message_queue()` background task nor skips
        the `task_done()` call for the failed message.

        Regression test for #271: a queued message from a client that had
        already disconnected raised from `handle_message()`, which terminated
        the background task and left the room unable to process any future
        message from any client.
        """
        import logging
        from jupyter_server_documents.rooms.yroom import YRoom

        handled: list[tuple[str, bytes]] = []

        class StubRoom:
            """
            Minimal stand-in providing only the attributes that
            `YRoom._process_message_queue()` uses.
            """
            room_id = "text:file:stub"
            file_api = None
            log = logging.getLogger("test_yroom.stub")

            def __init__(self):
                self._message_queue: asyncio.Queue = asyncio.Queue()

            async def handle_message(self, client_id: str, message: bytes):
                if client_id == "disconnected-client":
                    raise Exception("client not found")
                handled.append((client_id, message))

        stub = StubRoom()
        task = asyncio.create_task(YRoom._process_message_queue(stub))

        stub._message_queue.put_nowait(("disconnected-client", b"\x00\x02"))
        stub._message_queue.put_nowait(("connected-client", b"\x01\x00"))

        # `join()` only unblocks once `task_done()` has been called for both
        # messages, including the one whose handler raised.
        await asyncio.wait_for(stub._message_queue.join(), timeout=2)

        # The message following the failed one must still be handled.
        assert handled == [("connected-client", b"\x01\x00")]

        # The background task must still be running; halt it as `stop()` does.
        assert not task.done()
        stub._message_queue.put_nowait(None)
        await asyncio.wait_for(task, timeout=2)


class TestYRoomInactivity():
    """
    Tests for `YRoom` inactivity timeout behavior.
    """

    @pytest.mark.asyncio
    async def test_custom_inactivity_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that `inactivity_timeout` can be set via the constructor.
        """
        room = await make_yroom(inactivity_timeout=10)
        assert room.inactivity_timeout == 10

    @pytest.mark.asyncio
    async def test_basic_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that a room becomes inactive only after `inactivity_timeout`
        elapses.
        """
        room = await make_yroom(inactivity_timeout=1)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is True

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_execution_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_awareness_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

