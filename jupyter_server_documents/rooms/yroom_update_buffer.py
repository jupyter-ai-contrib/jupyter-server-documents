from __future__ import annotations

from typing import TYPE_CHECKING
from traitlets.config import LoggingConfigurable

if TYPE_CHECKING:
    from .yroom import YRoom
    from ..websockets import YjsClientGroup


class YRoomUpdateBuffer(LoggingConfigurable):
    """
    Broadcasts SyncUpdate messages to connected clients normally, queues them
    when paused, and flushes queued messages when resumed.

    When a client with divergent history syncs, we clear the YDoc before the
    handshake and restore it after. Pausing the buffer prevents other clients
    from seeing a flash of empty content.
    """

    parent: YRoom

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paused = False
        self._queue: list[bytes] = []

    @property
    def clients(self) -> YjsClientGroup:
        return self.parent.clients

    def send_update(self, message: bytes) -> None:
        """Broadcast a SyncUpdate message to all synced clients, or queue it
        if paused."""
        if self._paused:
            self._queue.append(message)
            return
        self._broadcast(message)

    def pause(self) -> None:
        """Start queuing updates instead of broadcasting them."""
        self._paused = True

    def resume(self, catchup_message: bytes | None = None) -> None:
        """Discard queued updates and unpause. If catchup_message is provided,
        broadcast it as a single batched update instead of replaying individual
        queued messages.

        Batching avoids a pycrdt offset encoding bug
        (jupyter-ai-contrib/jupyter-server-documents#197) where individual
        incremental Text updates after multi-byte characters crash JS yjs
        clients with findIndexSS "Unexpected case".
        """
        self._queue = []
        self._paused = False
        if catchup_message is not None:
            self._broadcast(catchup_message)

    def _broadcast(self, message: bytes) -> None:
        """Send a message to all synced clients."""
        for client in self.clients.get_all():
            try:
                client.websocket.write_message(message, binary=True)
            except Exception as e:
                self.log.warning(
                    f"Failed to broadcast SyncUpdate to client '{client.id}': {e}"
                )
