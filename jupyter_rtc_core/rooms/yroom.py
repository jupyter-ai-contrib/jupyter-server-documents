from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING, cast
from logging import Logger
import asyncio
from ..websockets import YjsClientGroup

import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
from jupyter_ydoc import ydocs as jupyter_ydoc_classes
from jupyter_ydoc.ybasedoc import YBaseDoc
from tornado.websocket import WebSocketHandler
from .yroom_file_api import YRoomFileAPI

if TYPE_CHECKING:
    from typing import Literal, Tuple, Any
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from pycrdt import TransactionEvent

class YRoom:
    """A Room to manage all client connection to one notebook file"""

    log: Logger
    """Log object"""
    room_id: str
    """
    The ID of the room. This is a composite ID following the format:

    room_id := "{file_type}:{file_format}:{file_id}"
    """

    _jupyter_ydoc: YBaseDoc
    """JupyterYDoc"""
    _ydoc: pycrdt.Doc
    """Ydoc"""
    _awareness: pycrdt.Awareness
    """Ydoc awareness object"""
    _loop: asyncio.AbstractEventLoop
    """Event loop"""
    _client_group: YjsClientGroup
    """Client group to manage synced and desynced clients"""
    _message_queue: asyncio.Queue[Tuple[str, bytes]]
    """A message queue per room to keep websocket messages in order"""
    _awareness_subscription: pycrdt.Subscription
    """Subscription to awareness changes."""
    _ydoc_subscription: pycrdt.Subscription
    """Subscription to YDoc changes."""


    def __init__(
        self,
        *,
        room_id: str,
        log: Logger,
        loop: asyncio.AbstractEventLoop,
        fileid_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
    ):
        # Bind instance attributes
        self.log = log
        self._loop = loop
        self.room_id = room_id

        # Initialize YjsClientGroup, YDoc, YAwareness, JupyterYDoc
        self._client_group = YjsClientGroup(room_id=room_id, log=self.log, loop=self._loop)
        self._ydoc = pycrdt.Doc()
        self._awareness = pycrdt.Awareness(ydoc=self._ydoc)
        _, file_type, _ = self.room_id.split(":")
        JupyterYDocClass = cast(
            type[YBaseDoc],
            jupyter_ydoc_classes.get(file_type, jupyter_ydoc_classes["file"])
        )
        self._jupyter_ydoc = JupyterYDocClass(ydoc=self._ydoc, awareness=self._awareness)

        # Initialize YRoomFileAPI and begin loading content
        self.file_api = YRoomFileAPI(
            room_id=self.room_id,
            jupyter_ydoc=self._jupyter_ydoc,
            log=self.log,
            loop=self._loop,
            fileid_manager=fileid_manager,
            contents_manager=contents_manager
        )
        self.file_api.load_ydoc_content()
        
        # Start observers on `self.ydoc` and `self.awareness` to ensure new
        # updates are broadcast to all clients and saved to disk.
        self._awareness_subscription = self._awareness.observe(
            self._on_awareness_update
        )
        self._ydoc_subscription = self._ydoc.observe(
            self._on_ydoc_update
        )
        self._jupyter_ydoc.observe(self._on_jupyter_ydoc_update)

        # Initialize message queue and start background task that routes new
        # messages in the message queue to the appropriate handler method.
        self._message_queue = asyncio.Queue()
        self._loop.create_task(self._process_message_queue())

        # Log notification that room is ready
        self.log.info(f"Room '{self.room_id}' initialized.")
    

    @property
    def clients(self) -> YjsClientGroup:
        """
        Returns the `YjsClientGroup` for this room, which provides an API for
        managing the set of clients connected to this room.
        """

        return self._client_group


    async def get_jupyter_ydoc(self):
        """
        Returns a reference to the room's JupyterYDoc
        (`jupyter_ydoc.ybasedoc.YBaseDoc`) after waiting for its content to be
        loaded from the ContentsManager.
        """
        await self.file_api.ydoc_content_loaded
        return self._jupyter_ydoc
    

    async def get_ydoc(self):
        """
        Returns a reference to the room's YDoc (`pycrdt.Doc`) after
        waiting for its content to be loaded from the ContentsManager.
        """
        await self.file_api.ydoc_content_loaded
        return self._ydoc

    
    def get_awareness(self):
        """
        Returns a reference to the room's awareness (`pycrdt.Awareness`).
        """
        return self._awareness
    

    def add_message(self, client_id: str, message: bytes) -> None:
        """
        Adds new message to the message queue. Items placed in the message queue
        are handled one-at-a-time.
        """
        self._message_queue.put_nowait((client_id, message))
    

    async def _process_message_queue(self) -> None:
        """
        Async method that only runs when a new message arrives in the message
        queue. This method routes the message to a handler method based on the
        message type & subtype, which are obtained from the first 2 bytes of the
        message.
        """
        # Wait for content to be loaded before processing any messages in the
        # message queue
        await self.file_api.ydoc_content_loaded

        # Begin processing messages from the message queue
        while True:
            try: 
                client_id, message = await self._message_queue.get()
            except asyncio.QueueShutDown:
                break
        
            # Determine message type & subtype from header
            message_type = message[0]
            sync_message_subtype = "*"
            if message_type == YMessageType.SYNC and len(message) >= 2:
                sync_message_subtype = message[1]



            # Determine if message is invalid
            # NOTE: In Python 3.12+, we can drop list(...) call 
            # according to https://docs.python.org/3/library/enum.html#enum.EnumType.__contains__
            invalid_message_type = message_type not in list(YMessageType)
            invalid_sync_message_type = message_type == YMessageType.SYNC and sync_message_subtype not in list(YSyncMessageSubtype)
            invalid_message = invalid_message_type or invalid_sync_message_type

            # Handle invalid messages by logging a warning and ignoring
            if invalid_message:
                self.log.warning(
                    "Ignoring an unrecognized message with header "
                    f"'{message_type},{sync_message_subtype}' from client "
                    "'{client_id}'. Messages must have one of the following "
                    "headers: '0,0' (SyncStep1), '0,1' (SyncStep2), "
                    "'0,2' (SyncUpdate), or '1,*' (AwarenessUpdate)."
                )
            # Handle Awareness messages
            elif message_type == YMessageType.AWARENESS:
                self.log.debug(f"Received AwarenessUpdate from '{client_id}'.")
                self.handle_awareness_update(client_id, message)
                self.log.debug(f"Handled AwarenessUpdate from '{client_id}'.")
            # Handle Sync messages
            elif sync_message_subtype == YSyncMessageSubtype.SYNC_STEP1:
                self.log.info(f"Received SS1 from '{client_id}'.")
                self.handle_sync_step1(client_id, message)
                self.log.info(f"Handled SS1 from '{client_id}'.")
            elif sync_message_subtype == YSyncMessageSubtype.SYNC_STEP2:
                self.log.info(f"Received SS2 from '{client_id}'.")
                self.handle_sync_step2(client_id, message)
                self.log.info(f"Handled SS2 from '{client_id}'.")
            elif sync_message_subtype == YSyncMessageSubtype.SYNC_UPDATE:
                self.log.info(f"Received SyncUpdate from '{client_id}'.")
                self.handle_sync_update(client_id, message)
                self.log.info(f"Handled SyncUpdate from '{client_id}'.")
            
            # Finally, inform the asyncio Queue that the task was complete
            # This is required for `self._message_queue.join()` to unblock once
            # queue is empty in `self.stop()`.
            self._message_queue.task_done()

        self.log.info(
            "Stopped `self._process_message_queue()` background task "
            f"for YRoom '{self.room_id}'."
        )


    def handle_sync_step1(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep1 messages from new clients by:

        - Computing a SyncStep2 reply,
        - Sending the reply to the client over WS, and
        - Sending a new SyncStep1 message immediately after.
        """
        # Mark client as desynced
        new_client = self.clients.get(client_id)
        self.clients.mark_desynced(client_id)

        # Compute SyncStep2 reply
        try:
            message_payload = message[1:]
            sync_step2_message = pycrdt.handle_sync_message(message_payload, self._ydoc)
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
            new_client.websocket.write_message(sync_step2_message, binary=True)
            self.log.info(f"Sent SS2 reply to client '{client_id}'.")
        except Exception as e:
            self.log.error(
                "An exception occurred when writing the SyncStep2 reply "
                f"to new client '{new_client.id}':"
            )
            self.log.exception(e)
            return
        
        self.clients.mark_synced(client_id)
        
        # Send SyncStep1 message
        try:
            assert isinstance(new_client.websocket, WebSocketHandler)
            sync_step1_message = pycrdt.create_sync_message(self._ydoc)
            new_client.websocket.write_message(sync_step1_message, binary=True)
            self.log.info(f"Sent SS1 message to client '{client_id}'.")
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
            pycrdt.handle_sync_message(message_payload, self._ydoc)
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
        clients after this method is called via the `self._on_ydoc_update()`
        observer.
        """
        # If client is desynced and sends a SyncUpdate, that results in a
        # protocol error. Close the WebSocket and return early in this case.
        if self._should_ignore_update(client_id, "SyncUpdate"):
            self.clients.remove(client_id)
            return

        # Apply the SyncUpdate to the YDoc
        try:
            message_payload = message[1:]
            pycrdt.handle_sync_message(message_payload, self._ydoc)
        except Exception as e:
            self.log.error(
                "An exception occurred when applying a SyncUpdate message "
                f"from client '{client_id}':"
            )
            self.log.exception(e)
            return
        

    def _on_ydoc_update(self, event: TransactionEvent) -> None:
        """
        This method is an observer on `self._ydoc` which broadcasts a
        `SyncUpdate` message to all synced clients whenever the YDoc changes.

        The YDoc is saved in the `self._on_jupyter_ydoc_update()` observer.
        """
        update: bytes = event.update
        message = pycrdt.create_update_message(update)
        self._broadcast_message(message, message_type="SyncUpdate")


    def _on_jupyter_ydoc_update(self, updated_key: str, *_) -> None:
        """
        This method is an observer on `self._jupyter_ydoc` which saves the file
        whenever the YDoc changes, unless `updated_key == "state"`.

        The `state` key is used by `jupyter_ydoc` to store temporary data like
        whether a file is 'dirty' (has unsaved changes). This data is not
        persisted, so changes to the `state` key should be ignored. Otherwise,
        an infinite loop of saves will result, as saving sets `dirty = False`.

        This observer is separate because `pycrdt.Doc.observe()` does not pass
        `updated_key` to `self._on_ydoc_update()`.
        """
        if updated_key != "state":
            self.file_api.schedule_save()


    def handle_awareness_update(self, client_id: str, message: bytes) -> None:
        # Apply the AwarenessUpdate message
        try:
            message_payload = pycrdt.read_message(message[1:])
            self._awareness.apply_awareness_update(message_payload, origin=self)
        except Exception as e:
            self.log.error(
                "An exception occurred when applying an AwarenessUpdate "
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

        client = self.clients.get(client_id)
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
        client_count = len(clients)
        if not client_count:
            return

        if message_type == "SyncUpdate":
            self.log.info(
                f"Broadcasting SyncUpdate to all {client_count} synced clients."
            )

        for client in clients:
            try:
                # TODO: remove this assertion once websocket is made required
                assert isinstance(client.websocket, WebSocketHandler)
                client.websocket.write_message(message, binary=True)
            except Exception as e:
                self.log.warning(
                    f"An exception occurred when broadcasting a "
                    f"{message_type} message "
                    f"to client '{client.id}:'"
                )
                self.log.exception(e)
                continue
        
        if message_type == "SyncUpdate":
            self.log.info(
                f"Broadcast of SyncUpdate complete."
            )
                
    def _on_awareness_update(self, type: str, changes: tuple[dict[str, Any], Any]) -> None:
        """
        Observer on `self.awareness` that broadcasts AwarenessUpdate messages to
        all clients on update.

        Arguments:
            type: The change type.
            changes: The awareness changes.
        """
        if type != "update" or changes[1] != "local":
            return
        
        updated_clients = [v for value in changes[0].values() for v in value]
        state = self._awareness.encode_awareness_update(updated_clients)
        message = pycrdt.create_awareness_message(state)
        self._broadcast_message(message, "AwarenessUpdate")
        
    async def stop(self) -> None:
        """
        Stops the YRoom gracefully.
        """
        # First, disconnect all clients by stopping the client group.
        self.clients.stop()
        
        # Remove all observers, as updates no longer need to be broadcast
        self._ydoc.unobserve(self._ydoc_subscription)
        self._awareness.unobserve(self._awareness_subscription)
        self._jupyter_ydoc.unobserve()

        # Finish processing all messages, then stop the queue to end the
        # `_process_message_queue()` background task.
        await self._message_queue.join()
        self._message_queue.shutdown(immediate=True)

        # Finally, stop FileAPI and return. This saves the final content of the
        # JupyterYDoc in the process.
        await self.file_api.stop()
