from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING
from logging import Logger
import asyncio
from ..websockets import YjsClientGroup

import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype

if TYPE_CHECKING:
    from typing import Literal, Tuple
    import tornado.websocket

class YRoom:
    ydoc: pycrdt.Doc
    awareness: pycrdt.Awareness
    loop: asyncio.AbstractEventLoop
    log: Logger
    _client_group: YjsClientGroup
    _message_queue: asyncio.Queue[Tuple[str, bytes]]

    def __init__(self, log: Logger, loop: asyncio.AbstractEventLoop):
        self.ydoc = pycrdt.Doc()
        self.awareness = pycrdt.Awareness(ydoc=self.ydoc)
        self.log = log
        self.loop = loop
        self._client_group = YjsClientGroup()
        self._message_queue = asyncio.Queue()

        # start listening to the message queue
        self.loop.create_task(self._on_new_message())
    
    @property
    def clients(self) -> YjsClientGroup:
        return self._client_group
    
    def add_client(self, websocket: tornado.websocket.WebSocketHandler) -> str:
        """Calls self.clients.add(), returns a client ID."""
        return self.clients.add(websocket)

    def remove_client(self, client_id: str) -> None:
        """Calls self.clients.remove()."""
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
        
            message_type = message[0]
            # Handle Awareness messages
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
                    f"Ignoring a SyncStep2 message from client '{client_id}'. The server should not receive SyncStep2 messages."
                )
                continue
            elif message_subtype == YSyncMessageSubtype.SYNC_UPDATE:
                self.handle_sync_update(client_id, message)
                continue
            else:
                self.log.warning(
                    f"Ignoring an unrecognized message with header '{message_type},{message_subtype}' from client '{client_id}'." \
                    "Messages must have one of the following headers: '0,0' (SyncStep1), '0,2' (SyncUpdate), or '1,*' (AwarenessUpdate)."
                )
                continue

    def handle_sync_step1(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep1 messages from new clients by computing a SyncStep2
        message and replying over WebSockets.
        """
        # mark client as non-synced
        new_client = self.clients.get(client_id, synced_only=False)
        self.clients.mark_desynced(client_id)

        try:
            message_payload = message[1:]
            sync_step2_message = pycrdt.handle_sync_message(message_payload, self.ydoc)
            assert isinstance(sync_step2_message, bytes)
        except Exception as e:
            self.log.error(f"An exception occurred when computing the SyncStep2 reply to new client '{new_client.id}':")
            self.log.exception(e)
            return

        try:
            # TODO: remove the assert once websocket is made required
            assert isinstance(new_client.websocket, tornado.websocket.WebSocketHandler)
            new_client.websocket.write_message(sync_step2_message)
            
            # mark the new client as synced
            self.clients.mark_synced(client_id)
        except Exception as e:
            self.log.error(f"An exception occurred when writing the SyncStep2 reply to new client '{new_client.id}':")
            self.log.exception(e)
            return


    def handle_sync_update(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncUpdate messages from new clients by applying the update to
        the YDoc, broadcasting the update to all other clients, and saving the
        YDoc to disk.
        """
        client = self.clients.get(client_id, synced_only=False)
        if not client.synced:
            self.log.warning(f"Received a SyncUpdate message from client '{client_id}', but the client is not synced. Ignoring this message.")
            return

        # Apply the SyncUpdate to the YDoc
        try:
            message_payload = message[1:]
            pycrdt.handle_sync_message(message_payload, self.ydoc)
        except Exception as e:
            self.log.error(f"An exception occurred when applying a SyncUpdate message from client '{client_id}':")
            self.log.exception(e)
            return
        
        # Broadcast the SyncUpdate to all other synced clients
        self._broadcast_message_from(client_id, message, message_type="SyncUpdate")
        
        # Finally, save the file to disk: TODO.
        return

    def handle_awareness_update(self, client_id: str, message: bytes) -> None:
        # Apply the AwarenessUpdate message
        message_payload = message[1:]
        self.awareness.apply_awareness_update(message_payload, origin=self)

        # Broadcast AwarenessUpdate message to all other synced clients
        self._broadcast_message_from(client_id, message, message_type="AwarenessUpdate")
    
    def _broadcast_message_from(self, client_id: str, message: bytes, message_type: Literal['AwarenessUpdate', 'SyncUpdate']):
        other_clients = self.clients.get_others(client_id)
        for other_client in other_clients:
            try:
                # TODO: remove this assertion
                assert isinstance(other_client.websocket, tornado.websocket.WebSocketHandler)
                other_client.websocket.write_message(message)
            except Exception as e:
                self.log.warning(f"An exception occurred when broadcasting a {message_type} message from client '{client_id}' to client '{other_client.id}:'")
                self.log.exception(e)

        
    def stop(self) -> None:
        # TODO
        return