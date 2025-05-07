from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING
from logging import Logger
import asyncio
from ..websockets import YjsClientGroup

import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
from tornado.websocket import WebSocketHandler

if TYPE_CHECKING:
    from typing import Literal, Tuple

class YRoom:
    ydoc: pycrdt.Doc
    awareness: pycrdt.Awareness
    loop: asyncio.AbstractEventLoop
    log: Logger
    _client_group: YjsClientGroup
    _message_queue: asyncio.Queue[Tuple[str, bytes]]


    def __init__(self, log: Logger, loop: asyncio.AbstractEventLoop):
        # Bind instance attributes
        self.log = log
        self.loop = loop

        # Initialize YDoc, YAwareness, YjsClientGroup, and message queue
        self.ydoc = pycrdt.Doc()
        self.awareness = pycrdt.Awareness(ydoc=self.ydoc)
        self._client_group = YjsClientGroup()
        self._message_queue = asyncio.Queue()

        # Start background task that routes new messages in the message queue
        # to the appropriate handler method.
        self.loop.create_task(self._on_new_message())

        # Start observer on the `ydoc` to ensure new updates are broadcast to
        # all clients and saved to disk.
        self.ydoc.observe(lambda event: self.write_sync_update(event.update))
    

    @property
    def clients(self) -> YjsClientGroup:
        """
        Returns the `YjsClientGroup` for this room, which provides an API for
        managing the set of clients connected to this room.
        """

        return self._client_group
    

    def add_client(self, websocket: WebSocketHandler) -> str:
        """
        Creates a new client from the given Tornado WebSocketHandler and
        adds it to the room. Returns the ID of the new client.
        """

        return self.clients.add(websocket)


    def remove_client(self, client_id: str) -> None:
        """Removes a client from the room, given the client ID."""

        self.clients.remove(client_id)
    

    def add_message(self, client_id: str, message: bytes) -> None:
        """
        Adds new message to the message queue. Items placed in the message queue
        are handled one-at-a-time.
        """
        self._message_queue.put_nowait((client_id, message))
    

    async def _on_new_message(self) -> None:
        """
        Async method that only runs when a new message arrives in the message
        queue. This method routes the message to a handler method based on the
        message type & subtype, which are obtained from the first 2 bytes of the
        message.
        """
        while True:
            try: 
                client_id, message = await self._message_queue.get()
            except asyncio.QueueShutDown:
                break
        
            # Handle Awareness messages
            message_type = message[0]
            if message_type == YMessageType.AWARENESS:
                self.handle_awareness_update(client_id, message[1:])
                continue
            
            # Handle Sync messages
            assert message_type == YMessageType.SYNC
            message_subtype = message[1] if len(message) >= 2 else None
            if message_subtype == YSyncMessageSubtype.SYNC_STEP1:
                self.handle_sync_step1(client_id, message)
                continue
            elif message_subtype == YSyncMessageSubtype.SYNC_STEP2:
                self.log.warning(
                    f"Ignoring a SyncStep2 message from client '{client_id}'. "
                    "The server should not receive SyncStep2 messages."
                )
                continue
            elif message_subtype == YSyncMessageSubtype.SYNC_UPDATE:
                self.handle_sync_update(client_id, message)
                continue
            else:
                self.log.warning(
                    "Ignoring an unrecognized message with header "
                    f"'{message_type},{message_subtype}' from client "
                    "'{client_id}'. Messages must have one of the following "
                    "headers: '0,0' (SyncStep1), '0,2' (SyncUpdate), or "
                    "'1,*' (AwarenessUpdate)."
                )
                continue


    def handle_sync_step1(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep1 messages from new clients by:

        - Computing a SyncStep2 reply,
        - Sending the reply to the client over WS, and
        - Sending a new SyncStep1 message immediately after.
        """
        # Mark client as desynced
        new_client = self.clients.get(client_id, synced_only=False)
        self.clients.mark_desynced(client_id)

        # Compute SyncStep2 reply
        try:
            message_payload = message[1:]
            sync_step2_message = pycrdt.handle_sync_message(message_payload, self.ydoc)
            assert isinstance(sync_step2_message, bytes)
        except Exception as e:
            self.log.error(
                "An exception occurred when computing the SyncStep2 reply "
                f"to new client '{new_client.id}':"
            )
            self.log.exception(e)
            return

        # Write SyncStep2 reply to the client's WebSocket
        # Marks client as synced.
        try:
            # TODO: remove the assert once websocket is made required
            assert isinstance(new_client.websocket, WebSocketHandler)
            new_client.websocket.write_message(sync_step2_message)
            self.clients.mark_synced(client_id)
        except Exception as e:
            self.log.error(
                "An exception occurred when writing the SyncStep2 reply "
                f"to new client '{new_client.id}':"
            )
            self.log.exception(e)
            return
        
        # Send SyncStep1 message
        try:
            assert isinstance(new_client.websocket, WebSocketHandler)
            sync_step1_message = pycrdt.create_sync_message(self.ydoc)
            new_client.websocket.write_message(sync_step1_message)
        except Exception as e:
            self.log.error(
                "An exception occurred when writing a SyncStep1 message "
                f"to newly-synced client '{new_client.id}':"
            )
            self.log.exception(e)


    def handle_sync_step2(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep2 messages from newly-synced clients by applying the
        SyncStep2 message to YDoc.

        A SyncUpdate message will automatically be broadcast to all synced
        clients after this method is called via the `self.write_sync_update()`
        observer.
        """
        try:
            message_payload = message[1:]
            pycrdt.handle_sync_message(message_payload, self.ydoc)
        except Exception as e:
            self.log.error(
                "An exception occurred when applying a SyncStep2 message "
                f"from client '{client_id}':"
            )
            self.log.exception(e)
            return


    def handle_sync_update(self, client_id: str, message: bytes) -> None:
        """
        Handles incoming SyncUpdate messages by applying the update to the YDoc.

        A SyncUpdate message will automatically be broadcast to all synced
        clients after this method is called via the `self.write_sync_update()`
        observer.
        """
        # Ignore the message if client is desynced
        if self._should_ignore_update(client_id, "SyncUpdate"):
            return

        # Apply the SyncUpdate to the YDoc
        try:
            message_payload = message[1:]
            pycrdt.handle_sync_message(message_payload, self.ydoc)
        except Exception as e:
            self.log.error(
                "An exception occurred when applying a SyncUpdate message "
                f"from client '{client_id}':"
            )
            self.log.exception(e)
            return
        
        # Broadcast the SyncUpdate to all other synced clients and save the YDoc
        # to disk.
        self.write_sync_update(message_payload, client_id)


    def write_sync_update(self, message_payload: bytes, client_id: str | None = None) -> None:
        """
        This method is an observer on `self.ydoc` which:

        - Broadcasts a SyncUpdate message payload to all connected clients by
        writing to their respective WebSockets,

        - Persists the contents of the updated YDoc by writing to disk.

        This method can also be called manually.
        """
        # Broadcast the message:
        message = pycrdt.create_update_message(message_payload)
        self._broadcast_message(message, message_type="SyncUpdate")

        # Save the file to disk.
        # TODO: requires YRoomLoader implementation
        return


    def handle_awareness_update(self, client_id: str, message: bytes) -> None:
        # Ignore the message if client is desynced
        if self._should_ignore_update(client_id, "AwarenessUpdate"):
            return

        # Apply the AwarenessUpdate message
        try:
            message_payload = message[1:]
            self.awareness.apply_awareness_update(message_payload, origin=self)
        except Exception as e:
            self.log.error(
                "An exception occurred when applying an AwarenessUpdate"
                f"message from client '{client_id}':"
            )
            self.log.exception(e)
            return

        # Broadcast AwarenessUpdate message to all other synced clients
        self._broadcast_message(message, message_type="AwarenessUpdate")


    def _should_ignore_update(self, client_id: str, message_type: Literal['AwarenessUpdate', 'SyncUpdate']) -> bool:
        """
        Returns whether a handler method should ignore an AwarenessUpdate or
        SyncUpdate message from a client because it is desynced. Automatically
        logs a warning if returning `True`. `message_type` is used to produce
        more readable warnings.
        """

        client = self.clients.get(client_id, synced_only=False)
        if not client.synced:
            self.log.warning(
                f"Ignoring a {message_type} message from client "
                f"'{client_id}' because the client is not synced."
            )
            return True
        
        return False
    

    def _broadcast_message(self, message: bytes, message_type: Literal['AwarenessUpdate', 'SyncUpdate']):
        """
        Broadcasts a given message from a given client to all other clients.
        This method automatically logs warnings when writing to a WebSocket
        fails. `message_type` is used to produce more readable warnings.
        """
        clients = self.clients.get_all()
        for client in clients:
            try:
                # TODO: remove this assertion once websocket is made required
                assert isinstance(client.websocket, WebSocketHandler)
                client.websocket.write_message(message)
            except Exception as e:
                self.log.warning(
                    f"An exception occurred when broadcasting a "
                    f"{message_type} message "
                    f"to client '{client.id}:'"
                )
                self.log.exception(e)

        
    def stop(self) -> None:
        # TODO: requires YRoomLoader implementation
        return

