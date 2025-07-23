"""Configuration for kernel tests."""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_logger():
    """Create a mock logger for testing."""
    return MagicMock()


@pytest.fixture
def mock_session():
    """Create a mock session for testing."""
    session = MagicMock()
    session.msg_header.return_value = {"msg_id": "test-msg-id"}
    session.msg.return_value = {"test": "message"}
    session.serialize.return_value = ["", "serialized", "msg"]
    session.deserialize.return_value = {"msg_type": "test", "content": b"test"}
    session.unpack.return_value = {"test": "data"}
    session.feed_identities.return_value = ([], [b"test", b"message"])
    return session