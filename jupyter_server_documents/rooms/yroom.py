from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING, cast, Any
import asyncio
import uuid
import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
from jupyter_server_documents.ydocs import ydocs as jupyter_ydoc_classes
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_events import EventLogger
from tornado.websocket import WebSocketHandler
from traitlets.config import LoggingConfigurable
import traitlets

from ..websockets import YjsClientGroup
from .yroom_file_api import YRoomFileAPI
from .yroom_events_api import YRoomEventsAPI

if TYPE_CHECKING:
    import logging
    from typing import Callable, Coroutine, Literal, Tuple, Any
    from .yroom_manager import YRoomManager
    from jupyter_server_fileid.manager import BaseFileIdManager  # type: ignore
    from jupyter_server.services.contents.manager import ContentsManager
    from pycrdt import TransactionEvent, Subscription
    from ..outputs.manager import OutputsManager

class YRoom(LoggingConfigurable):
    """
    A collaborative room instance. This class requires two arguments:

    1. `parent: YRoomManager`: a reference to the parent `YRoomManager`.

    2. `room_id: str`: the ID of the room. This takes the format
    "{file_format}:{file_type}:{file_id}".

    This class initializes a YDoc for the file and automatically receives,
    broadcasts, and applies YDoc updates. Websockets can be added to the room
    via `room.clients.add()`. This class automatically saves the content through
    the `ContentsManager`; see `YRoomFileAPI` for more info. 
    """

    room_id = traitlets.Unicode(
        allow_none=False,
        config=False,
        help="ID of the room to provide. This is a required argument."
    )
    """
    ID of the room to provide. This is a required argument.
    """

    file_api_class = traitlets.Type(
        klass=YRoomFileAPI,
        help="The `YRoomFileAPI` class.",
        default_value=YRoomFileAPI,
        config=True,
    )
    """
    Configurable trait that sets the `YRoomFileAPI` class used by each `YRoom`.
    See the `YRoomFileAPI` documentation for more info.
    """

    events_api_class = traitlets.Type(
        klass=YRoomEventsAPI,
        help="The `YRoomEventsAPI` class.",
        default_value=YRoomEventsAPI,
        config=True
    )
    """
    Configurable trait that sets the `YRoomEventsAPI` class used by each `YRoom`.
    See the `YRoomEventsAPI` documentation for more info.
    """

    client_group_class = traitlets.Type(
        klass=YjsClientGroup,
        help="The `YjsClientGroup` class.",
        default_value=YjsClientGroup,
        config=True
    )
    """
    Configurable trait that sets the `YjsClientGroup` class used by each `YRoom`.
    See the `YjsClientGroup` documentation for more info.
    """

    file_api: YRoomFileAPI | None
    """
    The `YRoomFileAPI` instance for this room. See its documentation for more
    info.

    - This is initialized using the class set by the `self.file_api_class`
    configurable trait.
    
    - This is set to `None` if & only if `self.room_id ==
    "JupyterLab:globalAwareness"`.
    """

    events_api: YRoomEventsAPI | None
    """
    A `YRoomEventsAPI` instance for this room. See its documentation for more
    info.
    
    - This is initialized using the class set by the `self.events_api_class`
    configurable trait.

    - This is set to `None` if & only if `self.room_id ==
    "JupyterLab:globalAwareness"`.
    """

    _client_group: YjsClientGroup
    """
    Client group to manage synced and desynced clients.

    - This is initialized using the class set by the `self.client_group_class`
    configurable trait.
    """

    parent: YRoomManager
    """
    The parent `YRoomManager` instance that is initializing & managing this
    class.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    log: logging.Logger
    """
    The `logging.Logger` instance used by this class to log.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    _jupyter_ydoc: YBaseDoc | None
    """
    The `JupyterYDoc` for this room's document. See `get_jupyter_ydoc()`
    documentation for more info.
    """

    _jupyter_ydoc_observers: dict[str, Callable[[str, Any], Any]]
    """
    Dictionary of JupyterYDoc observers added by consumers of this room.

    Added to via `observe_jupyter_ydoc()`. Removed from via
    `unobserve_jupyter_ydoc()`.
    """

    # TODO: define a dataclass for this to ensure values are type-safe
    _on_reset_callbacks: dict[Literal['awareness', 'ydoc', 'jupyter_ydoc'], list[Callable[[Any], Any]]]
    """
    Dictionary that stores all `on_reset` callbacks passed to `get_awareness()`,
    `get_jupyter_ydoc()`, or `get_ydoc()`. These are stored in lists under the
    'awareness', 'ydoc' and 'jupyter_ydoc' keys respectively.
    """

    _ydoc: pycrdt.Doc
    """
    The `YDoc` for this room's document. See `get_ydoc()` documentation for more
    info.
    """

    _awareness: pycrdt.Awareness
    """
    The awareness object for this room. See `pycrdt.Awareness` documentation for
    more info.
    """

    _message_queue: asyncio.Queue[Tuple[str, bytes] | None]
    """
    A per-room message queue that stores new messages from clients to process
    them in order. If a tuple `(client_id, message)` is enqueued, the message is
    queued for processing. If `None` is enqueued, the processing of the message
    queue is halted.

    The `self._process_message_queue()` background task can be halted by running
    `self._message_queue.put_nowait(None)`.
    """

    _awareness_subscription: str
    """Subscription to awareness changes."""

    _ydoc_subscription: Subscription
    """Subscription to YDoc changes."""

    _stopped: bool
    """
    Whether the YRoom is stopped. Set to `True` when `stop()` is called and set
    to `False` when `restart()` is called.
    """

    _updated: bool
    """
    See `self.updated` for more info.
    """

    _save_task: asyncio.Task | None
    """
    The task that is saving the final content of the YDoc to disk before
    stopping. See `self.until_saved` documentation for more info.
    """


    def __init__(self, *args, **kwargs):
        # Forward all arguments to parent class
        super().__init__(*args, **kwargs)

        # Initialize instance attributes
        self._jupyter_ydoc_observers = {}
        self._on_reset_callbacks = {
            "awareness": [],
            "jupyter_ydoc": [],
            "ydoc": [],
        }
        self._stopped = False
        self._updated = False
        self._save_task = None

        # Initialize YjsClientGroup, YDoc, and Awareness
        ClientGroupClass = self.client_group_class
        self._client_group = ClientGroupClass(room_id=self.room_id, log=self.log)
        self._ydoc = self._init_ydoc()
        self._awareness = self._init_awareness(ydoc=self._ydoc)

        # If this room is providing global awareness, set unused optional
        # attributes to `None`.
        if self.room_id == "JupyterLab:globalAwareness":
            self._jupyter_ydoc = None
            self.file_api = None
            self.events_api = None
        else:
            # Otherwise, initialize optional attributes for document rooms.
            # Initialize JupyterYDoc
            self._jupyter_ydoc = self._init_jupyter_ydoc(
                ydoc=self._ydoc,
                awareness=self._awareness
            )

            # Initialize YRoomFileAPI, start loading content
            FileAPIClass = self.file_api_class
            self.file_api = FileAPIClass(
                parent=self,
            )
            self.file_api.load_content_into(self._jupyter_ydoc)

            # Initialize YRoomEventsAPI
            EventsAPIClass = self.events_api_class
            self.events_api = EventsAPIClass(parent=self)
        
        # Initialize message queue and start background task that routes new
        # messages in the message queue to the appropriate handler method.
        self._message_queue = asyncio.Queue()
        asyncio.create_task(self._process_message_queue())

        # Log notification that room is ready
        self.log.info(f"Room '{self.room_id}' initialized.")

        # Emit events if defined
        if self.events_api:
            # Emit 'initialize' event
            self.events_api.emit_room_event("initialize")

            # Emit 'load' event once content is loaded
            assert self.file_api
            async def emit_load_event():
                await self.file_api.until_content_loaded
                self.events_api.emit_room_event("load")
            asyncio.create_task(emit_load_event())
    

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self.parent.fileid_manager
    

    @property
    def contents_manager(self) -> ContentsManager:
        return self.parent.contents_manager
    

    @property
    def event_logger(self) -> EventLogger:
        return self.parent.event_logger
    

    @property
    def outputs_manager(self) -> OutputsManager:
        return self.parent.outputs_manager
    

    def _init_ydoc(self) -> pycrdt.Doc:
        """
        Initializes a YDoc, automatically binding its `_on_ydoc_update()`
        observer to `self._ydoc_subscription`. The observer can be removed via
        `ydoc.unobserve(self._ydoc_subscription)`.
        """
        self._ydoc = pycrdt.Doc()
        self._ydoc_subscription = self._ydoc.observe(
            self._on_ydoc_update
        )
        return self._ydoc
    

    def _init_awareness(self, ydoc: pycrdt.Doc) -> pycrdt.Awareness:
        """
        Initializes an Awareness instance, automatically binding its
        `_on_awareness_update()` observer to `self._awareness_subscription`.
        The observer can be removed via
        `awareness.unobserve(self._awareness_subscription)`.
        """
        self._awareness = pycrdt.Awareness(ydoc=ydoc)
        if self.room_id != "JupyterLab:globalAwareness":
            file_format, file_type, file_id = self.room_id.split(":")
            self._awareness.set_local_state_field("file_id", file_id)
        self._awareness_subscription = self._awareness.observe(
            self._on_awareness_update
        )
        asyncio.create_task(self._awareness.start())
        return self._awareness


    def _init_jupyter_ydoc(self, ydoc: pycrdt.Doc, awareness: pycrdt.Awareness) -> YBaseDoc:
        """
        Initializes a Jupyter YDoc (instance of `pycrdt.YBaseDoc`),
        automatically attaching its `_on_jupyter_ydoc_update()` observer.
        The observer can be removed via `jupyter_ydoc.unobserve()`.

        Raises `AssertionError` if the room ID is "JupyterLab:globalAwareness",
        as a JupyterYDoc is not needed for global awareness rooms.
        """
        assert self.room_id != "JupyterLab:globalAwareness"

        # Get Jupyter YDoc class, defaulting to `YFile` if the file type is
        # unrecognized
        _, file_type, _ = self.room_id.split(":")
        JupyterYDocClass = cast(
            type[YBaseDoc],
            jupyter_ydoc_classes.get(file_type, jupyter_ydoc_classes["file"])
        )

        # Initialize Jupyter YDoc and return it
        self._jupyter_ydoc = JupyterYDocClass(ydoc=ydoc, awareness=awareness)
        self._jupyter_ydoc.observe(self._on_jupyter_ydoc_update)
        return self._jupyter_ydoc

    @property
    def clients(self) -> YjsClientGroup:
        """
        Returns the `YjsClientGroup` for this room, which provides an API for
        managing the set of clients connected to this room.
        """

        return self._client_group


    async def get_jupyter_ydoc(self, on_reset: Callable[[YBaseDoc], Any] | None = None) -> YBaseDoc:
        """
        Returns a reference to the room's Jupyter YDoc
        (`jupyter_ydoc.ybasedoc.YBaseDoc`) after waiting for its content to be
        loaded from the ContentsManager.

        This method also accepts an `on_reset` callback, which should take a
        Jupyter YDoc as an argument. This callback is run with the new Jupyter
        YDoc whenever the YDoc is reset, e.g. in response to an out-of-band
        change.
        """
        if self.room_id == "JupyterLab:globalAwareness":
            message = "There is no Jupyter ydoc for global awareness scenario"
            self.log.error(message)
            raise Exception(message)
        if self._jupyter_ydoc is None:
            raise RuntimeError("Jupyter YDoc is not available")
        if self.file_api:
            await self.file_api.until_content_loaded
        if on_reset:
            self._on_reset_callbacks['jupyter_ydoc'].append(on_reset)
            
        return self._jupyter_ydoc
    

    async def get_ydoc(self, on_reset: Callable[[pycrdt.Doc], Any] | None = None) -> pycrdt.Doc:
        """
        Returns a reference to the room's YDoc (`pycrdt.Doc`) after
        waiting for its content to be loaded from the ContentsManager.

        This method also accepts an `on_reset` callback, which should take a
        YDoc as an argument. This callback is run with the new YDoc object
        whenever the YDoc is reset, e.g. in response to an out-of-band change.
        """
        if self.file_api:
            await self.file_api.until_content_loaded
        if on_reset:
            self._on_reset_callbacks['ydoc'].append(on_reset)
        return self._ydoc

    
    def get_awareness(self, on_reset: Callable[[pycrdt.Awareness], Any] | None = None) -> pycrdt.Awareness:
        """
        Returns a reference to the room's awareness (`pycrdt.Awareness`).

        This method also accepts an `on_reset` callback, which should take an
        Awareness object as an argument. This callback is run with the new
        Awareness object whenever the YDoc is reset, e.g. in response to an
        out-of-band change.
        """
        if on_reset:
            self._on_reset_callbacks['awareness'].append(on_reset)
        return self._awareness
    
    def set_cell_execution_state(self, cell_id: str, execution_state: str) -> None:
        """
        Sets the execution state for a specific cell in the awareness system.
        This provides real-time updates to all connected clients and persists
        while the server is running (survives client reconnections).
        """
        awareness = self.get_awareness()
        if awareness is None:
            return

        local_state = awareness.get_local_state()
        if local_state is not None:
            cell_states = local_state.get("cell_execution_states", {})
        else:
            cell_states = {}

        cell_states[cell_id] = execution_state
        awareness.set_local_state_field("cell_execution_states", cell_states)

    def set_cell_awareness_state(self, cell_id: str, execution_state: str) -> None:
        """
        Alias for set_cell_execution_state for backward compatibility.
        """
        self.set_cell_execution_state(cell_id, execution_state)

    def set_kernel_execution_state(self, execution_state: str) -> None:
        """
        Sets the kernel execution state in awareness.
        This provides real-time updates to all connected clients.
        """
        awareness = self.get_awareness()
        if awareness is not None:
            awareness.set_local_state_field(
                "kernel", {"execution_state": execution_state}
            )

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
            await self.file_api.until_content_loaded

        # Begin processing messages from the message queue
        while True:
            # Wait for next item in the message queue
            queue_item = await self._message_queue.get()

            # If the next item is `None`, break the loop and stop this task
            if queue_item is None:
                break

            # Otherwise, process & handle the new message
            client_id, message = queue_item
            self.handle_message(client_id, message)
            
            # Finally, inform the asyncio Queue that the task was complete
            # This is required for `self._message_queue.join()` to unblock once
            # queue is empty in `self.stop()`.
            self._message_queue.task_done()

        self.log.debug(
            "Stopped `self._process_message_queue()` background task "
            f"for YRoom '{self.room_id}'."
        )
    
    def handle_message(self, client_id: str, message: bytes) -> None:
        """
        Handles all messages from every client received in the message queue by
        calling the appropriate handler based on the message type. This method
        routes the message to one of the following methods:

        - `handle_sync_step1()`
        - `handle_sync_step2()`
        - `handle_sync_update()`
        - `handle_awareness_update()`
        """

        # Determine message type & subtype from header
        message_type = message[0]
        sync_message_subtype = -1 # invalid sentinel value
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
            self.log.debug(f"Received AwarenessUpdate from '{client_id}' for room '{self.room_id}'.")
            self.handle_awareness_update(client_id, message)
            self.log.debug(f"Handled AwarenessUpdate from '{client_id}' for room '{self.room_id}'.")
        # Handle Sync messages
        elif sync_message_subtype == YSyncMessageSubtype.SYNC_STEP1:
            self.handle_sync_step1(client_id, message)
        elif sync_message_subtype == YSyncMessageSubtype.SYNC_STEP2:
            self.handle_sync_step2(client_id, message)
        elif sync_message_subtype == YSyncMessageSubtype.SYNC_UPDATE:
            self.handle_sync_update(client_id, message)


    def handle_sync_step1(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep1 messages from new clients by:

        - Computing a SyncStep2 reply,
        - Sending the reply to the client over WS, and
        - Sending a new SyncStep1 message immediately after.
        - Sending awareness state to the new client.
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
        except Exception as e:
            self.log.error(
                "An exception occurred when writing a SyncStep1 message "
                f"to newly-synced client '{new_client.id}':"
            )
            self.log.exception(e)

        # Send current awareness state to the new client
        try:
            # Get all awareness client IDs and broadcast the current state
            all_client_ids = list(self._awareness._states.keys())
            if all_client_ids:
                awareness_update = self._awareness.encode_awareness_update(all_client_ids)
                awareness_message = pycrdt.create_awareness_message(awareness_update)
                assert isinstance(new_client.websocket, WebSocketHandler)
                new_client.websocket.write_message(awareness_message, binary=True)
        except Exception as e:
            self.log.error(
                f"An exception occurred when sending awareness to "
                f"newly-synced client '{new_client.id}':"
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


    def observe_jupyter_ydoc(self, observer: Callable[[str, Any], Any]) -> str:
        """
        Adds an observer callback to the JupyterYDoc that fires on change.
        The callback should accept 2 arguments:

        1. `updated_key: str`: the key of the shared type that was updated, e.g.
        "cells", "state", or "metadata".

        2. `event: Any`: The `pycrdt` event corresponding to the shared type.
        For example, if "state" refers to a `pycrdt.Map`, `event` will take the
        type `pycrdt.MapEvent`.

        Consumers should use this method instead of calling `observe()` directly
        on the `jupyter_ydoc.YBaseDoc` instance, because JupyterYDocs generally
        only allow for a single observer.

        Returns an `observer_id: str` that can be passed to
        `unobserve_jupyter_ydoc()` to remove the observer.
        """
        observer_id = str(uuid.uuid4())
        self._jupyter_ydoc_observers[observer_id] = observer
        return observer_id
    

    def unobserve_jupyter_ydoc(self, observer_id: str):
        """
        Removes an observer from the JupyterYDoc previously added by
        `observe_jupyter_ydoc()`, given the returned `observer_id`.
        """
        self._jupyter_ydoc_observers.pop(observer_id, None)


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
        if not self.file_api.content_loaded:
            return

        # Do nothing if the event updates the 'state' dictionary with no effect
        if updated_key == "state":
            # The 'state' key always refers to a `pycrdt.Map` shared type, so
            # event always has type `pycrdt.MapEvent`.
            map_event = cast(pycrdt.MapEvent, event)
            if should_ignore_state_update(map_event):
                return
        
        # Otherwise, a change was made.
        # Call all observers added by consumers first.
        for observer in self._jupyter_ydoc_observers.values():
            observer(updated_key, event)

        # Then set `updated=True` and save the file.
        self._updated = True
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
                
    def _on_awareness_update(self, type: str, changes: tuple[dict[str, Any], Any]) -> None:
        """
        Observer on `self.awareness` that broadcasts AwarenessUpdate messages to
        all clients on update.

        Arguments:
            type: The change type.
            changes: The awareness changes.
        """

        self.log.debug(f"awareness update, type={type}, changes={changes}, changes[1]={changes[1]}, meta={self._awareness.meta}, ydoc.clientid={self._ydoc.client_id}, roomId={self.room_id}")
        updated_clients = [v for value in changes[0].values() for v in value]
        self.log.debug(f"awareness update, updated_clients={updated_clients}")
        state = self._awareness.encode_awareness_update(updated_clients)
        message = pycrdt.create_awareness_message(state)
        # !r ensures binary messages show as `b'...'`  instead of being decoded
        # into jargon in log statements.
        # https://docs.python.org/3/library/string.html#format-string-syntax
        self.log.debug(f"awareness update, message={message!r}")
        self._broadcast_message(message, "AwarenessUpdate")
    

    def reload_ydoc(self) -> None:
        """
        Alias for `self.restart(close_code=4000, immediately=True)`.
        
        TODO: Use a designated close code to distinguish YDoc reloads from
        out-of-band changes.
        """
        self.restart(close_code=4000, immediately=True)

        
    def handle_outofband_change(self) -> None:
        """
        Handles an out-of-band change by restarting the YRoom immediately,
        closing all Websockets with close code 4000.

        See `restart()` for more info.
        """
        self.restart(close_code=4000, immediately=True)
    

    def handle_outofband_move(self) -> None:
        """
        Handles an out-of-band move/deletion by stopping the YRoom immediately,
        closing all Websockets with close code 4001.

        See `stop()` for more info.
        """
        self.stop(close_code=4001, immediately=True)
    
    
    def handle_inband_deletion(self) -> None:
        """
        Handles an in-band file deletion by stopping the YRoom immediately,
        closing all Websockets with close code 4002.

        See `stop()` for more info.
        """
        self.stop(close_code=4002, immediately=True)
    

    def stop(self, close_code: int = 1001, immediately: bool = False) -> None:
        """
        Stops the YRoom. This method:
         
        - Disconnects all clients with the given `close_code`,
        defaulting to `1001` (server shutting down) if not given.
        
        - Removes all observers and stops the `_process_message_queue()`
        background task.

        - If `immediately=False` (default), this method will finish applying all
        pending updates in the message queue and save the YDoc before returning.
        Otherwise, if `immediately=True`, this method will drop all pending
        updates and not save the YDoc before returning.

        - Clears the YDoc, Awareness, and JupyterYDoc, freeing their memory to
        the server. This deletes the YDoc history.

        IMPORTANT: If the server is shutting down, the YRoomManager should call
        `await room.until_saved`. See `until_saved` documentation for more info.
        """
        self.log.info(f"Stopping YRoom '{self.room_id}'.")

        # Disconnect all clients with the given close code
        self.clients.stop(close_code=close_code)

        # Remove all observers
        self._ydoc.unobserve(self._ydoc_subscription)
        self._awareness.unobserve(self._awareness_subscription)
        if self._jupyter_ydoc:
            self._jupyter_ydoc.unobserve()
        
        # Empty the message queue based on `immediately` argument
        while not self._message_queue.empty():
            if immediately:
                self._message_queue.get_nowait()
                self._message_queue.task_done()
            else:
                queue_item = self._message_queue.get_nowait()
                if queue_item is not None:
                    client_id, message = queue_item
                    self.handle_message(client_id, message)
                self._message_queue.task_done()
        
        # Stop the `_process_message_queue` task by enqueueing `None`
        self._message_queue.put_nowait(None)
        
        # Return early if the room is not a document room, as no more action is
        # needed.
        if not self.file_api or not self._jupyter_ydoc:
            return

        # Otherwise, stop the file API.
        self.file_api.stop()

        # Clear the YDoc, saving the previous content unless `immediately=True`
        if not immediately:
            prev_jupyter_ydoc = self._jupyter_ydoc
            self._save_task = asyncio.create_task(
                self.file_api.save(prev_jupyter_ydoc)
            )
        self._reset_ydoc()
        self._stopped = True
    

    @property
    def until_saved(self) -> Coroutine[Any, Any, None]:
        """
        Returns an Awaitable that resolves when the save is complete after the
        room was stopped with `immediately=False`.

        If the server is shutting down, this property must be awaited by
        `YRoomManager`. Otherwise, the `ContentsManager` will shut down before
        the final save completes, resulting in an empty file.
        """
        return self._until_saved()
    

    async def _until_saved(self) -> None:
        if self._save_task:
            await self._save_task
    

    def _reset_ydoc(self) -> None:
        """
        Deletes and re-initializes the YDoc, awareness, and JupyterYDoc. This
        frees the memory occupied by their histories.

        This runs all `on_reset` callbacks previously passed to `get_ydoc()`,
        `get_jupyter_ydoc()`, or `get_awareness()`.
        """
        self._ydoc = self._init_ydoc()
        self._awareness = self._init_awareness(ydoc=self._ydoc)
        self._jupyter_ydoc = self._init_jupyter_ydoc(
            ydoc=self._ydoc,
            awareness=self._awareness
        )

        # Run callbacks stored in `self._on_reset_callbacks`.
        objects_by_type = {
            "awareness": self._awareness,
            "jupyter_ydoc": self._jupyter_ydoc,
            "ydoc": self._ydoc,
        }
        for obj_type, obj in objects_by_type.items():
            # This is type-safe, but requires a mypy hint because it cannot
            # infer that `obj_type` only takes 3 values.
            for on_reset in self._on_reset_callbacks[obj_type]: # type: ignore
                try:
                    result = on_reset(obj)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:
                    self.log.exception(f"Exception raised by '{obj_type}' on_reset() callback:")
                    continue
    
    @property
    def stopped(self) -> bool:
        """
        Returns whether the room is stopped.
        """
        return self._stopped
    

    @property
    def updated(self) -> bool:
        """
        Returns whether the room has been updated since the last restart, or
        since initialization if the room was not restarted.

        This initializes to `False` and is set to `True` whenever a meaningful
        update that needs to be saved occurs. This is reset to `False` when
        `restart()` is called.
        """
        return self._updated


    def restart(self, close_code: int = 1001, immediately: bool = False) -> None:
        """
        Restarts the YRoom. This method re-initializes & reloads the YDoc,
        Awareness, and the JupyterYDoc. After this method is called, this
        instance behaves as if it were just initialized.

        If the YRoom was not stopped beforehand, then `self.stop(close_code,
        immediately)` with the given arguments. Otherwise, `close_code` and
        `immediately` are ignored.
        """
        # Stop if not stopped already
        if not self._stopped:
            self.stop(close_code=close_code, immediately=immediately)
        
        # Reset internal state
        self._stopped = False
        self._updated = False

        # Restart client group
        self.clients.restart()

        # Restart `YRoomFileAPI` & reload the document
        if self.file_api is not None and self._jupyter_ydoc is not None:
            self.file_api.restart()
            self.file_api.load_content_into(self._jupyter_ydoc)

        # Restart `_process_message_queue()` task
        asyncio.create_task(self._process_message_queue())

        self.log.info(f"Restarted YRoom '{self.room_id}'.")
    

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
    for key in getattr(event, 'keys', {}).keys():
        update_info = getattr(event, 'keys', {})[key]
        action = update_info.get('action', None)
        if action == 'update':
            old_value = update_info.get('oldValue', None)
            new_value = update_info.get('newValue', None)
            if old_value != new_value:
                return False
        elif action == "add":
            old_value = getattr(event, 'target', {}).get(key, None)
            new_value = update_info.get('newValue', None)
            if old_value != new_value:
                return False
        
    # Otherwise, return `True`.
    return True
    