"""
Tests for YRoomManager._should_free_room() — the GC decision logic.

The GC periodically checks each room and frees it if _should_free_room()
returns True. For notebook rooms, the decision depends on:

  1. The room must be inactive (no recent activity) AND empty (no WebSocket clients).
  2. The kernel execution_state must be safe to free: "idle", "dead", "unknown", or None.
  3. For YNotebookRoom instances, no server-side execution may be queued or
     running on a kernel that can still finish it
     (YRoomManager._room_has_live_executions).

A None execution_state occurs when no kernel has ever reported status for
the notebook — e.g. the notebook was opened without starting a kernel, or
the kernel was shut down externally. In all these cases, there's no active
computation to protect, so freeing is safe.

Non-notebook rooms (text files, etc.) skip the execution_state check entirely
and only require inactive_and_empty.

The FakeRoom tests below cover conditions 1 and 2. Condition 3 is covered at
the end of this file with a real YNotebookRoom in a real YRoomManager (the
`make_yroom` fixture), since it reads the room's execution queue and worker.
"""
from __future__ import annotations
import asyncio
import json
import uuid
from typing import TYPE_CHECKING
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jupyter_server_documents.rooms.ynotebook_room import _source_hash
from jupyter_server_documents.rooms.yroom_manager import YRoomManager

if TYPE_CHECKING:
    from ...conftest import MakeYRoom


# Sentinel used to simulate awareness state where the "kernel" key is
# entirely absent (as opposed to present with execution_state=None).
_UNSET = object()


class FakeAwareness:
    """Returns a configurable local state dict, mimicking pycrdt.Awareness."""

    def __init__(self, state: dict | None = None):
        self._state = state

    def get_local_state(self):
        return self._state


class FakeRoom:
    """
    Minimal stand-in for YRoom that exposes only what _should_free_room reads:
    - room_id: determines whether this is a notebook room ("json:notebook:...")
    - inactive_and_empty: whether the room has no clients and has been idle
    - get_awareness(): returns awareness with a configurable execution_state
    """

    def __init__(self, room_id: str, inactive_and_empty: bool = True, execution_state=None):
        self.room_id = room_id
        self.inactive_and_empty = inactive_and_empty
        self.inactive = inactive_and_empty
        self.empty = inactive_and_empty
        self._execution_state = execution_state

    def get_awareness(self):
        # _UNSET simulates awareness where "kernel" key was never written
        if self._execution_state is _UNSET:
            return FakeAwareness({})
        return FakeAwareness({"kernel": {"execution_state": self._execution_state}})


@pytest.fixture
def manager():
    """
    Create a YRoomManager without initializing a real server.

    We bypass __init__ because it requires a full ServerDocsApp parent with
    contents_manager, event_loop, etc. Since _should_free_room only reads
    self.show_gc_debug and self.log, we set those directly.
    """
    with patch.object(YRoomManager, '__init__', lambda self, **kwargs: None):
        mgr = YRoomManager.__new__(YRoomManager)
        mgr.show_gc_debug = False
        mgr.log = MagicMock()
    return mgr


