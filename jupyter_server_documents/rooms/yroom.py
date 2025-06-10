from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING, cast
from logging import Logger
import asyncio
from ..websockets import YjsClientGroup

import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
from jupyter_server_documents.ydocs import ydocs as jupyter_ydoc_classes
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_events import EventLogger
from tornado.websocket import WebSocketHandler
from .yroom_file_api import YRoomFileAPI
from .yroom_events_api import YRoomEventsAPI

if TYPE_CHECKING:
    from typing import Literal, Tuple, Any
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from pycrdt import TransactionEvent

class YRoom:
    """A Room to manage all client connection to one notebook file"""

    log: Logger
    """The `logging.Logger` instance used by this room to log."""

    room_id: str
    """
    The ID of the room. This is a composite ID following the format:

    room_id := "{file_format}:{file_type}:{file_id}"
    """

    file_api: YRoomFileAPI | None
    """
    The `YRoomFileAPI` instance for this room. This is set to `None` only
    if `self.room_id == "JupyterLab:globalAwareness"`.

    The file API provides `load_ydoc_content()` for loading the YDoc content
    from the `ContentsManager`, accepts & handles save requests via
    `file_api.schedule_save()`, and automatically watches the file for
    out-of-band changes.
    """

    events_api: YRoomEventsAPI | None
    """
    A `YRoomEventsAPI` instance for this room that provides methods for emitting
    events through the `jupyter_events.EventLogger` singleton. This is set to
    `None` only if `self.room_id == "JupyterLab:globalAwareness"`.
    """

    _jupyter_ydoc: YBaseDoc | None
    """JupyterYDoc"""

    _ydoc: pycrdt.Doc
    """Ydoc"""
    _awareness: pycrdt.Awareness
    """Ydoc awareness object"""
    _loop: asyncio.AbstractEventLoop
    """Event loop"""
    _client_group: YjsClientGroup
    """Client group to manage synced and desynced clients"""
    _message_queue: asyncio.Queue[Tuple[str, bytes] | None]
    """
    A per-room message queue that stores new messages from clients to process
    them in order. If a tuple `(client_id, message)` is enqueued, the message is
    queued for processing. If `None` is enqueued, the processing of the message
    queue is halted.

    The `self._process_message_queue()` background task can be halted by running
    `self._message_queue.put_nowait(None)`.
    """
    _awareness_subscription: pycrdt.Subscription
    """Subscription to awareness changes."""
    _ydoc_subscription: pycrdt.Subscription
    """Subscription to YDoc changes."""

    _on_stop: callable[[], Any] | None
    """
    Callback to run after stopping, provided in the constructor.
    """

    _fileid_manager: BaseFileIdManager
    _contents_manager: AsyncContentsManager | ContentsManager


    def __init__(
        self,
        *,
        room_id: str,
        log: Logger,
        loop: asyncio.AbstractEventLoop,
        fileid_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
        on_stop: callable[[], Any] | None = None,
        event_logger: EventLogger
    ):
        # Bind instance attributes
        self.room_id = room_id
        self.log = log
        self._loop = loop
        self._fileid_manager = fileid_manager
        self._contents_manager = contents_manager
        self._on_stop = on_stop

        # Initialize YjsClientGroup, YDoc, YAwareness, JupyterYDoc
        self._client_group = YjsClientGroup(room_id=room_id, log=self.log, loop=self._loop)
        self._ydoc = pycrdt.Doc()
        self._awareness = pycrdt.Awareness(ydoc=self._ydoc)

        # If this room is providing global awareness, set unused optional
        # attributes to `None`.
        if self.room_id == "JupyterLab:globalAwareness":
            self.file_api = None
            self._jupyter_ydoc = None
            self.events_api = None
        else:
            # Otherwise, initialize optional attributes for document rooms
            # Initialize JupyterYDoc
            self._jupyter_ydoc = self._init_jupyter_ydoc()

            # Initialize YRoomFileAPI, start loading content
            self.file_api = YRoomFileAPI(
                room_id=self.room_id,
                jupyter_ydoc=self._jupyter_ydoc,
                log=self.log,
                loop=self._loop,
                fileid_manager=self._fileid_manager,
                contents_manager=self._contents_manager,
                on_outofband_change=self.reload_ydoc,
                on_outofband_move=self.handle_outofband_move,
                on_inband_deletion=self.handle_inband_deletion
            )
            self.file_api.load_ydoc_content()

            # Attach Jupyter YDoc observer to automatically save on change
            self._jupyter_ydoc.observe(self._on_jupyter_ydoc_update)

            # Initialize YRoomEventsAPI
            self.events_api = YRoomEventsAPI(
                event_logger=event_logger,
                fileid_manager=fileid_manager,
                room_id=self.room_id,
                log=self.log,
            )
        
        # Start observers on `self.ydoc` and `self.awareness` to ensure new
        # updates are always broadcast to all clients.
        self._awareness_subscription = self._awareness.observe(
            self._on_awareness_update
        )
        self._ydoc_subscription = self._ydoc.observe(
            self._on_ydoc_update
        )

        # Initialize message queue and start background task that routes new
        # messages in the message queue to the appropriate handler method.
        self._message_queue = asyncio.Queue()
        self._loop.create_task(self._process_message_queue())

        # Log notification that room is ready
        self.log.info(f"Room '{self.room_id}' initialized.")

        # Emit events if defined
        if self.events_api:
            # Emit 'initialize' event
            self.events_api.emit_room_event("initialize")

            # Emit 'load' event once content is loaded
            assert self.file_api
            async def emit_load_event():
                await self.file_api.ydoc_content_loaded.wait()
                self.events_api.emit_room_event("load")
            self._loop.create_task(emit_load_event())
    

    def _init_jupyter_ydoc(self) -> YBaseDoc:
        """
        Initializes a Jupyter YDoc (instance of `pycrdt.YBaseDoc`). This
        should not be called in global awareness rooms, and requires
        `self._ydoc` and `self._awareness` to be set prior.

        Raises `AssertionError` if the room ID is "JupyterLab:globalAwareness"
        or if either `self._ydoc` or `self._awareness` are not set.
        """
        assert self.room_id != "JupyterLab:globalAwareness"
        assert self._ydoc
        assert self._awareness

        # Get Jupyter YDoc class, defaulting to `YFile` if the file type is
        # unrecognized
        _, file_type, _ = self.room_id.split(":")
        JupyterYDocClass = cast(
            type[YBaseDoc],
            jupyter_ydoc_classes.get(file_type, jupyter_ydoc_classes["file"])
        )

        # Initialize Jupyter YDoc and return it
        jupyter_ydoc = JupyterYDocClass(ydoc=self._ydoc, awareness=self._awareness)
        return jupyter_ydoc


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
        if self.file_api:
            await self.file_api.ydoc_content_loaded.wait()
        if self.room_id == "JupyterLab:globalAwareness":
            message = "There is no Jupyter ydoc for global awareness scenario"
            self.log.error(message)
            raise Exception(message)
        return self._jupyter_ydoc
    

    async def get_ydoc(self):
        """
        Returns a reference to the room's YDoc (`pycrdt.Doc`) after
        waiting for its content to be loaded from the ContentsManager.
        """
        if self.file_api:
            await self.file_api.ydoc_content_loaded.wait()
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

        This task can be halted by calling
        `self._message_queue.put_nowait(None)`.
        """
        # Wait for content to be loaded before processing any messages in the
        # message queue
        if self.file_api:
            await self.file_api.ydoc_content_loaded.wait()

        # Begin processing messages from the message queue
        while True:
            # Wait for next item in the message queue
            queue_item = await self._message_queue.get()

            # If the next item is `None`, break the loop and stop this task
            if queue_item is None:
                break

            # Otherwise, process the new message
            client_id, message = queue_item
        
            # Determine message type & subtype from header
            message_type = message[0]
            sync_message_subtype = "*"
            # message subtypes only exist on sync messages, hence this condition
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
                    f"'{client_id}'. Messages must have one of the following "
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


    def _on_jupyter_ydoc_update(self, updated_key: str, event: Any) -> None:
        """
        This method is an observer on `self._jupyter_ydoc` which saves the file
        whenever the YDoc changes.

        - This observer ignores updates to the 'state' dictionary if they have
        no effect. See `should_ignore_state_update()` documentation for info.

        - This observer is separate from the `pycrdt` observer because we must
        check if the update should be ignored. This requires the `updated_key`
        and `event` arguments exclusive to `jupyter_ydoc` observers, not
        available to `pycrdt` observers.

        - The type of the `event` argument depends on the shared type that
        `updated_key` references. If it references a `pycrdt.Map`, then event
        will always be of type `pycrdt.MapEvent`. Same applies for other shared
        types, like `pycrdt.Array` or `pycrdt.Text`.
        """
        # Do nothing if there is no file API for this room (e.g. global awareness)
        if self.file_api is None:
            return

        # Do nothing if the content is still loading. Clients cannot make
        # updates until the content is loaded, so this safely prevents an extra
        # save upon loading/reloading the YDoc.
        content_loading = not self.file_api.ydoc_content_loaded.is_set()
        if content_loading:
            return

        # Do nothing if the event updates the 'state' dictionary with no effect
        if updated_key == "state":
            # The 'state' key always refers to a `pycrdt.Map` shared type, so
            # event always has type `pycrdt.MapEvent`.
            map_event = cast(pycrdt.MapEvent, event)
            if should_ignore_state_update(map_event):
                return

        # Otherwise, save the file
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
    

    def reload_ydoc(self) -> None:
        """
        Reloads the YDoc from the `ContentsManager`. This method:

        - Is called in response to out-of-band changes.

        - Disconnects all clients with close code 4000.

        - Empties the message queue, as the updates can no longer be applied.

        - Resets `self._ydoc`, `self._awareness`, and `self._jupyter_ydoc`.

        - Resets `self.file_api` to reload the YDoc from the `ContentsManager`.

        This method is deliberately synchronous so it cannot interrupted by
        another coroutine.
        """
        # Do nothing if this is a global awareness room, since the YDoc is never
        # used anyways.
        if self.room_id == "JupyterLab:globalAwareness":
            return

        # Stop the existing `YRoomFileAPI` immediately
        assert self.file_api
        self.file_api.stop()

        # Disconnect all clients with close code 4000.
        # This is a special code defined by our extension, informing each client
        # to purge their existing YDoc & re-connect.
        self.clients.close_all(4000)

        # Empty message queue
        while not self._message_queue.empty():
            self._message_queue.get_nowait()
            self._message_queue.task_done()

        # Remove existing observers
        self._ydoc.unobserve(self._ydoc_subscription)
        self._awareness.unobserve(self._awareness_subscription)
        self._jupyter_ydoc.unobserve()

        # Reset YDoc, YAwareness, JupyterYDoc to empty states
        self._ydoc = pycrdt.Doc()
        self._awareness = pycrdt.Awareness(ydoc=self._ydoc)
        self._jupyter_ydoc = self._init_jupyter_ydoc()

        # Reset `YRoomFileAPI` & reload the document
        self.file_api = YRoomFileAPI(
            room_id=self.room_id,
            jupyter_ydoc=self._jupyter_ydoc,
            log=self.log,
            loop=self._loop,
            fileid_manager=self._fileid_manager,
            contents_manager=self._contents_manager,
            on_outofband_change=self.reload_ydoc,
            on_outofband_move=self.handle_outofband_move,
            on_inband_deletion=self.handle_inband_deletion
        )
        self.file_api.load_ydoc_content()

        # Add observers to new YDoc, YAwareness, and JupyterYDoc instances
        self._awareness_subscription = self._awareness.observe(
            self._on_awareness_update
        )
        self._ydoc_subscription = self._ydoc.observe(
            self._on_ydoc_update
        )
        self._jupyter_ydoc.observe(self._on_jupyter_ydoc_update)

        # Emit 'overwrite' event as the YDoc content has been overwritten
        if self.events_api:
            self.events_api.emit_room_event("overwrite")

        
    def handle_outofband_move(self) -> None:
        """
        Handles an out-of-band move/deletion by stopping the YRoom immediately
        with close code 4001.
        """
        self.stop_immediately(close_code=4001)
    
    
    def handle_inband_deletion(self) -> None:
        """
        Handles an in-band file deletion by stopping the YRoom immediately with
        close code 4002.
        """
        self.stop_immediately(close_code=4002)
    

    def stop_immediately(self, close_code: int) -> None:
        """
        Stops the YRoom immediately, closing all Websockets with the given
        `close_code`. This is similar to `self.stop()` with some key
        differences:
        
        - This does not apply any pending YDoc updates from other clients.
        - This does not save the file before exiting.

        This should be reserved for scenarios where it does not make sense to
        apply pending updates or save the file, e.g. when the file has been
        deleted from disk.
        """
        # Disconnect all clients with given `close_code`
        self.clients.stop(close_code=close_code)

        # Remove all observers
        self._ydoc.unobserve(self._ydoc_subscription)
        self._awareness.unobserve(self._awareness_subscription)

        # Purge the message queue immediately, dropping all queued messages
        while not self._message_queue.empty():
            self._message_queue.get_nowait()
            self._message_queue.task_done()
        
        # Enqueue `None` to stop the `_process_message_queue()` background task
        self._message_queue.put_nowait(None)

        # Stop FileAPI immediately (without saving)
        if self.file_api:
            self.file_api.stop()

        # Finally, run the provided callback (if any) and return
        if self._on_stop:
            self._on_stop()


    async def stop(self) -> None:
        """
        Stops the YRoom gracefully by disconnecting all clients with close code
        1001, applying all pending updates, and saving the YDoc before exiting.
        """
        # First, disconnect all clients by stopping the client group.
        self.clients.stop()
        
        # Remove all observers, as updates no longer need to be broadcast
        self._ydoc.unobserve(self._ydoc_subscription)
        self._awareness.unobserve(self._awareness_subscription)
        if self._jupyter_ydoc:
            self._jupyter_ydoc.unobserve()

        # Finish processing all messages, then enqueue `None` to stop the
        # `_process_message_queue()` background task.
        await self._message_queue.join()
        self._message_queue.put_nowait(None)

        # Stop FileAPI, saving the content before doing so
        if self.file_api:
            await self.file_api.stop_then_save()

        # Finally, run the provided callback (if any) and return
        if self._on_stop:
            self._on_stop()

def should_ignore_state_update(event: pycrdt.MapEvent) -> bool:
    """
    Returns whether an update to the `state` dictionary should be ignored by
    `_on_jupyter_ydoc_update()`. Every Jupyter YDoc includes this dictionary in
    its YDoc.

    This function returns `False` if the update has no effect, i.e. the event
    consists of updating each key to the same value it had originally.

    Motivation: `pycrdt` emits update events on the 'state' key even when they have no
    effect. Without ignoring those updates, saving the file triggers an
    infinite loop of saves, as setting `jupyter_ydoc.dirty = False` always
    emits an update, even if that attribute was already `False`. See PR #50 for
    more info.
    """
    # Iterate through the keys added/updated/deleted by this event. Return
    # `False` immediately if:
    # - a key was updated to a value different from the previous value
    # - a key was added with a value different from the previous value
    for key in event.keys.keys():
        update_info = event.keys[key]
        action = update_info.get('action', None)
        if action == 'update':
            old_value = update_info.get('oldValue', None)
            new_value = update_info.get('newValue', None)
            if old_value != new_value:
                return False
        elif action == "add":
            old_value = event.target.get(key, None)
            new_value = update_info.get('newValue', None)
            if old_value != new_value:
                return False
        
    # Otherwise, return `True`.
    return True
    