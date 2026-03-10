from __future__ import annotations # see PEP-563 for motivation behind this
from typing import TYPE_CHECKING, cast, Any
import asyncio
import time
import uuid
import pycrdt
from pycrdt import YMessageType, YSyncMessageType as YSyncMessageSubtype
from jupyter_server_documents.ydocs import ydocs as jupyter_ydoc_classes
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_events import EventLogger
from traitlets.config import LoggingConfigurable
import traitlets

from ..websockets import YjsClientGroup
from .yroom_file_api import YRoomFileAPI
from .yroom_events_api import YRoomEventsAPI
from .yroom_update_buffer import YRoomUpdateBuffer

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

    inactivity_timeout = traitlets.Int(
        default_value=60,
        config=True,
        help="Number of seconds of inactivity before a room is considered inactive."
    )
    """
    Number of seconds of inactivity before a room is considered inactive.

    See `YRoom.inactive` for more details on how activity is tracked.
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

    _on_stop_callbacks: list[Callable[[], Any]]
    """
    List that stores all `on_stop` callbacks passed to `get_awareness()`,
    `get_jupyter_ydoc()`, or `get_ydoc()`. These are called when the room is
    stopped.
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

    show_gc_debug: bool
    """
    Whether to show garbage collection debug logs. Set to
    `YRoomManager.show_gc_debug` trait.
    """

    update_buffer: YRoomUpdateBuffer
    """
    Buffer for all SyncUpdate messages. See class docstring for more details.
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
        self._on_stop_callbacks: list[Callable[[], Any]] = []
        self._stopped = False
        self._updated = False
        self._pending_ss2_future: asyncio.Future[bytes] | None = None
        self._pending_ss2_client_id: str | None = None
        self._save_task = None
        self._last_activity = time.monotonic()
        self.show_gc_debug = self.parent.show_gc_debug

        # Initialize YjsClientGroup, YDoc, and Awareness
        ClientGroupClass = self.client_group_class
        self._client_group = ClientGroupClass(room_id=self.room_id, log=self.log)
        self._ydoc = self._init_ydoc()
        self._awareness = self._init_awareness(ydoc=self._ydoc)

        # Initialize YRoomUpdateBuffer
        self.update_buffer = YRoomUpdateBuffer(parent=self)

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

    def _update_activity(self, method_name: str | None = None) -> None:
        """Updates the last activity timestamp to the current time."""
        self._last_activity = time.monotonic()
        if self.show_gc_debug and self.empty:
            source = f"'{method_name}()'" if method_name else "unknown source"
            self.log.error(f"Activity in empty YRoom '{self.room_id}' from {source}.")

    @property
    def inactive(self) -> bool:
        """
        Returns whether this room has been inactive for longer than
        `self.inactivity_timeout`. Activity is recorded when either:

        - A consumer accesses the room via `get_ydoc()`, `get_awareness()`, or
        `get_jupyter_ydoc()`, or

        - A meaningful update is made to the YDoc or Awareness objects (excludes
        no-op state updates).
        """
        return (time.monotonic() - self._last_activity) > self.inactivity_timeout
    
    @property
    def empty(self) -> bool:
        """Returns whether this room has no connected clients."""
        return self.clients.count == 0

    @property
    def inactive_and_empty(self) -> bool:
        """Returns whether this room is inactive and has no connected clients."""
        return self.inactive and self.empty

    @property
    def jupyter_ydoc(self) -> YBaseDoc | None:
        """Sync access to the Jupyter YDoc (may not have content loaded yet)."""
        return self._jupyter_ydoc

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
        if self._stopped:
            self.restart()

        # Raise exception if room does not contain a JupyterYDoc
        if self.room_id == "JupyterLab:globalAwareness":
            message = "There is no Jupyter ydoc for global awareness scenario"
            self.log.error(message)
            raise Exception(message)
        if self._jupyter_ydoc is None:
            raise RuntimeError("Jupyter YDoc is not available")

        # Otherwise, update activity and return the JupyterYDoc once loaded
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
        if self._stopped:
            self.restart()
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
        if self._stopped:
            self.restart()
        if on_reset:
            self._on_reset_callbacks['awareness'].append(on_reset)
        return self._awareness
    
    def set_kernel_execution_state(self, execution_state: str) -> None:
        """
        Sets the kernel execution state in awareness.
        This provides real-time updates to all connected clients.
        """
        if self._stopped:
            self.restart()
        awareness = self.get_awareness()
        if awareness is not None:
            awareness.set_local_state_field(
                "kernel", {"execution_state": execution_state}
            )

    def add_message(self, client_id: str, message: bytes) -> None:
        """
        Adds new message to the message queue. Items placed in the message queue
        are handled one-at-a-time.

        If handle_sync_step1 is awaiting an SS2 reply from a client, the reply
        bypasses the queue and resolves the pending future directly.
        """
        if (
            self._pending_ss2_future is not None
            and not self._pending_ss2_future.done()
            and client_id == self._pending_ss2_client_id
            and len(message) >= 2
            and message[0] == YMessageType.SYNC
            and message[1] == YSyncMessageSubtype.SYNC_STEP2
        ):
            self._pending_ss2_future.set_result(message)
            return

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
            await self.handle_message(client_id, message)
            
            # Finally, inform the asyncio Queue that the task was complete
            # This is required for `self._message_queue.join()` to unblock once
            # queue is empty in `self.stop()`.
            self._message_queue.task_done()

        self.log.debug(
            "Stopped `self._process_message_queue()` background task "
            f"for YRoom '{self.room_id}'."
        )
    
    async def handle_message(self, client_id: str, message: bytes) -> None:
        """
        Handles all messages from every client received in the message queue by
        calling the appropriate handler based on the message type. This method
        routes the message to one of the following methods:

        - `await handle_sync()`: performs a sync handshake initiated by a
        client's SS1 message and returns once the handshake is complete. This
        blocks handling of other messages until the sync handshake is complete.

        - `handle_sync_update()`: immediately applies a document update from a
        synced client.

        - `handle_awareness_update()`: immediately applies an awareness update
        from a synced client.
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
            await self.handle_sync(client_id, message)
        elif sync_message_subtype == YSyncMessageSubtype.SYNC_STEP2:
            self.log.warning("Received SS2 message in message loop, this should never happen.")
            return
        elif sync_message_subtype == YSyncMessageSubtype.SYNC_UPDATE:
            self.handle_sync_update(client_id, message)

    @staticmethod
    def _decode_state_vector(sv: bytes) -> dict[int, int]:
        d = pycrdt.Decoder(sv)
        return {d.read_var_uint(): d.read_var_uint() for _ in range(d.read_var_uint())}

    def _has_divergent_history(self, message_payload: bytes) -> bool:
        """Returns True if the client's state vector contains client IDs
        unknown to the server, indicating a stale client from a previous
        session."""
        d = pycrdt.Decoder(message_payload)
        d.read_var_uint()  # skip subtype
        sv_bytes = d.read_message()
        if sv_bytes is None:
            return False
        client_sv = self._decode_state_vector(sv_bytes)
        if not client_sv:
            return False
        server_sv = self._decode_state_vector(self._ydoc.get_state())
        return bool(set(client_sv) - set(server_sv))

    async def handle_sync(self, client_id: str, ss1_message: bytes) -> None:
        """
        Handles the bidirectional sync handshake initiated upon receiving a
        SyncStep1 message from a new client. Specifically, this method:

        1. Sends a SyncStep2 reply providing server side updates,
        2. Sends a SyncStep1 message requesting client side updates,
        3. Awaits the client's SyncStep2 reply (up to 5s timeout),
        4. Applies the client's SyncStep2 reply.

        If the client has divergent history (stale client from a previous
        session), the server clears the YDoc source before the handshake,
        suppresses broadcasts and saves, then restores the source after the
        handshake completes. This prevents content duplication caused by merging
        two YDocs with the same content but different CRDT histories.
        """
        # Mark client as desynced
        self.clients.mark_desynced(client_id)

        # Check if client has divergent history
        ss1_payload = ss1_message[1:]
        divergent = self._has_divergent_history(ss1_payload)

        # If divergent, pause update broadcasts and file saves then clear the
        # YDoc source to prevent content duplication.
        saved_source = None
        if divergent and self._jupyter_ydoc is not None:
            self.log.warning(
                "Client '%s' has divergent history in room '%s'. Clearing YDoc source before handshake.",
                client_id,
                self.room_id
            )
            self.update_buffer.pause()
            if self.file_api is not None:
                self.file_api._reloading_content = True
            # reset JupyterYDoc source
            saved_source = self._jupyter_ydoc.source
            _, file_type, _ = self.room_id.split(":")
            JupyterYDocClass = cast(
                type[YBaseDoc],
                jupyter_ydoc_classes.get(file_type, jupyter_ydoc_classes["file"])
            )
            empty_jupyter_ydoc = JupyterYDocClass()
            self._jupyter_ydoc.source = empty_jupyter_ydoc.source

        # Initialize future that resolves when an SS2 reply is received.
        loop = asyncio.get_running_loop()
        self._pending_ss2_future = loop.create_future()
        self._pending_ss2_client_id = client_id

        # Core handshake logic.
        # If handshake fails at any point, cut the WebSocket connection.
        self.log.info("Initiating handshake with client '%s' in room '%s'.", client_id, self.room_id)
        handshake_failed = False
        try:
            self.handle_sync_step1(client_id, ss1_message)
            ss2_message = await asyncio.wait_for(self._pending_ss2_future, timeout=5.0)
            self.handle_sync_step2(client_id, ss2_message)
            self.log.info("Completed handshake with client '%s' in room '%s'.", client_id, self.room_id)
        except asyncio.TimeoutError:
            self.log.warning(
                "Timed out waiting for SyncStep2 reply from client '%s' in room '%s'.",
                client_id,
                self.room_id
            )
            handshake_failed = True
        except Exception:
            self.log.exception("Exception raised during sync handshake with client '%s' in room '%s':", client_id, self.room_id)
            handshake_failed = True

        # Restore the YDoc source, flush all document updates queued in the
        # update_buffer, and resume saving, regardless of whether the handshake
        # succeeded.
        if saved_source is not None and self._jupyter_ydoc is not None:
            self._jupyter_ydoc.source = saved_source
            self.log.info("Restored YDoc source.")
        self.update_buffer.resume()
        if self.file_api is not None:
            self.file_api._reloading_content = False
        
        # Clear instance state
        self._pending_ss2_future = None
        self._pending_ss2_client_id = None

        # Cut the connection.
        if handshake_failed:
            self.log.error("Disconnecting client '%s' due to failed sync handshake in room '%s'.", client_id, self.room_id)
            self.clients.remove(client_id)

    def handle_sync_step1(self, client_id: str, message: bytes) -> None:
        """
        Handles SyncStep1 messages from new clients by:

        - Computing and sending a SyncStep2 reply,
        - Marking the client as synced (ready to receive server updates),
        - Sending a new SyncStep1 message immediately after.
        - Sending awareness state to the new client.

        Should re-raise all exceptions so they are caught by `handle_sync()`.
        """
        new_client = self.clients.get(client_id)
        message_payload = message[1:]

        # Compute and send SyncStep2 reply
        try:
            sync_step2_message = pycrdt.handle_sync_message(message_payload, self._ydoc)
            assert isinstance(sync_step2_message, bytes)
            new_client.websocket.write_message(sync_step2_message, binary=True)
            # Mark client as synced immediately after sending SS2. This means
            # that client has latest copy of server's state and is ready to
            # receive updates to the server.
            self.clients.mark_synced(client_id)
        except Exception as e:
            self.log.exception(
                "An exception occurred when computing/sending the SyncStep2 reply "
                f"to new client '{new_client.id}':"
            )
            raise

        # Send SyncStep1 message to client
        try:
            sync_step1_message = pycrdt.create_sync_message(self._ydoc)
            new_client.websocket.write_message(sync_step1_message, binary=True)
        except Exception as e:
            self.log.exception(
                "An exception occurred when writing a SyncStep1 message "
                f"to newly-synced client '{new_client.id}':"
            )
            raise

        # Send current awareness state to the new client
        try:
            # Get all awareness client IDs and broadcast the current state
            all_client_ids = list(self._awareness._states.keys())
            if all_client_ids:
                awareness_update = self._awareness.encode_awareness_update(all_client_ids)
                awareness_message = pycrdt.create_awareness_message(awareness_update)
                new_client.websocket.write_message(awareness_message, binary=True)
        except Exception as e:
            self.log.error(
                f"An exception occurred when sending awareness to "
                f"newly-synced client '{new_client.id}':"
            )
            self.log.exception(e)

    def handle_sync_step2(self, client_id: str, message: bytes) -> None:
        """
        Applies a SyncStep2 message from a client to the YDoc.

        Should re-raise all exceptions so they are caught by `handle_sync()`.
        """
        try:
            message_payload = message[1:]
            pycrdt.handle_sync_message(message_payload, self._ydoc)
        except Exception as e:
            self.log.exception(
                "An exception occurred when applying a SyncStep2 message "
                f"from client '{client_id}':"
            )
            raise

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


    def _on_ydoc_update(self, event: TransactionEvent) -> None:
        """
        This method is an observer on `self._ydoc` which broadcasts a
        `SyncUpdate` message to all synced clients whenever the YDoc changes.

        The YDoc is saved in the `self._on_jupyter_ydoc_update()` observer.
        """
        self._update_activity("_on_ydoc_update")
        update: bytes = event.update
        message = pycrdt.create_update_message(update)
        self.update_buffer.send_update(message)


    def add_stop_callback(self, callback: Callable[[], Any]) -> None:
        """
        Registers a callback to be called when the room is stopped (but not
        when restarting). The callback takes no arguments.
        """
        self._on_stop_callbacks.append(callback)

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

        # Do nothing if an in-place reload is in progress. The update was
        # triggered by reading a new version of the file from disk, so saving
        # it back would cause an infinite reload loop via last_modified checks.
        if self.file_api.reloading_content:
            return

        # Do nothing if the event updates the 'state' dictionary with no effect
        if updated_key == "state":
            # The 'state' key always refers to a `pycrdt.Map` shared type, so
            # event always has type `pycrdt.MapEvent`.
            map_event = cast(pycrdt.MapEvent, event)
            if should_ignore_state_update(map_event):
                return
        
        # Otherwise, a change was made.
        self._update_activity("_on_jupyter_ydoc_update")
        # Call all observers added by consumers first.
        for observer in self._jupyter_ydoc_observers.values():
            observer(updated_key, event)

        # Then set `updated=True` and save the file.
        self._updated = True
        self.file_api.schedule_save()
    

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
                client.websocket.write_message(message, binary=True)
            except Exception as e:
                self.log.warning(
                    f"An exception occurred when broadcasting a "
                    f"{message_type} message "
                    f"to client '{client.id}:'"
                )
                self.log.exception(e)
                continue
                
    def _on_awareness_update(self, topic: str, changes: tuple[dict[str, Any], Any]) -> None:
        """
        Observer on `self.awareness` that broadcasts AwarenessUpdate messages to
        all clients on update.

        Arguments:
            topic: The change topic ("change" or "update").
                See: `pycrdt._awareness.Awareness._emit()`
            changes: A tuple of (dict with "added", "updated", "removed" client
                ID lists, origin).
        """
        # Only update activity on "change" events, which indicate actual state
        # differences (added/removed/updated). "update" events fire on every
        # mutation including clock-only renewals, which would keep the room
        # alive indefinitely.
        if topic == "change":
            self._update_activity("_on_awareness_update")
        self.log.debug(f"awareness update, topic={topic}, changes={changes}, changes[1]={changes[1]}, meta={self._awareness.meta}, ydoc.clientid={self._ydoc.client_id}, roomId={self.room_id}")
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
    

    def stop(self, close_code: int = 1001, immediately: bool = False, restarting: bool = False) -> None:
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
        if self._stopped:
            return
        self.log.info(f"Stopping YRoom '{self.room_id}'.")

        # Disconnect all clients with the given close code
        self.clients.stop(close_code=close_code)
        
        # Stop awareness heartbeat
        asyncio.create_task(self._awareness.stop())

        # Remove all observers
        try:
            self._ydoc.unobserve(self._ydoc_subscription)
        except ValueError:
            # Continue if YDoc was already unobserved
            pass
        try:
            self._awareness.unobserve(self._awareness_subscription)
        except KeyError:
            # Continue if Awareness was already unobserved
            pass
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
                    # Call sync handlers directly instead of async
                    # handle_message(). SyncStep1 is skipped because clients
                    # are already disconnected and a handshake cannot complete.
                    msg_type = message[0]
                    if msg_type == YMessageType.SYNC and len(message) >= 2 and message[1] == YSyncMessageSubtype.SYNC_UPDATE:
                        self.handle_sync_update(client_id, message)
                    elif msg_type == YMessageType.AWARENESS:
                        self.handle_awareness_update(client_id, message)
                self._message_queue.task_done()
        
        # Stop the `_process_message_queue` task by enqueueing `None`
        self._message_queue.put_nowait(None)
        
        # If this room is a document room, stop the file API and save the
        # previous content if `immediately=False`.
        if self.file_api and self._jupyter_ydoc:
            self.file_api.stop()
            if not immediately:
                prev_jupyter_ydoc = self._jupyter_ydoc
                self._save_task = asyncio.create_task(
                    self.file_api.save(prev_jupyter_ydoc)
                )

        # Fire `on_stop` callbacks (skip if restarting)
        if not restarting:
            for on_stop in self._on_stop_callbacks:
                try:
                    result = on_stop()
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:
                    self.log.exception("Exception raised by on_stop() callback:")
                    continue

        self._stopped = True
        self.log.info(f"Stopped YRoom '{self.room_id}'.")
    

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
        self._update_activity("restart")

        # Stop if not stopped already
        if not self._stopped:
            self.stop(close_code=close_code, immediately=immediately, restarting=True)

        # Re-add to YRoomManager if this room was freed
        self.parent.add_room(self)

        # Reset internal state
        self._stopped = False
        self._updated = False

        # Re-attach observers
        self._reset_ydoc()
        
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
    