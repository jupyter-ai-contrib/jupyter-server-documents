"""
Tests for YNotebookRoom.execute_cell() — source hash verification and
request ordering.

The source_hash feature prevents a cell from being executed with code the
requesting user never saw (because a collaborator edited it in between).

The request_id / previous_request_id chaining guarantees that rapid
single-cell execute calls arrive at the queue in the same order the user
pressed Run, regardless of network jitter.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jupyter_server_documents.rooms.ynotebook_room import (
    YNotebookRoom,
    SourceMismatchError,
    PredecessorTimeoutError,
    _source_hash,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_room():
    """Return a YNotebookRoom with all state initialized but no real __init__."""
    room = YNotebookRoom.__new__(YNotebookRoom)
    room.room_id = "json:notebook:file-abc"
    room.log = MagicMock()
    room._kernel_client = MagicMock()
    room._kernel_manager = MagicMock()
    room._shell_confirmed = True
    room._execution_queue = asyncio.Queue()
    room._execution_worker_task = MagicMock(done=MagicMock(return_value=False))
    room.output_processor = None
    room._enqueued_events = {}
    return room


def make_ydoc(cell_source: str, cell_id: str = "cell-1"):
    mock_cell = {"id": cell_id, "cell_type": "code", "source": cell_source, "outputs": []}
    ydoc = MagicMock()
    ydoc.ycells = [mock_cell]
    return ydoc, mock_cell


# ── source_hash helper ────────────────────────────────────────────────────────

def test_source_hash_is_murmur2():
    """_source_hash uses MurmurHash2 with seed 0, returned as a decimal string."""
    assert _source_hash("print('hello')") == "3975440051"


def test_source_hash_empty_string():
    assert _source_hash("") == "0"


# ── source hash verification ──────────────────────────────────────────────────

class TestSourceHashVerification:
    """execute_cell rejects execution when source_hash mismatches the YDoc."""

    @pytest.mark.asyncio
    async def test_matching_hash_allows_execution(self):
        """Correct hash passes through and the cell is enqueued."""
        room = make_room()
        source = "x = 1"
        ydoc, cell = make_ydoc(source)
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash(source))

        assert not room._execution_queue.empty()
        assert cell["execution_state"] == "running"

    @pytest.mark.asyncio
    async def test_mismatched_hash_raises_source_mismatch_error(self):
        """Stale hash raises SourceMismatchError before the cell is touched."""
        room = make_room()
        ydoc, cell = make_ydoc("x = 2")  # server has this
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(SourceMismatchError) as exc_info:
            await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"))

        assert exc_info.value.cell_id == "cell-1"
        # Cell must not have been touched
        assert room._execution_queue.empty()
        assert cell.get("execution_state") is None

    @pytest.mark.asyncio
    async def test_missing_hash_raises_value_error(self):
        """Omitting source_hash raises ValueError (it is now required)."""
        room = make_room()
        ydoc, _ = make_ydoc("any source")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(ValueError, match="source_hash is required"):
            await room.execute_cell("cell-1", source_hash=None)

    @pytest.mark.asyncio
    async def test_empty_source_hash_matches_empty_cell(self):
        """A cell with no source and hash of '' matches correctly."""
        room = make_room()
        ydoc, _ = make_ydoc("")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash(""))

        assert not room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_source_mismatch_error_carries_cell_id(self):
        """SourceMismatchError exposes the cell_id for the 409 response."""
        room = make_room()
        ydoc, _ = make_ydoc("server source", cell_id="my-cell-99")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(SourceMismatchError) as exc_info:
            await room.execute_cell("my-cell-99", source_hash="999999999")

        assert exc_info.value.cell_id == "my-cell-99"


# ── request ordering ──────────────────────────────────────────────────────────

class TestRequestOrdering:
    """execute_cell guarantees FIFO enqueue order via request_id chaining."""

    @pytest.mark.asyncio
    async def test_request_id_is_stored_after_enqueue(self):
        """After enqueue, request_id is recorded as a set Event."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), request_id="req-A")

        assert "req-A" in room._enqueued_events
        assert room._enqueued_events["req-A"].is_set()

    @pytest.mark.asyncio
    async def test_successor_waits_for_predecessor_event(self):
        """A request with previous_request_id waits until that event is set."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Pre-register a predecessor event that is NOT yet set.
        predecessor_event = asyncio.Event()
        room._enqueued_events["req-A"] = predecessor_event

        # Start the successor — it should block until we set the event.
        task = asyncio.create_task(
            room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), request_id="req-B", previous_request_id="req-A")
        )
        await asyncio.sleep(0)  # let the coroutine start
        assert room._execution_queue.empty(), "should still be waiting"

        # Release the predecessor.
        predecessor_event.set()
        await task

        assert not room._execution_queue.empty(), "should now be enqueued"

    @pytest.mark.asyncio
    async def test_unknown_predecessor_times_out(self):
        """If previous_request_id never arrives, the request times out.

        B arrived before A but A never shows up (e.g. A's HTTP request was
        dropped). B must not block forever — it times out with
        PredecessorTimeoutError.
        """
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # No entry for "req-A-dropped" — simulates A being lost in transit.
        with patch("jupyter_server_documents.rooms.ynotebook_room._PREDECESSOR_TIMEOUT", 0.05):
            with pytest.raises(PredecessorTimeoutError):
                await room.execute_cell(
                    "cell-1",
                    source_hash=_source_hash("x = 1"),
                    request_id="req-B",
                    previous_request_id="req-A-dropped",
                )

        assert room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_predecessor_timeout_raises(self):
        """If the predecessor never sets its event, PredecessorTimeoutError is raised."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Register a predecessor that will never be set.
        room._enqueued_events["req-stuck"] = asyncio.Event()

        # Patch the timeout to a tiny value so the test runs fast.
        with patch("jupyter_server_documents.rooms.ynotebook_room._PREDECESSOR_TIMEOUT", 0.05):
            with pytest.raises(PredecessorTimeoutError):
                await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), previous_request_id="req-stuck")

        assert room._execution_queue.empty(), "cell must not have been enqueued"

    @pytest.mark.asyncio
    async def test_chained_requests_enqueued_in_order(self):
        """B arrives before A but still enqueues after A (true out-of-order fix)."""
        room = make_room()
        cell_a = {"id": "cell-a", "cell_type": "code", "source": "a = 1", "outputs": []}
        cell_b = {"id": "cell-b", "cell_type": "code", "source": "b = 2", "outputs": []}

        call_count = 0
        async def get_ydoc():
            nonlocal call_count
            call_count += 1
            ydoc = MagicMock()
            ydoc.ycells = [cell_a] if call_count == 1 else [cell_b]
            return ydoc

        room.get_jupyter_ydoc = get_ydoc

        # B arrives first — creates an unset event for "req-A" and waits.
        task_b = asyncio.create_task(
            room.execute_cell("cell-b", source_hash=_source_hash("b = 2"), request_id="req-B", previous_request_id="req-A")
        )
        await asyncio.sleep(0)  # let B start and register its wait
        assert room._execution_queue.empty(), "B should be blocked waiting for A"

        # A arrives and enqueues — sets the event B is waiting on.
        await room.execute_cell("cell-a", source_hash=_source_hash("a = 1"), request_id="req-A")
        await task_b  # B should now complete

        a_item = room._execution_queue.get_nowait()
        b_item = room._execution_queue.get_nowait()
        assert a_item.cell_id == "cell-a"
        assert b_item.cell_id == "cell-b"

    @pytest.mark.asyncio
    async def test_enqueued_events_cleared_on_disconnect(self):
        """disconnect_kernel() clears _enqueued_events to avoid stale state."""
        room = make_room()
        room._enqueued_events["req-old-1"] = asyncio.Event()
        room._enqueued_events["req-old-1"].set()
        room._enqueued_events["req-old-2"] = asyncio.Event()

        room._execution_worker_task = MagicMock()
        room._execution_worker_task.done.return_value = True
        room._kernel_manager = MagicMock(
            remove_restart_callback=MagicMock(side_effect=Exception("not registered"))
        )

        await room.disconnect_kernel()

        assert room._enqueued_events == {}

    @pytest.mark.asyncio
    async def test_predecessor_entry_deleted_after_consumption(self):
        """Predecessor event is removed from _enqueued_events once consumed."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Enqueue A, then B chained after A.
        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), request_id="req-A")
        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), request_id="req-B", previous_request_id="req-A")

        # A's entry should be gone (consumed by B); B's entry is the tail.
        assert "req-A" not in room._enqueued_events
        assert "req-B" in room._enqueued_events

    @pytest.mark.asyncio
    async def test_timed_out_predecessor_entry_deleted(self):
        """Timed-out predecessor event is removed, not left as an orphan."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        room._enqueued_events["req-stuck"] = asyncio.Event()  # never set

        with patch("jupyter_server_documents.rooms.ynotebook_room._PREDECESSOR_TIMEOUT", 0.05):
            with pytest.raises(PredecessorTimeoutError):
                await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), previous_request_id="req-stuck")

        assert "req-stuck" not in room._enqueued_events
