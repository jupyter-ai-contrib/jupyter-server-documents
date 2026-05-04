from __future__ import annotations
import pytest
from unittest.mock import MagicMock, patch
import pycrdt

from jupyter_server_documents.rooms.yroom_manager import YRoomManager


class FakeAwareness:
    """Minimal awareness mock that returns a configurable local state."""

    def __init__(self, state: dict | None = None):
        self._state = state

    def get_local_state(self):
        return self._state


class FakeRoom:
    """Minimal room mock for testing _should_free_room logic."""

    def __init__(self, room_id: str, inactive_and_empty: bool = True, execution_state=None):
        self.room_id = room_id
        self.inactive_and_empty = inactive_and_empty
        self.inactive = inactive_and_empty
        self.empty = inactive_and_empty
        self._execution_state = execution_state

    def get_awareness(self):
        if self._execution_state is _UNSET:
            return FakeAwareness({})
        return FakeAwareness({"kernel": {"execution_state": self._execution_state}})


_UNSET = object()


@pytest.fixture
def manager():
    """Create a YRoomManager with mocked parent to avoid server dependencies."""
    mock_parent = MagicMock()
    mock_parent.config = {}
    mock_parent.log = MagicMock()
    mock_parent.event_loop = MagicMock()
    mock_parent.contents_manager = MagicMock()

    with patch.object(YRoomManager, '__init__', lambda self, **kwargs: None):
        mgr = YRoomManager.__new__(YRoomManager)
        mgr.show_gc_debug = False
        mgr.log = MagicMock()
    return mgr


class TestShouldFreeNotebookRoom:
    """Tests that _should_free_room handles notebook execution states correctly."""

    def test_idle_allows_free(self, manager):
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="idle")
        assert manager._should_free_room(room) is True

    def test_dead_allows_free(self, manager):
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="dead")
        assert manager._should_free_room(room) is True

    def test_none_allows_free(self, manager):
        """None execution state (kernel culled) should allow freeing."""
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state=None)
        assert manager._should_free_room(room) is True

    def test_missing_kernel_key_allows_free(self, manager):
        """No kernel key in awareness (never started) should allow freeing."""
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state=_UNSET)
        assert manager._should_free_room(room) is True

    def test_busy_blocks_free(self, manager):
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="busy")
        assert manager._should_free_room(room) is False

    def test_starting_blocks_free(self, manager):
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=True, execution_state="starting")
        assert manager._should_free_room(room) is False

    def test_not_inactive_blocks_free(self, manager):
        """Even with idle kernel, active room should not be freed."""
        room = FakeRoom("json:notebook:abc123", inactive_and_empty=False, execution_state="idle")
        assert manager._should_free_room(room) is False

    def test_non_notebook_room_ignores_execution_state(self, manager):
        """Non-notebook rooms only check inactive_and_empty."""
        room = FakeRoom("text:file:abc123", inactive_and_empty=True, execution_state="busy")
        assert manager._should_free_room(room) is True
