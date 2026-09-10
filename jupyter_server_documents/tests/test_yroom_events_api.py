from unittest.mock import MagicMock
import pytest
from traitlets.config import LoggingConfigurable

from ..rooms.yroom_events_api import YRoomEventsAPI
from ..events import JSD_AWARENESS_EVENT_URI


class MockYRoom(LoggingConfigurable):
    room_id = "text:file:test-file-id"

    def __init__(self, event_logger, **kwargs):
        super().__init__(**kwargs)
        self._event_logger = event_logger

    @property
    def event_logger(self):
        return self._event_logger


@pytest.fixture
def mock_event_logger():
    return MagicMock()


@pytest.fixture
def events_api(mock_event_logger):
    yroom = MockYRoom(event_logger=mock_event_logger)
    return YRoomEventsAPI(parent=yroom)


class TestEmitAwarenessEvent:
    def test_join_emits_with_correct_schema(self, events_api, mock_event_logger):
        events_api.emit_awareness_event("alice", "join")

        mock_event_logger.emit.assert_called_once_with(
            schema_id=JSD_AWARENESS_EVENT_URI,
            data={
                "level": "INFO",
                "roomid": "text:file:test-file-id",
                "username": "alice",
                "action": "join",
            },
        )

    def test_leave_emits_with_correct_schema(self, events_api, mock_event_logger):
        events_api.emit_awareness_event("bob", "leave")

        mock_event_logger.emit.assert_called_once_with(
            schema_id=JSD_AWARENESS_EVENT_URI,
            data={
                "level": "INFO",
                "roomid": "text:file:test-file-id",
                "username": "bob",
                "action": "leave",
            },
        )

    def test_custom_level_is_forwarded(self, events_api, mock_event_logger):
        events_api.emit_awareness_event("alice", "join", level="DEBUG")

        _, kwargs = mock_event_logger.emit.call_args
        assert kwargs["data"]["level"] == "DEBUG"

    def test_exception_is_caught_and_not_raised(self, events_api, mock_event_logger):
        mock_event_logger.emit.side_effect = RuntimeError("emit failed")

        # Should not raise
        events_api.emit_awareness_event("alice", "join")
