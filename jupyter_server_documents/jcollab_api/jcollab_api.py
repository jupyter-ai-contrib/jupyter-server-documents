from __future__ import annotations
from jupyter_ydoc.ybasedoc import YBaseDoc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Literal
    from jupyter_server_fileid.manager import BaseFileIdManager
    from ..rooms import YRoomManager


class JCollabAPI:
    """
    Provides the Python API provided by `jupyter_collaboration~=4.0` under
    `self.settings["jupyter_server_ydoc"]`.
    """
    fileid_manager: BaseFileIdManager
    yroom_manager: YRoomManager

    def __init__(self, get_fileid_manager: Callable[[], BaseFileIdManager], yroom_manager: YRoomManager):
        self._get_fileid_manager = get_fileid_manager
        self.yroom_manager = yroom_manager

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self._get_fileid_manager()

    async def get_document(
        self,
        *,
        path: str | None = None,
        content_type: str | None = None,
        file_format: Literal["json", "text"] | None = None,
        room_id: str | None = None,
        copy: bool = True,
    ) -> YBaseDoc:
        """
        Returns the Jupyter YDoc for a collaborative room.

        You need to provide either a ``room_id`` or the ``path``,
        the ``content_type`` and the ``file_format``.

        The `copy` argument is ignored by `jupyter_server_documents`.
        """

        # Raise exception if required arguments are not given
        if room_id is None and (path is None or content_type is None or file_format is None):
            raise ValueError(
                "You need to provide either a ``room_id`` or the ``path``, the ``content_type`` and the ``file_format``."
            )
        
        # Compute room_id if not given
        if room_id is None:
            file_id = self.fileid_manager.index(path)
            room_id = f"{file_format}:{content_type}:{file_id}"
        
        # Get or create room using `room_id`
        room = self.yroom_manager.get_room(room_id)
        if not room:
            raise ValueError(
                f"Could not get room using room ID '{room_id}'."
            )
        
        # Return the Jupyter YDoc once ready
        return await room.get_jupyter_ydoc()
