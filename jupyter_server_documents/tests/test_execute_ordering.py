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
    room._next_seq = {}
    room._seq_generation = {}
    room._seq_reset_reason = {}
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

def make_seq_room():
    """A room whose single cell's hash matches ``run()``'s default."""
    room = make_room()
    ydoc, _ = make_ydoc("x = 1")
    room.get_jupyter_ydoc = AsyncMock(return_value=ydoc)
    return room


async def run(room, sequence, client_id="tab-A", source_hash=_source_hash("x = 1")):
    await room.execute_cell(
        "cell-1", source_hash=source_hash, client_id=client_id, sequence=sequence
    )


async def settle():
    """Let pending tasks reach their sequence wait."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def prep_disconnect(room):
    """Stub out the kernel pieces disconnect_kernel() touches."""
    room._execution_worker_task = MagicMock()
    room._execution_worker_task.done.return_value = True
    room._kernel_manager = MagicMock(
        remove_restart_callback=MagicMock(side_effect=Exception("not registered"))
    )


class TestSequenceOrdering:
    """execute_cells enqueues in strict sequence order per client_id."""

    @pytest.mark.asyncio
    async def test_in_order_arrivals_advance_next_seq(self):
        room = make_seq_room()
        for seq in range(3):
            await run(room, seq)

        assert room._next_seq["tab-A"] == 3
        assert room._execution_queue.qsize() == 3

    @pytest.mark.asyncio
    async def test_out_of_order_buffered_until_predecessor_arrives(self):
        room = make_seq_room()

        task_b = asyncio.create_task(run(room, 1))
        await settle()
        assert room._execution_queue.empty(), "seq=1 must be blocked waiting for seq=0"

        await run(room, 0)
        await task_b

        assert room._execution_queue.qsize() == 2
        assert room._next_seq["tab-A"] == 2

    @pytest.mark.asyncio
    async def test_sequence_below_next_seq_raises(self):
        room = make_seq_room()
        await run(room, 0)
        await run(room, 1)

        with pytest.raises(SequenceOutOfRangeError):
            await run(room, 1)

    @pytest.mark.asyncio
    async def test_sequence_zero_after_high_seq_resets_state(self):
        room = make_seq_room()
        for seq in range(3):
            await run(room, seq)

        await run(room, 0)

        assert room._next_seq["tab-A"] == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("trigger", ["sequence_zero", "disconnect"])
    async def test_reset_abandons_pending_waiter(self, trigger):
        """A seq=0 reset or a kernel disconnect abandons a pending waiter."""
        room = make_seq_room()
        await run(room, 0)

        waiter = asyncio.create_task(run(room, 5))
        await settle()
        assert not waiter.done()

        if trigger == "sequence_zero":
            await run(room, 0)
        else:
            prep_disconnect(room)
            await room.disconnect_kernel()
            assert room._next_seq == {}

        with pytest.raises(SessionResetError) as exc_info:
            await waiter
        assert exc_info.value.reason == "reset"

    @pytest.mark.asyncio
    async def test_lost_predecessor_times_out(self):
        """A waiter whose predecessor never arrives gives up after
        ``execute_sequence_timeout``."""
        room = make_seq_room()
        room.execute_sequence_timeout = 0.05

        with pytest.raises(SessionResetError, match="timed out") as exc_info:
            await run(room, 3)
        assert exc_info.value.reason == "timeout"

    @pytest.mark.asyncio
    async def test_timeout_releases_peers_behind_the_same_gap(self):
        """Peers stuck behind a lost predecessor fail with the first timeout,
        not their own, and report it as a timeout."""
        room = make_seq_room()
        room.execute_sequence_timeout = 0.2

        first = asyncio.create_task(run(room, 7))
        await asyncio.sleep(0.1)
        peers = [asyncio.create_task(run(room, seq)) for seq in (8, 9)]

        # The peers' own deadlines are ~0.3s out; the first one's is ~0.2s.
        results = await asyncio.wait_for(
            asyncio.gather(first, *peers, return_exceptions=True), timeout=0.25
        )

        assert all(isinstance(r, SessionResetError) for r in results)
        assert [r.reason for r in results] == ["timeout"] * 3
        assert room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_advances_even_on_source_mismatch(self):
        """A failed request still advances the sequence — the slot is used."""
        room = make_seq_room()

        with pytest.raises(SourceMismatchError):
            await run(room, 0, source_hash="does-not-match")

        assert room._next_seq["tab-A"] == 1
        await run(room, 1)
        assert not room._execution_queue.empty()

    @pytest.mark.asyncio
    async def test_independent_clients_dont_block_each_other(self):
        room = make_seq_room()

        waiter_a = asyncio.create_task(run(room, 1))
        await settle()
        assert not waiter_a.done()

        await run(room, 0, client_id="tab-B")
        assert room._next_seq["tab-B"] == 1

        await run(room, 0)
        await waiter_a
        assert room._next_seq["tab-A"] == 2


class TestSequencePreservedAcrossRestart:
    """Kernel restart-in-place preserves per-client sequence counters.

    The browser's per-``docKey`` counter isn't reset on restart (same
    ``kernel_id``), so the server's ``_next_seq`` must survive too —
    otherwise the next request (with sequence N > 0) waits for predecessors
    that will never arrive.
    """

    @pytest.mark.asyncio
    async def test_disconnect_kernel_reset_false_preserves_next_seq(self):
        room = make_seq_room()
        for seq in range(3):
            await run(room, seq)

        prep_disconnect(room)
        await room.disconnect_kernel(reset_sequences=False)

        assert room._next_seq["tab-A"] == 3
