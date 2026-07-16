"""Tests for YjsClientGroup, the per-room client registry.

Regression coverage for #271: a lookup of an unknown client must raise a
proper exception (not UnboundLocalError), so the caller's exception boundary
can skip the offending message instead of poisoning the room's queue.
"""

from __future__ import annotations

import logging

import pytest

from jupyter_server_documents.websockets.clients import YjsClientGroup


class FakeWebSocket:
    """Minimal stand-in for a Tornado WebSocketHandler."""

    def __init__(self, connected: bool = True):
        # `get()` checks both `websocket` and `websocket.ws_connection`.
        self.ws_connection = object() if connected else None
        self.closed = False

    def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = True


@pytest.fixture
def group() -> YjsClientGroup:
    return YjsClientGroup(room_id="test-room", log=logging.getLogger("test"))


def test_get_unknown_client_raises_exception(group: YjsClientGroup):
    """An unknown client_id must raise a proper Exception, not UnboundLocalError."""
    with pytest.raises(Exception) as exc_info:
        group.get("does-not-exist")
    assert "does-not-exist" in str(exc_info.value)
    assert not isinstance(exc_info.value, UnboundLocalError)


def test_get_desynced_client(group: YjsClientGroup):
    """A desynced (newly added) client is returned by get()."""
    client_id = group.add(FakeWebSocket())
    assert group.get(client_id).id == client_id


def test_get_synced_client(group: YjsClientGroup):
    """A synced client is returned by get()."""
    client_id = group.add(FakeWebSocket())
    group.mark_synced(client_id)
    assert group.get(client_id).id == client_id


def test_get_disconnected_client_raises(group: YjsClientGroup):
    """A client whose websocket has no live connection is treated as missing."""
    client_id = group.add(FakeWebSocket(connected=False))
    with pytest.raises(Exception):
        group.get(client_id)
