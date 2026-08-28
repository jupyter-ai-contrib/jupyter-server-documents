from __future__ import annotations
import logging

import pytest
from unittest.mock import Mock

from jupyter_server_documents.websockets import YjsClientGroup


@pytest.fixture
def client_group() -> YjsClientGroup:
    return YjsClientGroup(
        room_id="text:file:test-file-id",
        log=logging.getLogger("test_client_group"),
    )


def _mock_websocket() -> Mock:
    """Returns a mock Websocket that appears connected."""
    websocket = Mock()
    websocket.ws_connection = object()
    return websocket


class TestYjsClientGroupGet():
    """
    Tests for `YjsClientGroup.get()`.
    """

    def test_get_returns_new_client(self, client_group: YjsClientGroup):
        """
        Asserts that `get()` returns a newly-added (desynced) client.
        """
        client_id = client_group.add(_mock_websocket())
        client = client_group.get(client_id)
        assert client.id == client_id

    def test_get_returns_synced_client(self, client_group: YjsClientGroup):
        """
        Asserts that `get()` returns a client after it is marked as synced.
        """
        client_id = client_group.add(_mock_websocket())
        client_group.mark_synced(client_id)
        client = client_group.get(client_id)
        assert client.id == client_id

    def test_get_unknown_client_raises_cleanly(self, client_group: YjsClientGroup):
        """
        Asserts that `get()` raises the intended exception when given a client
        ID that is in neither the synced nor the desynced dictionary, instead
        of an `UnboundLocalError` from referencing an unassigned local.

        Regression test for #271: a queued message from a client that has
        already been removed previously raised `UnboundLocalError`.
        """
        with pytest.raises(Exception) as excinfo:
            client_group.get("unknown-client-id")

        assert not isinstance(excinfo.value, UnboundLocalError)
        assert "not found" in str(excinfo.value)

    def test_get_removed_client_raises_cleanly(self, client_group: YjsClientGroup):
        """
        Asserts that `get()` raises the intended exception for a client that
        was previously added and then removed, instead of `UnboundLocalError`.
        """
        client_id = client_group.add(_mock_websocket())
        client_group.remove(client_id)

        with pytest.raises(Exception) as excinfo:
            client_group.get(client_id)

        assert not isinstance(excinfo.value, UnboundLocalError)
        assert "not found" in str(excinfo.value)
