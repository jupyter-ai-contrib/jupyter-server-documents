from __future__ import annotations

import pycrdt
from typing import TYPE_CHECKING
from traitlets.config import LoggingConfigurable

if TYPE_CHECKING:
    from .yroom import YRoom
    from ..websockets import YjsClientGroup


class YRoomUpdateChannel(LoggingConfigurable):
    """Broadcast channel for SyncUpdate messages that can be paused and resumed.

    When a client with divergent history syncs, the channel is paused to
    suppress broadcasts while the YDoc source is temporarily cleared. On
    resume, a single batched catchup diff is computed and broadcast to bring
    other clients up to date.
    """

    parent: YRoom

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._paused = False

    @property
    def clients(self) -> YjsClientGroup:
        return self.parent.clients

    def send_update(self, message: bytes) -> None:
        """Broadcast a SyncUpdate message to all synced clients, or discard it
        if paused."""
        if self._paused:
            return
        self._broadcast(message)

    def pause(self) -> None:
        """Suppress broadcasts until resume() is called."""
        self._paused = True

    def resume(self, pre_sync_sv: bytes) -> None:
        """Unpause and broadcast a single batched catchup diff covering all
        mutations since pre_sync_sv.

        Batching avoids a pycrdt offset-encoding bug (#197) where individual
        incremental Text updates after multi-byte characters crash JS yjs
        clients with findIndexSS "Unexpected case".
        """
        self._paused = False
        catchup = self.parent._ydoc.get_update(pre_sync_sv)
        # An empty yjs update is 2 bytes (b"\x00\x00").
        if catchup and len(catchup) > 2:
            self._broadcast(pycrdt.create_update_message(catchup))

    def _broadcast(self, message: bytes) -> None:
        """Send a message to all synced clients."""
        for client in self.clients.get_all():
            try:
                client.websocket.write_message(message, binary=True)
            except Exception as e:
                self.log.warning(
                    f"Failed to broadcast SyncUpdate to client '{client.id}': {e}"
                )
