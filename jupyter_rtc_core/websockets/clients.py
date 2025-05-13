"""
WIP.

This file just contains interfaces to be filled out later.
"""

from __future__ import annotations
from datetime import timedelta, timezone, datetime
from logging import Logger
from typing import TYPE_CHECKING
import uuid
import asyncio

if TYPE_CHECKING:
    from tornado.websocket import WebSocketHandler
class YjsClient:
    """Data model that represents all data associated
    with a user connecting to a YDoc through JupyterLab."""

    websocket: WebSocketHandler | None
    """The Tornado WebSocketHandler handling the WS connection to this client."""
    id: str
    """UUIDv4 string that uniquely identifies this client."""
    last_modified: datetime
    """Indicates the last modified time when synced state is modified"""

    _synced: bool

    def __init__(self, websocket):
        self.websocket: WebSocketHandler | None = websocket
        self.id: str = str(uuid.uuid4())
        self._synced: bool = False
        self.last_modified = datetime.now(timezone.utc)
        
    @property
    def synced(self):
        """
        Indicates whether the initial Client SS1 + Server SS2 handshake has been
        completed.
        """
        return self._synced

    @synced.setter
    def synced(self, v: bool):
        self._synced = v
        self.last_modified = datetime.now(timezone.utc)

class YjsClientGroup:
    """
    Data model that represents a group of clients connected to a room. Provides
    helpful abstractions used by YRoom.
    
    New clients start as desynced. Consumers should call mark_synced() to mark a
    new client as synced once the SS1 + SS2 handshake is complete.
    
    Automatically removes desynced clients if they do not become synced after
    a certain timeout.
    """
    room_id: str
    """Room Id for associated YRoom"""
    synced: dict[str, YjsClient]
    """A dict of client_id and synced YjsClient mapping"""
    desynced: dict[str, YjsClient]
    """A dict of client_id and desynced YjsClient mapping"""
    log: Logger
    """Log object"""
    loop: asyncio.AbstractEventLoop
    """Event loop"""
    _poll_interval_seconds: int
    """The poll time interval used while auto removing desynced clients"""
    desynced_timeout_seconds: int
    """The max time period in seconds that a desynced client does not become synced before get auto removed from desynced dict"""
    
    def __init__(self, *, room_id: str, log: Logger, loop: asyncio.AbstractEventLoop, poll_interval_seconds: int = 60, desynced_timeout_seconds: int = 120):
        self.room_id = room_id
        self.synced: dict[str, YjsClient] = {}
        self.desynced: dict[str, YjsClient] = {}
        self.log = log
        self.loop = loop
        self.loop.create_task(self._clean_desynced())
        self._poll_interval_seconds = poll_interval_seconds
        self.desynced_timeout_seconds = desynced_timeout_seconds
        
    def add(self, websocket: WebSocketHandler) -> str:
        """Adds a pending client to the group. Returns a client ID."""
        client = YjsClient(websocket)
        self.desynced[client.id] = client
        return client.id
    
    def mark_synced(self, client_id: str) -> None:
        """Marks a client as synced."""
        if client := self.desynced.pop(client_id, None):
            client.synced = True
            self.synced[client.id] = client
    
    def mark_desynced(self, client_id: str) -> None:
        """Marks a client as desynced."""
        if client := self.synced.pop(client_id, None):
            client.synced = False
            self.desynced[client.id] = client

    def remove(self, client_id: str) -> None:
        """Removes a client from the group."""
        if client := self.desynced.pop(client_id, None) is None: 
            client = self.synced.pop(client_id, None)
        if client and client.websocket and client.websocket.ws_connection: 
            try:
                client.websocket.close()
            except Exception as e:
                self.log.exception(f"An exception occurred when remove client '{client_id}' for room '{self.room_id}': {e}")  
    
    def get(self, client_id: str) -> YjsClient:
        """
        Gets a client from its ID.
        """
        if client_id in self.desynced: 
            client = self.desynced[client_id]
        if client_id in self.synced:
            client = self.synced[client_id]
        if client.websocket and client.websocket.ws_connection:
            return client
        error_message = f"The client_id '{client_id}' is not found in client group in room '{self.room_id}'"
        self.log.error(error_message)
        raise Exception(error_message)

    def get_all(self, synced_only: bool = True) -> list[YjsClient]:
        """
        Returns a list of all synced clients.
        Set synced_only=False to also get desynced clients.
        """
        if synced_only: 
            return list(client for client in self.synced.values() if client.websocket and client.websocket.ws_connection)
        return list(client for client in self.desynced.values() if client.websocket and client.websocket.ws_connection)
    
    def is_empty(self) -> bool:
        """Returns whether the client group is empty."""
        return len(self.synced) == 0 and len(self.desynced) == 0
    
    async def _clean_desynced(self) -> None:
        while True: 
            try:
                await asyncio.sleep(self._poll_interval_seconds)
                for (client_id, client) in list(self.desynced.items()): 
                    if client.last_modified <= datetime.now(timezone.utc) - timedelta(seconds=self.desynced_timeout_seconds):
                        self.log.warning(f"Remove client '{client_id}' for room '{self.room_id}' since client does not become synced after {self.desynced_timeout_seconds} seconds.")  
                        self.remove(client_id)
                for (client_id, client) in list(self.synced.items()): 
                    if client.websocket is None or client.websocket.ws_connection is None:
                        self.log.warning(f"Remove client '{client_id}' for room '{self.room_id}' since client does not become synced after {self.desynced_timeout_seconds} seconds.")  
                        self.remove(client_id)
            except asyncio.CancelledError:
                break
            