class TestShouldFreeNotebookRoom:
    """
    Verifies _should_free_room for notebook rooms (room_id starts with
    "json:notebook:"). These rooms have an additional execution_state guard
    beyond the inactive_and_empty check.
    """

    # --- States that SHOULD allow freeing ---

    def test_idle_allows_free(self, manager):
        # Kernel finished executing and is sitting idle — safe to free.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="idle")
        assert manager._should_free_room(room) is True

    def test_dead_allows_free(self, manager):
        # Kernel process has terminated — nothing left to protect.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="dead")
        assert manager._should_free_room(room) is True

    def test_none_allows_free(self, manager):
        # execution_state is None when the kernel was shut down externally
        # (e.g. culled for inactivity) and no final status was written to
        # awareness. The room is orphaned — safe to free.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state=None)
        assert manager._should_free_room(room) is True

    def test_unknown_string_allows_free(self, manager):
        # "unknown" is an explicit execution state that may be set when the
        # kernel status cannot be determined. Same semantics as None — no
        # active computation to protect.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="unknown")
        assert manager._should_free_room(room) is True

    def test_missing_kernel_key_allows_free(self, manager):
        # The "kernel" key was never written to awareness — this happens when
        # a notebook is opened but no kernel is ever started. Since there's
        # no kernel, there's no computation to protect.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state=_UNSET)
        assert manager._should_free_room(room) is True

    # --- States that SHOULD block freeing ---

    def test_busy_blocks_free(self, manager):
        # Kernel is actively executing — freeing would discard live state.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="busy")
        assert manager._should_free_room(room) is False

    def test_starting_blocks_free(self, manager):
        # Kernel is starting up — freeing could race with initialization.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="starting")
        assert manager._should_free_room(room) is False

    def test_not_inactive_blocks_free(self, manager):
        # Even with an idle kernel, if the room still has recent activity or
        # connected clients, we must not free it — someone may reconnect.
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=False, execution_state="idle")
        assert manager._should_free_room(room) is False

    # --- Non-notebook rooms ---

    def test_non_notebook_room_ignores_execution_state(self, manager):
        # Text/file rooms don't have kernels. The execution_state is irrelevant;
        # only inactive_and_empty matters. Here we set execution_state="busy"
        # to prove it's ignored for non-notebook rooms.
        room = FakeRoom("text:file:abc123", inactive_and_empty=True, execution_state="busy")
        assert manager._should_free_room(room) is True


# --- Condition 3: queued or running server-side executions ---


@pytest.fixture
def attach_stub_kernel():
    """Bind a room to a stub kernel manager registered in the server's real
    MultiKernelManager, so the GC's kernel-presence check sees a running
    kernel without a kernel process. Deregistered on teardown.

    Writes to the private `_kernels` dict because MultiKernelManager has no
    public way to register an existing kernel manager."""
    registered = []

    def _attach(room, kernel_id: str = "kernel-1"):
        km = MagicMock()
        km.kernel_id = kernel_id
        room._kernel_manager = km
        mkm = room.parent.parent.serverapp.kernel_manager
        mkm._kernels[kernel_id] = km
        registered.append((mkm, kernel_id))
        return km

    yield _attach

    for mkm, kernel_id in registered:
        mkm._kernels.pop(kernel_id, None)


async def make_inactive_notebook_room(make_yroom: MakeYRoom):
    """Return a real notebook room, in a real manager, that is already
    inactive and empty — i.e. one the GC would free."""
    room = await make_yroom(file_type="notebook", inactivity_timeout=0)
    await asyncio.sleep(0.05)
    assert room.inactive_and_empty
    return room


def hold_item(room):
    """Put the worker in the state it is in while running a cell: the item
    is off the queue and the kernel start it was sent to is recorded."""
    room._execution_queue = asyncio.Queue()
    room._worker_busy = True
    room._worker_kernel_ready = room._kernel_manager.ready


class TestNotebookRoomExecutionState:
    """
    Pins the two room properties condition 3 reads. Queue depth alone is not
    enough: the worker takes an item off the queue before running it, so for
    the whole duration of a long cell the queue is empty while the worker is
    busy.
    """

    @pytest.mark.asyncio
    async def test_has_active_executions_counts_queued_and_running(self, make_yroom: MakeYRoom):
        room = await make_yroom(file_type="notebook")

        # No queue yet, then an empty one.
        assert room.has_active_executions is False
        room._execution_queue = asyncio.Queue()
        assert room.has_active_executions is False

        # Something queued.
        room._execution_queue.put_nowait(object())
        assert room.has_active_executions is True

        # The worker took it off the queue and is running it: the queue is
        # empty, but the execution is still active.
        room._execution_queue.get_nowait()
        room._worker_busy = True
        assert room.has_active_executions is True

        room._worker_busy = False
        assert room.has_active_executions is False

    @pytest.mark.asyncio
    async def test_worker_is_stranded_once_the_kernel_is_restarted(self, make_yroom: MakeYRoom):
        room = await make_yroom(file_type="notebook")
        room._kernel_manager = MagicMock()
        assert room.worker_is_stranded is False

        hold_item(room)
        assert room.worker_is_stranded is False

        # A kernel manager replaces `ready` whenever it starts or shuts down
        # a kernel, as a restart does.
        room._kernel_manager.ready = object()
        assert room.worker_is_stranded is True

        room._worker_busy = False
        assert room.worker_is_stranded is False


