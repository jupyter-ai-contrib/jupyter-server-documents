"""
Tests for YRoomManager._should_free_room() — the GC decision logic.

The GC periodically checks each room and frees it if _should_free_room()
returns True. For notebook rooms, the decision depends on:

  1. The room must be inactive (no recent activity) AND empty (no WebSocket clients).
  2. The kernel execution_state must be safe to free: "idle", "dead", or None.

A None execution_state occurs when no kernel has ever reported status for
the notebook — e.g. the notebook was opened without starting a kernel, or
the kernel was shut down externally. In all these cases, there's no active
computation to protect, so freeing is safe.

Non-notebook rooms (text files, etc.) skip the execution_state check entirely
and only require inactive_and_empty.
"""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch

from jupyter_server_documents.rooms.yroom_manager import YRoomManager


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
