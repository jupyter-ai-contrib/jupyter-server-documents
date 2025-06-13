from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    import logging
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from jupyter_events import EventLogger

class YRoomManager():
    """
    A singleton that manages all `YRoom` instances in the server extension. This
    automatically deletes `YRoom` instances if they have had no connected
    clients or active kernel for >10 seconds.

    Because rooms may be deleted due to inactivity, consumers should only store
    a reference to the room ID and call `get_room(room_id)` each time a
    reference to the room is needed. See `get_room()` for more details.
    """

    _rooms_by_id: dict[str, YRoom]
    """
    Dictionary of active `YRoom` instances, keyed by room ID.

    It is guaranteed that if a room is present in the dictionary, the room is
    not currently stopping. This is ensured by `_handle_yroom_stopping()`.
    """

    _inactive_rooms: set[str]
    """
    Set of room IDs that were marked inactive on the last iteration of
    `_watch_rooms()`. If a room is inactive and its ID is present in this set,
    then the room has been inactive for >10 seconds, and the room should be
    deleted in `_watch_rooms()`.
    """

    _get_fileid_manager: callable[[], BaseFileIdManager]
    contents_manager: AsyncContentsManager | ContentsManager
    event_logger: EventLogger
    loop: asyncio.AbstractEventLoop
    log: logging.Logger
    _watch_rooms_task: asyncio.Task

    def __init__(
        self,
        *,
        get_fileid_manager: callable[[], BaseFileIdManager],
        contents_manager: AsyncContentsManager | ContentsManager,
        event_logger: EventLogger,
        loop: asyncio.AbstractEventLoop,
        log: logging.Logger,
    ):
        # Bind instance attributes
        self._get_fileid_manager = get_fileid_manager
        self.contents_manager = contents_manager
        self.event_logger = event_logger
        self.loop = loop
        self.log = log

        # Initialize dictionary of YRooms, keyed by room ID
        self._rooms_by_id = {}

        # Initialize set of inactive rooms tracked by `self._watch_rooms()`
        self._inactive_rooms = set()

        # Start `self._watch_rooms()` background task to automatically stop
        # empty rooms
        self._watch_rooms_task = self.loop.create_task(self._watch_rooms())


    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self._get_fileid_manager()


    def get_room(self, room_id: str) -> YRoom | None:
        """
        Returns the `YRoom` instance for a given room ID. If the instance does
        not exist, this method will initialize one and return it. Otherwise,
        this method returns the instance from its cache, ensuring that this
        method is fast in almost all cases.

        Consumers should always call this method each time a reference to the
        `YRoom` is needed, since rooms may be deleted due to inactivity.

        This method also ensures that the returned room will be alive for >10
        seconds. This prevents the room from being deleted shortly after the
        consumer receives it via this method, even if it was inactive.
        """
        # First, ensure this room stays open for >10 seconds by removing it from
        # the inactive set of rooms if it is present.
        self._inactive_rooms.discard(room_id)

        # If room exists, return the room
        if room_id in self._rooms_by_id:
            return self._rooms_by_id[room_id]
        
        # Otherwise, create a new room
        try:
            self.log.info(f"Initializing room '{room_id}'.")
            yroom = YRoom(
                room_id=room_id,
                log=self.log,
                loop=self.loop,
                fileid_manager=self.fileid_manager,
                contents_manager=self.contents_manager,
                on_stopping=lambda: self._handle_yroom_stopping(room_id),
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

    def _handle_yroom_stopping(self, room_id: str) -> None:
        """
        Callback that is run when the YRoom starts stopping. This callback:
        
        - Ensures the room is removed from the dictionary, even if the room was
        stopped directly without `YRoomManager.delete_room()`.

        - Prevents future connections to the stopping room and allows its memory
        to be freed once complete.
        """
        self._rooms_by_id.pop(room_id, None)

        
    def delete_room(self, room_id: str) -> None:
        """
        Gracefully deletes a YRoom given a room ID. This stops the YRoom,
        closing all Websockets, applying remaining updates, and saves the final
        content of the YDoc in a background task.

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
        deleting any rooms that have been inactive for >10 seconds.

        - For rooms providing notebooks: This task deletes the room if it has no
        connected clients and its kernel execution status is either 'idle' or
        'dead'.

        - For all other rooms: This task deletes the room if it has no connected
        clients.
        """
        while True:
            # Check every 10 seconds
            await asyncio.sleep(10)

            # Get all room IDs from the room dictionary in advance, as the
            # dictionary will mutate if rooms are deleted.
            room_ids = set(self._rooms_by_id.keys())

            # Remove the global awareness room ID from this set, as that room
            # should not be stopped until the server extension is stopped.
            room_ids.discard("JupyterLab:globalAwareness")

            # Iterate through all rooms. If any rooms are empty, stop the rooms.
            for room_id in room_ids:
                # Continue if `room_id` is not in the rooms dictionary. This
                # happens if the room was stopped by something else while this
                # `for` loop is still running, so we must check.
                if room_id not in self._rooms_by_id:
                    self._inactive_rooms.discard(room_id)
                    continue

                # Continue if the room has any connected clients.
                room = self._rooms_by_id[room_id]
                if room.clients.count != 0:
                    self._inactive_rooms.discard(room_id)
                    continue
                
                # Continue if the room contains a notebook with kernel execution
                # state neither 'idle' nor 'dead'.
                # In this case, the notebook kernel may still be running code
                # cells, so the room should not be closed.
                awareness = room.get_awareness().get_local_state() or {}
                execution_state = awareness.get("kernel", {}).get("execution_state", None)
                if execution_state not in { "idle", "dead", None }:
                    self._inactive_rooms.discard(room_id)
                    continue

                # The room is inactive if this statement is reached
                # Delete the room if was marked as inactive in the last
                # iteration, otherwise mark it as inactive.
                if room_id in self._inactive_rooms:
                    self.log.info(
                        f"YRoom '{room_id}' has been inactive for >10 seconds. "
                    )
                    self.loop.create_task(self.delete_room(room_id))
                    self._inactive_rooms.discard(room_id)
                else:
                    self._inactive_rooms.add(room_id)
                

    def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.
        """
        # First, stop all background tasks
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
        
