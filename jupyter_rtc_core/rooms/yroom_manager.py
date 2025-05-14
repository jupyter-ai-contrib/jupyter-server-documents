from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    import logging
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager

class YRoomManager():
    _rooms_by_id: dict[str, YRoom]

    def __init__(
        self,
        *,
        get_fileid_manager: callable[[], BaseFileIdManager],
        contents_manager: AsyncContentsManager | ContentsManager,
        loop: asyncio.AbstractEventLoop,
        log: logging.Logger,
    ):
        # Bind instance attributes
        self._get_fileid_manager = get_fileid_manager
        self.contents_manager = contents_manager
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
            )
            self._rooms_by_id[room_id] = yroom
            return yroom
        except Exception as e:
            self.log.error(
                f"Unable to initialize YRoom '{room_id}'.",
                exc_info=True
            )
            return None
        
        
    async def delete_room(self, room_id: str) -> None:
        """
        Gracefully deletes a YRoom given a room ID. This stops the YRoom first,
        which finishes applying all updates & saves the content automatically.
        """
        yroom = self._rooms_by_id.get(room_id, None)
        if not yroom:
            return
        
        await yroom.stop()
        del self._rooms_by_id[room_id]
    

    async def stop(self) -> None:
        """
        Gracefully deletes each `YRoom`. See `delete_room()` for more info.
        """
        for room_id in self._rooms_by_id.keys():
            await self.delete_room(room_id)
        
