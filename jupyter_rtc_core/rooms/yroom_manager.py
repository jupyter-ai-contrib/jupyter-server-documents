from typing import Any, Dict, Optional
from traitlets import HasTraits, Instance, default
from __future__ import annotations

from .yroom import YRoom
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio
    import logging
    from typing import Callable
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager

class YRoomManager():
    _rooms_by_id: dict[str, YRoom]

    def __init__(
        self,
        *,
        get_fileid_manager: Callable[[], BaseFileIdManager],
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
        
        
    def delete_room(self, room_id: str) -> None:
        """
        Deletes a YRoom given a room ID.
        
        TODO: finish implementing YRoom.stop(), and delete empty rooms w/ no
        live kernels automatically in a background task.
        """
        yroom = self._rooms_by_id.get(room_id, None)
        if not yroom:
            return
        
        yroom.stop()
        del self._rooms_by_id[room_id]
