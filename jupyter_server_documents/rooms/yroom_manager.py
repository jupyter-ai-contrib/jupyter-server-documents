from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING
import asyncio
from traitlets import Dict, Set, Type
from traitlets.config import LoggingConfigurable

if TYPE_CHECKING:
    import logging
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from jupyter_events import EventLogger

class YRoomManager(LoggingConfigurable):
    """
    A singleton that manages all `YRoom` instances in the server extension.

    This manager automatically restarts updated `YRoom` instances if they have
    had no connected clients or active kernel for >10 seconds. This deletes the
    YDoc history to free its memory to the server.
    """

    yroom_class = Type(
        klass=YRoom,
        help="The `YRoom` class.",
        default_value=YRoom,
        config=True,
    )
    """
    Configurable trait that sets the `YRoom` class initialized when a client
    opens a collaborative room.
    """

    log: logging.Logger
    """
    The `logging.Logger` instance used by this class. This is automatically set
    by the `LoggingConfigurable` parent class; this declaration only hints the
    type for type checkers.
    """

    _rooms_by_id: dict[str, YRoom] = Dict(default_value={})
    """
    Dictionary of active `YRoom` instances, keyed by room ID. Rooms are never
    deleted from this dictionary.

    TODO: Delete a room if its file was deleted in/out-of-band or moved
    out-of-band. See #116.
    """

    _inactive_rooms: set[str] = Set()
    """
    Set of room IDs that were marked inactive on the last iteration of
    `_watch_rooms()`. If a room is inactive and its ID is present in this set,
    then the room should be restarted as it has been inactive for >10 seconds.
    """

    _get_fileid_manager: callable[[], BaseFileIdManager]
    contents_manager: AsyncContentsManager | ContentsManager
    event_logger: EventLogger
    loop: asyncio.AbstractEventLoop
    _watch_rooms_task: asyncio.Task | None

    def __init__(
        self,
        *args,
        get_fileid_manager: callable[[], BaseFileIdManager],
        contents_manager: AsyncContentsManager | ContentsManager,
        event_logger: EventLogger,
        loop: asyncio.AbstractEventLoop,
        **kwargs,
    ):
        # Forward other arguments to parent class
        super().__init__(*args, **kwargs)

        # Bind instance attributes
        self._get_fileid_manager = get_fileid_manager
        self.contents_manager = contents_manager
        self.event_logger = event_logger
        self.loop = loop

        # Start `self._watch_rooms()` background task to automatically stop
        # empty rooms
        # TODO: Do not enable this until #120 is addressed.
        # self._watch_rooms_task = self.loop.create_task(self._watch_rooms())
        self._watch_rooms_task = None


    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self._get_fileid_manager()


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
            self.log.info(f"Initializing room '{room_id}'.")
            YRoomClass = self.yroom_class
            yroom = YRoomClass(
                parent=self,
                room_id=room_id,
                loop=self.loop,
                fileid_manager=self.fileid_manager,
                contents_manager=self.contents_manager,
                event_logger=self.event_logger,
            )
            self._rooms_by_id[room_id] = yroom
            return yroom
        except Exception as e:
            self.log.error(
                f"Unable to initialize YRoom '{room_id}'.",
                exc_info=True
            )
            return None
    

    def has_room(self, room_id: str) -> bool:
        """
        Returns whether a `YRoom` instance with a matching `room_id` already
        exists.
        """
        return room_id in self._rooms_by_id


    def delete_room(self, room_id: str) -> None:
        """
        Gracefully deletes a YRoom given a room ID. This stops the YRoom,
        closing all Websockets with close code 1001 (server shutting down),
        applying remaining updates, and saving the final content of the YDoc in
        a background task.

        Returns `True` if the room was deleted successfully. Returns `False` if
        an exception was raised.
        """
        yroom = self._rooms_by_id.pop(room_id, None)
        if not yroom:
            return
        
        self.log.info(f"Stopping YRoom '{room_id}'.")
        try:
            yroom.stop()
            return True
        except Exception as e:
            self.log.exception(
                f"Exception raised when stopping YRoom '{room_id}: "
            )
            return False
    
    async def _watch_rooms(self) -> None:
        """
        Background task that checks all `YRoom` instances every 10 seconds,
        restarting any updated rooms that have been inactive for >10 seconds.
        This frees the memory occupied by the room's YDoc history, discarding it
        in the process.

        - For rooms providing notebooks: This task restarts the room if it has
        been updated, has no connected clients, and its kernel execution status
        is either 'idle' or 'dead'.

        - For all other rooms: This task restarts the room if it has been
        updated and has no connected clients.
        """
        while True:
            # Check every 10 seconds
            await asyncio.sleep(10)

            # Get all room IDs, except for the global awareness room
            room_ids = set(self._rooms_by_id.keys())
            room_ids.discard("JupyterLab:globalAwareness")

            # Check all rooms and restart it if inactive for >10 seconds.
            for room_id in room_ids:
                self._check_room(room_id)
                

    def _check_room(self, room_id: str) -> None:
        """
        Checks a room for inactivity.

        - Rooms that have not been updated are not restarted, as there is no
        YDoc history to free.

        - If a room is inactive and not in `_inactive_rooms`, this method adds
        the room to `_inactive_rooms`. 

        - If a room is inactive and is listed in `_inactive_rooms`, this method
        restarts the room, as it has been inactive for 2 consecutive iterations
        of `_watch_rooms()`.
        """
        # Do nothing if the room has any connected clients.
        room = self._rooms_by_id[room_id]
        if room.clients.count != 0:
            self._inactive_rooms.discard(room_id)
            return
        
        # Do nothing if the room contains a notebook with kernel execution state
        # neither 'idle' nor 'dead'.
        # In this case, the notebook kernel may still be running code cells, so
        # the room should not be closed.
        awareness = room.get_awareness().get_local_state() or {}
        execution_state = awareness.get("kernel", {}).get("execution_state", None)
        if execution_state not in { "idle", "dead", None }:
            self._inactive_rooms.discard(room_id)
            return
        
        # Do nothing if the room has not been updated. This prevents empty rooms
        # from being restarted every 10 seconds.
        if not room.updated:
            self._inactive_rooms.discard(room_id)
            return

        # The room is updated (with history) & inactive if this line is reached.
        # Restart the room if was marked as inactive in the last iteration,
        # otherwise mark it as inactive.
        if room_id in self._inactive_rooms:
            self.log.info(
                f"Room '{room_id}' has been inactive for >10 seconds. "
                "Restarting the room to free memory occupied by its history."
            )
            room.restart()
            self._inactive_rooms.discard(room_id)
        else:
            self._inactive_rooms.add(room_id)


    def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.
        """
        # First, stop all background tasks
        if self._watch_rooms_task:
            self._watch_rooms_task.cancel()

        # Get all room IDs. If there are none, return early.
        room_ids = list(self._rooms_by_id.keys())
        room_count = len(room_ids)
        if room_count == 0:
            return

        # Otherwise, delete all rooms.
        self.log.info(
            f"Stopping `YRoomManager` and deleting all {room_count} YRooms."
        )
        failures = 0
        for room_id in room_ids:
            result = self.delete_room(room_id)
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
        
