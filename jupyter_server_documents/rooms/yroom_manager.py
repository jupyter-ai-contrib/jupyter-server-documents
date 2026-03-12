from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING
import asyncio
import gc
import weakref
import traitlets
from traitlets.config import LoggingConfigurable
from jupyter_server_fileid.manager import BaseFileIdManager  # type: ignore

from ..outputs.manager import OutputsManager

if TYPE_CHECKING:
    import logging
    from jupyter_server.extension.application import ExtensionApp
    from jupyter_server.services.contents.manager import ContentsManager
    from jupyter_events import EventLogger

class YRoomManager(LoggingConfigurable):
    """
    A singleton that manages all `YRoom` instances in the server extension. The
    constructor requires only a single argument `parent: ExtensionApp`.

    This manager automatically restarts updated `YRoom` instances if they have
    had no connected clients or active kernel for >10 seconds. This deletes the
    YDoc history to free its memory to the server.
    """

    yroom_class = traitlets.Type(
        klass=YRoom,
        help="The `YRoom` class.",
        default_value=YRoom,
        config=True,
    )
    """
    Configurable trait that sets the `YRoom` class initialized when a client
    opens a collaborative room.
    """

    parent: ExtensionApp
    """
    The parent `ExtensionApp` instance that is initializing this class. This
    should be the `ServerDocsApp` server extension.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    log: logging.Logger
    """
    The `logging.Logger` instance used by this class to log.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    _rooms_by_id: traitlets.Dict[str, YRoom] = traitlets.Dict(default_value={})
    """
    Dictionary of active `YRoom` instances, keyed by room ID. Rooms are never
    deleted from this dictionary.

    TODO: Delete a room if its file was deleted in/out-of-band or moved
    out-of-band. See #116.
    """

    _inactive_rooms = traitlets.Set()
    """
    Set of room IDs (as strings) that were marked inactive on the last iteration
    of `_watch_rooms()`. If a room is inactive and its ID is present in this
    set, then the room should be restarted as it has been inactive for >10
    seconds.
    """

    auto_free_interval = traitlets.Int(default_value=60, config=True)
    """
    Interval in seconds between checks for inactive rooms to free from memory.
    """

    show_gc_debug = traitlets.Bool(default_value=False, config=True)
    """
    If True, logs referrer debug info for rooms that are not garbage collected
    after being freed.
    """

    _auto_free_rooms_task: asyncio.Task

    _freeing_rooms: set[str]
    """Set of room IDs that are in the process of being freed."""

    def __init__(self, *args, **kwargs):
        # Forward all arguments to parent class
        super().__init__(*args, **kwargs)
        self._freeing_rooms = set()

        # Start `self._auto_free_rooms()` as a background task to automatically
        # free rooms from memory
        self._auto_free_rooms_task = asyncio.get_event_loop().create_task(self._auto_free_rooms())


    @property
    def fileid_manager(self) -> BaseFileIdManager:
        if self.parent.serverapp is None:
            raise RuntimeError("ServerApp is not available")
        manager = self.parent.serverapp.web_app.settings.get("file_id_manager", None)
        assert isinstance(manager, BaseFileIdManager)
        return manager
    

    @property
    def contents_manager(self) -> ContentsManager:
        if self.parent.serverapp is None:
            raise RuntimeError("ServerApp is not available")
        return self.parent.serverapp.contents_manager
    

    @property
    def event_logger(self) -> EventLogger:
        if self.parent.serverapp is None:
            raise RuntimeError("ServerApp is not available")
        event_logger = self.parent.serverapp.event_logger
        if event_logger is None:
            raise RuntimeError("Event logger is not available")
        return event_logger
    

    @property
    def outputs_manager(self) -> OutputsManager:
        if not hasattr(self.parent, 'outputs_manager'):
            raise RuntimeError("Outputs manager is not available")
        return self.parent.outputs_manager
    

    def get_room(self, room_id: str) -> YRoom | None:
        """
        Returns the `YRoom` instance for a given room ID. If the instance does
        not exist, this method will initialize one and return it. Otherwise,
        this method returns the instance from its cache.
        """
        # First, ensure the room is not considered inactive.
        self._inactive_rooms.discard(room_id)

        # If room exists, return the room
        yroom = self._rooms_by_id.get(room_id, None)
        if yroom:
            return yroom
        
        # Otherwise, create a new room
        try:
            return self.create_room(room_id)
        except Exception as e:
            self.log.error(
                f"Unable to initialize YRoom '{room_id}'.",
                exc_info=True
            )
            return None
    

    def create_room(self, room_id: str, **room_kwargs) -> YRoom:
        """
        Creates a `YRoom` instance. This method raises an exception if the room
        already exists, so developers should prefer calling `get_room()`.
        """
        if self.has_room(room_id):
            raise Exception(f"Room already exists: '{room_id}'.")

        self.log.info(f"Initializing room '{room_id}'.")
        YRoomClass = self.yroom_class
        yroom = YRoomClass(
            parent=self,
            room_id=room_id,
            **room_kwargs
        )
        self._rooms_by_id[room_id] = yroom
        self._freeing_rooms.discard(room_id)
        return yroom
    

    def has_room(self, room_id: str) -> bool:
        """
        Returns whether a `YRoom` instance with a matching `room_id` already
        exists.
        """
        return room_id in self._rooms_by_id


    async def delete_room(self, room_id: str) -> bool:
        """
        Gracefully deletes a YRoom given a room ID. This stops the YRoom,
        closing all Websockets with close code 1001 (server shutting down),
        applying remaining updates, and saving the final content of the YDoc in
        a background task.

        Returns `True` if the room was deleted successfully. Returns `False` if
        an exception was raised.
        """
        self.log.info(f"Deleting YRoom '{room_id}'.")
        yroom = self._rooms_by_id.get(room_id, None)
        if not yroom:
            self.log.info(f"YRoom '{room_id}' was already deleted.")
            return True
        
        try:
            yroom.stop()
            await yroom.until_saved
            self._rooms_by_id.pop(room_id, None)
            self.log.info(f"Deleted YRoom '{room_id}'.")
            return True
        except Exception as e:
            self.log.exception(
                f"Exception raised when deleting YRoom '{room_id}: "
            )
            return False
    
    
    def list_document_rooms(self) -> list[YRoom]:
        """
        Lists all document rooms, excluding "JupyterLab:globalAwareness".
        """
        return [
            room for room_id, room in self._rooms_by_id.items()
            if room_id != "JupyterLab:globalAwareness"
        ]


    async def _auto_free_rooms(self) -> None:
        """
        Background task that checks all `YRoom` instances on an interval,
        deleting any rooms that should be freed. See
        `_should_cleanup_room()` for more info.

        """
        while True:
            await asyncio.sleep(self.auto_free_interval)

            rooms_to_free = [
                room for room in self.list_document_rooms()
                if self._should_free_room(room)
            ]

            for i in range(len(rooms_to_free)):
                await self._free_room(rooms_to_free[i])
            
            if rooms_to_free:
                if self.show_gc_debug:
                    for room in rooms_to_free:
                        self.log.error(f"Referrers of room '{room.room_id}':")
                        self._log_referrers(room)
                    del room
                rooms_to_free.clear()
                gc.collect()
                

    def _should_free_room(self, room: YRoom) -> bool:
        """
        Returns whether a room should be deleted to free memory.

        - For rooms not providing notebooks: This task stops the room if it
        is inactive and empty (no WebSocket clients connected / connecting).

        - For rooms providing notebooks: This task stops the room if it has is
        inactive, has no connected clients, and its kernel execution status is
        either 'idle' or 'dead'.

        - See `YRoom.inactive` for details on how activity is measured.
        """
        if not room.room_id.startswith("json:notebook:"):
            if self.show_gc_debug:
                self.log.info(f"Should free room '{room.room_id}': {room.inactive_and_empty}")
            return room.inactive_and_empty
        
        awareness = room.get_awareness().get_local_state() or {}
        execution_state = awareness.get("kernel", {}).get("execution_state", None)
        should_free = execution_state in { "idle", "dead" } and room.inactive_and_empty
        if self.show_gc_debug:
            self.log.info(f"Should free notebook room '{room.room_id}': {should_free}")
            if not should_free:
                self.log.info(f"- Execution state: {execution_state}")
                self.log.info(f"- Client count: {room.clients.count}")
                self.log.info(f"- Inactive: {room.inactive}")
        return should_free
    

    async def _free_room(self, room: YRoom) -> None:
        """
        Frees a room from memory by deleting it. This is the same as
        `delete_room()`, but logs when the room is freed.
        """
        self.log.info(f"Freeing room '{room.room_id}'.")

        # Capture room_id as a string so the finalizer callback doesn't
        # hold a strong reference to `room`.
        room_id = room.room_id
        self._freeing_rooms.add(room_id)
        weakref.finalize(
            room,
            self._on_room_freed,
            room_id,
        )
        await self.delete_room(room.room_id)


    def _on_room_freed(self, room_id: str) -> None:
        """Callback fired by weakref.finalize when a room is garbage collected."""
        self.log.info(f"Freed YRoom '{room_id}' from memory.")
        self._freeing_rooms.discard(room_id)


    def was_room_freed(self, room_id: str) -> bool:
        """Returns whether a room has been freed from memory."""
        return room_id not in self._freeing_rooms and room_id not in self._rooms_by_id


    async def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.

        - This method should only be called when the server is shutting down.

        - This method is uniquely async because it waits for each room to finish
        saving its final content. Without waiting, the `ContentsManager` will
        shut down before the saves complete, resulting in empty files.
        """
        
        # First, stop all background tasks
        if self._auto_free_rooms_task:
            self._auto_free_rooms_task.cancel()
            try:
                await self._auto_free_rooms_task
            except asyncio.CancelledError:
                pass

        # Return early if there are no rooms
        room_count = len(self._rooms_by_id)
        if room_count == 0:
            return

        # Otherwise, prepare to delete all rooms
        self.log.info(
            f"Stopping `YRoomManager` and deleting all {room_count} YRooms."
        )
        deletion_tasks = []

        # Delete all rooms concurrently using `delete_then_save()`
        for room_id in self._rooms_by_id:
            deletion_task = asyncio.create_task(
                self.delete_room(room_id)
            )
            deletion_tasks.append(deletion_task)
        
        # Await all deletion tasks in serial. This doesn't harm performance
        # since the tasks were started concurrently.
        failures = 0
        for deletion_task in deletion_tasks:
            result = await deletion_task
            if not result:
                failures += 1

        # Log the aggregate status before returning.
        if failures:
            self.log.error(
                "An exception occurred when stopping `YRoomManager`. "
                "Exceptions were raised when stopping "
                f"({failures}/{room_count}) `YRoom` instances, "
                "which are printed above."
            )
        else:
            self.log.info(
                "Successfully stopped `YRoomManager` and deleted all "
                f"{room_count} YRooms."
            )
        

    def _log_referrers(self, obj: object) -> None:
        """
        Logs all objects holding a reference to `obj`. Used exclusively for
        debugging garbage collection.

        This is disabled by default because it is computationally expensive. Set
        `show_gc_debug = True` to enable these logs.
        """
        for referrer in gc.get_referrers(obj):
            if isinstance(referrer, dict):
                for parent in gc.get_referrers(referrer):
                    if any(
                        getattr(parent, attr, None) is referrer
                        for attr in ('__dict__', '_trait_values')
                    ):
                        self.log.error(f"{type(parent).__name__} @ {id(parent):#x}")
                        break
                else:
                    self.log.error(f"dict: {list(referrer.keys())[:8]}")
            elif hasattr(referrer, 'cr_code'):
                # Coroutine
                label = f"coroutine: {referrer.cr_code.co_qualname}"
                if referrer.cr_frame:
                    locals_ = referrer.cr_frame.f_locals
                    if 'self' in locals_:
                        s = locals_['self']
                        label += f" (self={type(s).__name__} @ {id(s):#x})"
                    label += f" locals={list(locals_.keys())}"
                else:
                    label += " (frame=None, suspended)"
                self.log.error(label)
            elif type(referrer).__name__ == 'frame':
                self.log.error(
                    f"frame: {referrer.f_code.co_qualname} "
                    f"at {referrer.f_code.co_filename}:{referrer.f_lineno} "
                    f"locals={list(referrer.f_locals.keys())}"
                )
            else:
                label = f"{type(referrer).__name__} @ {id(referrer):#x}"
                if callable(referrer) and hasattr(referrer, '__qualname__'):
                    label += f" ({referrer.__qualname__})"
                self.log.error(label)
                # Chase one level deeper for methods/callables/tuples/lists
                if callable(referrer) or isinstance(referrer, (tuple, list)):
                    for r2 in gc.get_referrers(referrer):
                        if r2 is obj:
                            continue
                        r2label = f"  └─ {type(r2).__name__} @ {id(r2):#x}"
                        if hasattr(r2, 'cr_code'):
                            r2label = f"  └─ coroutine: {r2.cr_code.co_qualname}"
                        elif type(r2).__name__ == 'cell':
                            # Find which function owns this closure cell
                            owners = []
                            for owner in gc.get_referrers(r2):
                                if owner is referrer:
                                    continue
                                owners.append(f"{type(owner).__name__}"
                                    + (f" ({owner.__qualname__})" if hasattr(owner, '__qualname__') else f" @ {id(owner):#x}"))
                            r2label = f"  └─ cell @ {id(r2):#x} val={type(r2.cell_contents).__name__ if r2 != type(None) else '?'} owners={owners}"
                        elif callable(r2) and hasattr(r2, '__qualname__'):
                            r2label += f" ({r2.__qualname__})"
                        elif isinstance(r2, dict):
                            r2label = f"  └─ dict: {list(r2.keys())[:8]}"
                        elif isinstance(r2, (tuple, list)):
                            r2label = f"  └─ {type(r2).__name__} len={len(r2)}"
                        self.log.error(r2label)


