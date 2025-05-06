"""
WIP.

This file just contains interfaces to be filled out later.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager

class YRoomLoader:
    file_format: str
    file_type: str
    file_id: str

    def __init__(
        self,
        file_format: str,
        file_type: str,
        file_id: str,
        file_id_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
        loop: asyncio.AbstractEventLoop
    ):
        # Bind instance attributes
        self.file_format = file_format
        self.file_type = file_type
        self.file_id = file_id
        self.file_id_manager = file_id_manager
        self.contents_manager = contents_manager
        self.loop = loop

    async def _load(self) -> None:
        """
        Loads the file from disk asynchronously. Uses the `FileIdManager`
        provided by `jupyter_server_fileid` to resolve the file ID to a path,
        then uses the ConfigManager to retrieve the contents of the file.

        TODO
        """
        return
    
    def schedule_write(self) -> None:
        """
        Schedules a write to the disk. If any other write is scheduled to the
        disk when this method is called, the other write is cancelled and
        replaced with this write request.

        TODO
        """
        return

