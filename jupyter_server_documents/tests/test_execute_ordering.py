"""
Tests for YNotebookRoom.execute_cells() — source hash verification and
sequence-based ordering.

The source_hash feature prevents a cell from being executed with code the
requesting user never saw (because a collaborator edited it in between).

Sequence-based ordering guarantees rapid execute calls arrive at the
queue in the order the user pressed Run, regardless of network jitter.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from jupyter_server_documents.rooms.ynotebook_room import (
    YNotebookRoom,
    SequenceOutOfRangeError,
    SessionResetError,
    SourceMismatchError,
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
    room._reattach_tasks = []
    room._next_seq = {}
    room._seq_generation = {}
    room._seq_cv = asyncio.Condition()
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
        room = make_room()
        source = "x = 1"
        ydoc, cell = make_ydoc(source)
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash(source))

        assert not room._execution_queue.empty()
        assert cell["execution_state"] == "running"

    @pytest.mark.asyncio
    async def test_mismatched_hash_raises_source_mismatch_error(self):
        room = make_room()
        ydoc, cell = make_ydoc("x = 2")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(SourceMismatchError) as exc_info:
            await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"))

        assert exc_info.value.cell_id == "cell-1"
        assert room._execution_queue.empty()
        assert cell.get("execution_state") is None

    @pytest.mark.asyncio
    async def test_missing_hash_raises_value_error(self):
        room = make_room()
        ydoc, _ = make_ydoc("any source")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(ValueError, match="source_hash is required"):
            await room.execute_cell("cell-1", source_hash=None)

    @pytest.mark.asyncio
    async def test_empty_source_hash_matches_empty_cell(self):
        room = make_room()
        ydoc, _ = make_ydoc("")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash(""))

        assert not room._execution_queue.empty()


# ── sequence-based ordering ───────────────────────────────────────────────────

class TestSequenceOrdering:
    """execute_cells enqueues in strict sequence order per client_id."""

    @pytest.mark.asyncio
    async def test_in_order_arrivals_advance_next_seq(self):
        """Three sequential arrivals bump next_seq to 3."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        for seq in range(3):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=seq,
            )

        assert room._next_seq["tab-A"] == 3
        assert room._execution_queue.qsize() == 3

    @pytest.mark.asyncio
    async def test_out_of_order_buffered_until_predecessor_arrives(self):
        """seq=1 arrives before seq=0; waits, then processes after seq=0."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # seq=1 arrives first — should block waiting for seq=0.
        task_b = asyncio.create_task(
            room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=1,
            )
        )
        # Give the coroutine a chance to hit the wait.
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert room._execution_queue.empty(), "seq=1 must be blocked waiting for seq=0"

        # seq=0 arrives — should enqueue, then unblock seq=1 which also enqueues.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=0,
        )
        await task_b

        assert room._execution_queue.qsize() == 2
        assert room._next_seq["tab-A"] == 2

    @pytest.mark.asyncio
    async def test_sequence_below_next_seq_raises(self):
        """A late/duplicate sequence below next_seq is rejected."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Advance to seq=1 (next_seq=2).
        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), client_id="tab-A", sequence=0)
        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), client_id="tab-A", sequence=1)

        with pytest.raises(SequenceOutOfRangeError):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=1,   # already processed
            )

    @pytest.mark.asyncio
    async def test_sequence_zero_after_high_seq_resets_state(self):
        """seq=0 after next_seq > 0 clears state and starts over."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        for seq in range(3):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=seq,
            )
        assert room._next_seq["tab-A"] == 3

        # Browser resets — sends seq=0.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=0,
        )
        # After reset + this request, next_seq is 1 (0 processed, advanced to 1).
        assert room._next_seq["tab-A"] == 1

    @pytest.mark.asyncio
    async def test_session_reset_wakes_pending_waiter(self):
        """A pending seq=5 waiter is abandoned when a seq=0 reset arrives."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Advance to next_seq=1 first (so the reset actually resets something).
        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), client_id="tab-A", sequence=0)

        # seq=5 arrives, blocks waiting for seq=1..4.
        waiter = asyncio.create_task(
            room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=5,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not waiter.done()

        # Reset comes in — the waiter should raise SessionResetError.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=0,
        )

        with pytest.raises(SessionResetError):
            await waiter

    @pytest.mark.asyncio
    async def test_lost_predecessor_times_out(self, monkeypatch):
        """A waiter whose predecessor request never arrives is abandoned
        after ``kernel_info_timeout`` so peers stuck behind it recover."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Force a short timeout so the test doesn't wait 60s.
        monkeypatch.setattr(room, "_seq_wait_timeout", lambda: 0.05)

        # Send seq=3 without ever sending seq=0..2.
        with pytest.raises(SessionResetError, match="timed out"):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=3,
            )

    @pytest.mark.asyncio
    async def test_advances_even_on_source_mismatch(self):
        """A failed request still advances the sequence — the slot is used."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        with pytest.raises(SourceMismatchError):
            await room.execute_cell(
                "cell-1",
                source_hash="does-not-match",
                client_id="tab-A",
                sequence=0,
            )

        # next_seq must have advanced so subsequent requests aren't stuck.
        assert room._next_seq["tab-A"] == 1

        # Next request with seq=1 proceeds normally.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=1,
        )
        assert not room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_independent_clients_dont_block_each_other(self):
        """tab-A's out-of-order queue doesn't block tab-B."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # tab-A seq=1 arrives first — blocks.
        waiter_a = asyncio.create_task(
            room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=1,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not waiter_a.done()

        # tab-B seq=0 must run to completion independently.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-B",
            sequence=0,
        )
        assert room._next_seq["tab-B"] == 1

        # Unblock tab-A.
        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=0,
        )
        await waiter_a
        assert room._next_seq["tab-A"] == 2

    @pytest.mark.asyncio
    async def test_sequence_state_cleared_on_disconnect(self):
        """disconnect_kernel() clears next_seq and abandons pending waiters."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell("cell-1", source_hash=_source_hash("x = 1"), client_id="tab-A", sequence=0)

        waiter = asyncio.create_task(
            room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=5,
            )
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not waiter.done()

        # Prep for disconnect_kernel — pretend the worker task is already done.
        room._execution_worker_task = MagicMock()
        room._execution_worker_task.done.return_value = True
        room._kernel_manager = MagicMock(
            remove_restart_callback=MagicMock(side_effect=Exception("not registered"))
        )

        await room.disconnect_kernel()

        assert room._next_seq == {}
        with pytest.raises(SessionResetError):
            await waiter


