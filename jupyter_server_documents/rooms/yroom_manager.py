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
    _rooms_by_id: dict[str, YRoom]

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
    

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self._get_fileid_manager()


    def get_room(self, room_id: str) -> YRoom | None:
        """
        Retrieves a YRoom given a room ID. If the YRoom does not exist, this
        method will initialize a new YRoom.
        """

        # If room exists, then return it immediately
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
                on_stop=lambda: self._handle_yroom_stop(room_id),
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
    

    def _handle_yroom_stop(self, room_id: str) -> None:
        """
        Callback that is run when the YRoom is stopped. This ensures the room is
        removed from the dictionary for garbage collection, even if the room was
        stopped directly without `YRoomManager.delete_room()`.
        """
        self._rooms_by_id.pop(room_id, None)

        
    async def delete_room(self, room_id: str) -> None:
        """
        Gracefully deletes a YRoom given a room ID. This stops the YRoom first,
        which finishes applying all updates & saves the content automatically.

        Returns `True` if the room was deleted successfully. Returns `False` if
        an exception was raised.
        """
        yroom = self._rooms_by_id.pop(room_id, None)
        if not yroom:
            return
        
        self.log.info(f"Stopping YRoom '{room_id}'.")
        try:
            await yroom.stop()
            self.log.info(f"Stopped YRoom '{room_id}'.")
            return True
        except Exception as e:
            self.log.error(f"Exception raised when stopping YRoom '{room_id}:")
            self.log.exception(e)
            return False
    

    async def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.
        """
        room_ids = list(self._rooms_by_id.keys())
        room_count = len(room_ids)

        if room_count == 0:
            return

        self.log.info(
            f"Stopping `YRoomManager` and deleting all {room_count} YRooms."
        )

        # Delete rooms in parallel.
        # Note that we do not use `asyncio.TaskGroup` here because that cancels
        # all other tasks when any task raises an exception.
        deletion_tasks = []
        for room_id in room_ids:
            dt = asyncio.create_task(self.delete_room(room_id))
            deletion_tasks.append(dt)
        
        # Use returned values to log success/failure of room deletion
        results: list[bool] = await asyncio.gather(*deletion_tasks)
        failures = results.count(False)

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
        
