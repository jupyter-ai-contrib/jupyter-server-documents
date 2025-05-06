from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass
import uuid

if TYPE_CHECKING:
    from tornado.websocket import WebSocketHandler

@dataclass
class YjsClient:
    """Data model that represents all data associated
    with a user connecting to a YDoc through JupyterLab."""

    websocket: WebSocketHandler | None = None
    """
    The Tornado WebSocketHandler handling the WS connection to this
    client.

    TODO: make this required
    """
    
    id: str = str(uuid.uuid4())
    """UUIDv4 string that uniquely identifies this client."""

    synced: bool = False
    """Indicates whether the SS1 + SS2 handshake has been completed."""

class YjsClientGroup:
    """
    Data model that represents a group of clients connected to a room. Provides
    helpful abstractions used by YRoom.
    
    New clients start as desynced. Consumers should call mark_synced() to mark a
    new client as synced once the SS1 + SS2 handshake is complete.
    
    TODO: Automatically removes desynced clients if they do not become synced after
    a certain timeout.
    """
    synced: dict[str, YjsClient]
    desynced: dict[str, YjsClient]
        
    def add(self, websocket: WebSocketHandler) -> str:
        """Adds a pending client to the group. Returns a client ID."""
        return ""
    
    def mark_synced(self, client_id: str) -> None:
        """Marks a client as synced."""
        return
    
    def mark_desynced(self, client_id: str) -> None:
        """Marks a client as desynced."""
        return

    def remove(self, client_id: str) -> None:
        """Removes a client from the group."""
        return
    
    def get(self, client_id: str, synced_only: bool = True) -> YjsClient:
        """
        Gets a client from its ID.
        Set synced_only=False to also get desynced clients.
        """
        return YjsClient()

    def get_others(self, client_id: str, synced_only: bool = True) -> list[YjsClient]:
        """
        Gets all *other* clients given a client ID. Useful for broadcasting
        SyncUpdate messages.
        
        Set synced_only=False to also get pending clients.
        """
        return []
    
    def is_empty(self) -> bool:
        """Returns whether the client group is empty."""
        return False