class TestShouldFreeNotebookRoomWithActiveExecutions:
    """
    Condition 3 through the real _should_free_room, on a real YNotebookRoom
    that satisfies conditions 1 and 2 (no clients, no awareness["kernel"]
    written, and `inactivity_timeout=0` except in the real-kernel test).
    """

    @pytest.mark.asyncio
    async def test_blocks_queued_and_running_executions(self, make_yroom: MakeYRoom, attach_stub_kernel):
        room = await make_inactive_notebook_room(make_yroom)
        attach_stub_kernel(room)
        manager = room.parent

        # Control: inactive, empty and idle — freeable.
        assert manager._should_free_room(room) is True

        # A queued execution must block freeing.
        room._execution_queue = asyncio.Queue()
        room._execution_queue.put_nowait(object())
        assert manager._should_free_room(room) is False

        # So must an execution the worker has already taken off the queue.
        room._execution_queue.get_nowait()
        hold_item(room)
        assert manager._should_free_room(room) is False

        room._worker_busy = False
        assert manager._should_free_room(room) is True

    @pytest.mark.asyncio
    async def test_does_not_pin_a_room_whose_kernel_is_gone(self, make_yroom: MakeYRoom, attach_stub_kernel):
        room = await make_inactive_notebook_room(make_yroom)
        manager = room.parent

        # Work queued on a room that never connected a kernel.
        room._execution_queue = asyncio.Queue()
        room._execution_queue.put_nowait(object())
        assert manager._should_free_room(room) is True

        attach_stub_kernel(room, "kernel-1")
        hold_item(room)
        assert manager._should_free_room(room) is False

        # The kernel is shut down without disconnect_kernel() running: the
        # server's MultiKernelManager drops it, but the room still holds its
        # kernel manager, so only that membership shows the kernel is gone.
        mkm = manager.parent.serverapp.kernel_manager
        mkm.remove_kernel("kernel-1")
        assert "kernel-1" not in mkm
        assert manager._should_free_room(room) is True

    @pytest.mark.asyncio
    async def test_does_not_pin_a_room_whose_kernel_was_restarted(self, make_yroom: MakeYRoom, attach_stub_kernel):
        room = await make_inactive_notebook_room(make_yroom)
        km = attach_stub_kernel(room)
        manager = room.parent

        hold_item(room)
        assert manager._should_free_room(room) is False

        # Restarted without the room being told (through the kernels API, or
        # automatically after a crash): same kernel manager and kernel id,
        # still registered, but a new `ready` future.
        km.ready = object()
        assert "kernel-1" in manager.parent.serverapp.kernel_manager
        assert manager._should_free_room(room) is True

    @pytest.mark.asyncio
    async def test_room_stays_unfreeable_while_worker_runs_a_cell(self, make_yroom: MakeYRoom, attach_stub_kernel):
        """End to end through the real execution worker.

        While a cell is executing, the queue is empty (the worker holds the
        item) and nothing else touches the room, so an inactivity-timed-out
        room with no clients looks freeable to every other signal the GC has.
        It must still not be freed until the worker is done.

        The kernel round-trip itself is mocked at the _run_item boundary, so
        this pins the worker's bookkeeping rather than which kernel-client
        call _run_item makes.
        """
        room = await make_inactive_notebook_room(make_yroom)
        attach_stub_kernel(room)
        manager = room.parent

        # Enough kernel plumbing for execute_cell() to enqueue.
        room._kernel_client = MagicMock()
        room._shell_confirmed = True
        mock_cell = {"id": "cell-1", "source": "1+1", "cell_type": "code", "outputs": []}
        mock_ydoc = MagicMock()
        mock_ydoc.ycells = [mock_cell]
        room.get_jupyter_ydoc = AsyncMock(return_value=mock_ydoc)

        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_run_item(item):
            started.set()
            await release.wait()
            item.ycell["execution_state"] = "idle"

        room._run_item = fake_run_item
        room._execution_queue = asyncio.Queue()
        room._execution_worker_task = asyncio.create_task(room._execution_worker())

        try:
            await room.execute_cell("cell-1", source_hash=_source_hash("1+1"))
            await asyncio.wait_for(started.wait(), timeout=2.0)

            # The worker has dequeued the item and is waiting on the kernel.
            assert room._execution_queue.empty()
            await asyncio.sleep(0.05)
            assert room.inactive_and_empty
            assert manager._should_free_room(room) is False
            assert room.has_active_executions is True
            assert room.worker_is_stranded is False

            # Let the cell finish; once the worker is done the room is
            # freeable again.
            release.set()
            await asyncio.wait_for(room._execution_queue.join(), timeout=2.0)
            assert mock_cell["execution_state"] == "idle"
            assert manager._should_free_room(room) is True
            assert room.has_active_executions is False
        finally:
            room._execution_worker_task.cancel()
            await asyncio.gather(room._execution_worker_task, return_exceptions=True)

    @pytest.mark.timeout(60)
    async def test_restart_through_the_kernels_api_does_not_pin_the_room(self, jp_fetch, jp_serverapp, tmp_path):
        """With a real kernel: restart it through the kernels API while a
        cell runs. That path does not fire the restart callbacks registered
        by connect_kernel(), so unless something else relays the restart to
        the room, its worker is left waiting on a reply from the old kernel.

        This end-to-end test lives here rather than in tests/executions/ to
        keep condition 3 in one file. It finds the room through the
        YRoomManager rather than the session manager.
        """
        cell_id = "sleep-cell"
        source = "import time; time.sleep(30)"
        nb_name = f"test_{uuid.uuid4().hex[:8]}.ipynb"
        (tmp_path / nb_name).write_text(json.dumps({
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
            "cells": [{
                "cell_type": "code", "id": cell_id, "source": source,
                "metadata": {}, "outputs": [], "execution_count": None,
            }],
        }))

        r = await jp_fetch(
            "api", "sessions", method="POST",
            body=json.dumps({"path": nb_name, "name": nb_name, "type": "notebook", "kernel": {"name": "python3"}}),
            headers={"Content-Type": "application/json"},
        )
        session = json.loads(r.body)
        session_id, kernel_id = session["id"], session["kernel"]["id"]
        try:
            manager = jp_serverapp.web_app.settings["yroom_manager"]
            file_id_manager = jp_serverapp.web_app.settings["file_id_manager"]
            document_id = f"json:notebook:{file_id_manager.index(nb_name)}"
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 20
            room = None
            while room is None:
                try:
                    candidate = manager.get_room(document_id)
                    _, cell = (await candidate.get_jupyter_ydoc()).find_cell(cell_id)
                    if cell is not None:
                        room = candidate
                except Exception:
                    pass
                assert loop.time() < deadline, "room never loaded"
                await asyncio.sleep(0.1)

            r = await jp_fetch(
                "api", "kernels", kernel_id, "execute", method="POST",
                body=json.dumps({"document_id": document_id, "cells": [{"cell_id": cell_id, "source_hash": _source_hash(source)}]}),
                headers={"Content-Type": "application/json"},
            )
            assert r.code == 200
            while not room._worker_busy:
                assert loop.time() < deadline, "the worker never took the cell"
                await asyncio.sleep(0.1)
            # Not needed for the assertions (the worker records `ready` when it
            # takes the item); it only lets the cell start on the old kernel.
            await asyncio.sleep(0.5)
            assert manager._room_has_live_executions(room) is True

            await jp_fetch("api", "kernels", kernel_id, "restart", method="POST", body="{}")

            # Same kernel id, still registered, but the cell's kernel is gone.
            assert kernel_id in manager.kernel_manager
            assert manager._room_has_live_executions(room) is False
        finally:
            await jp_fetch("api", "sessions", session_id, method="DELETE")