class TestAbortPendingExecutions:
    """abort_pending_executions() drains queued cells on interrupt."""

    @pytest.mark.asyncio
    async def test_drains_queue_and_marks_idle(self):
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Enqueue three cells.
        for seq in range(3):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=seq,
            )
        assert room._execution_queue.qsize() == 3

        aborted = room.abort_pending_executions()

        assert aborted == 3
        assert room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_no_op_when_no_queue(self):
        room = make_room()
        room._execution_queue = None
        assert room.abort_pending_executions() == 0

    @pytest.mark.asyncio
    async def test_no_op_when_queue_empty(self):
        room = make_room()
        assert room.abort_pending_executions() == 0


class TestSequencePreservedAcrossRestart:
    """Kernel restart-in-place preserves per-client sequence counters.

    The browser's per-``docKey`` counter isn't reset on restart (same
    ``kernel_id``), so the server's ``_next_seq`` must survive too —
    otherwise the next request (with sequence N > 0) waits forever for
    predecessors that will never arrive.
    """

    @pytest.mark.asyncio
    async def test_disconnect_kernel_reset_false_preserves_next_seq(self):
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        # Advance next_seq to 3 by running three cells.
        for seq in range(3):
            await room.execute_cell(
                "cell-1",
                source_hash=_source_hash("x = 1"),
                client_id="tab-A",
                sequence=seq,
            )
        assert room._next_seq["tab-A"] == 3

        # Prep for disconnect_kernel — pretend worker is already done.
        room._execution_worker_task = MagicMock()
        room._execution_worker_task.done.return_value = True
        room._kernel_manager = MagicMock(
            remove_restart_callback=MagicMock(side_effect=Exception("not registered"))
        )

        await room.disconnect_kernel(reset_sequences=False)

        # Next_seq preserved. Next request with sequence=3 proceeds normally.
        assert room._next_seq["tab-A"] == 3

    @pytest.mark.asyncio
    async def test_default_disconnect_kernel_still_resets(self):
        """Default reset_sequences=True still clears state (existing behaviour)."""
        room = make_room()
        ydoc, _ = make_ydoc("x = 1")
        room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)

        await room.execute_cell(
            "cell-1",
            source_hash=_source_hash("x = 1"),
            client_id="tab-A",
            sequence=0,
        )
        assert room._next_seq["tab-A"] == 1

        room._execution_worker_task = MagicMock()
        room._execution_worker_task.done.return_value = True
        room._kernel_manager = MagicMock(
            remove_restart_callback=MagicMock(side_effect=Exception("not registered"))
        )

        await room.disconnect_kernel()

        assert room._next_seq == {}
