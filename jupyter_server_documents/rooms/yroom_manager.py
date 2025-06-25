from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING
import asyncio
import traitlets
from traitlets.config import LoggingConfigurable
from jupyter_server_fileid.manager import BaseFileIdManager

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

    _rooms_by_id: dict[str, YRoom] = traitlets.Dict(default_value={})
    """
    Dictionary of active `YRoom` instances, keyed by room ID. Rooms are never
    deleted from this dictionary.

    TODO: Delete a room if its file was deleted in/out-of-band or moved
    out-of-band. See #116.
    """

    _inactive_rooms: set[str] = traitlets.Set()
    """
    Set of room IDs that were marked inactive on the last iteration of
    `_watch_rooms()`. If a room is inactive and its ID is present in this set,
    then the room should be restarted as it has been inactive for >10 seconds.
    """

    _watch_rooms_task: asyncio.Task | None

    def __init__(self, *args, **kwargs):
        # Forward all arguments to parent class
        super().__init__(*args, **kwargs)

        # Start `self._watch_rooms()` background task to automatically stop
        # empty rooms
        # TODO: Do not enable this until #120 is addressed.
        # self._watch_rooms_task = asyncio.create_task(self._watch_rooms())
        self._watch_rooms_task = None


    @property
    def fileid_manager(self) -> BaseFileIdManager:
        manager = self.parent.serverapp.web_app.settings.get("file_id_manager", None)
        assert isinstance(manager, BaseFileIdManager)
        return manager
    

    @property
    def contents_manager(self) -> ContentsManager:
        return self.parent.serverapp.contents_manager
    

    @property
    def event_logger(self) -> EventLogger:
        return self.parent.serverapp.event_logger
    

    @property
    def outputs_manager(self) -> OutputsManager:
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
            self.log.info(f"Initializing room '{room_id}'.")
            YRoomClass = self.yroom_class
            yroom = YRoomClass(
                parent=self,
                room_id=room_id,
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


    async def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.

        - This method should only be called when the server is shutting down.

        - This method is uniquely async because it waits for each room to finish
        saving its final content. Without waiting, the `ContentsManager` will
        shut down before the saves complete, resulting in empty files.
        """
        
        # First, stop all background tasks
        if self._watch_rooms_task:
            self._watch_rooms_task.cancel()

        # Return early if there are no rooms
        room_count = len(self._rooms_by_id)
        if room_count == 0:
            return

        # Otherwise, prepare to delete all rooms
        self.log.info(
            f"Stopping `YRoomManager` and deleting all {room_count} YRooms."
        )
        deletion_tasks = []

        # Define task that deletes the room and waits until the content is saved
        async def delete_then_save(room_id: str, room: YRoom):
            ret = self.delete_room(room_id)
            await room.until_saved
            return ret

        # Delete all rooms concurrently using `delete_then_save()`
        for room_id, room in self._rooms_by_id.items():
            deletion_task = asyncio.create_task(
                delete_then_save(room_id, room)
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
        
