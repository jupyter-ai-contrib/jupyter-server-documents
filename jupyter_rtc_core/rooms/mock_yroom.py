import logging
from typing import Any

from .yroom import YRoom


class MockYRoom(YRoom):
    """
    mock YRoom implementation that uses jupyter_collaboration

    """

    @property
    def jupyter_server_ydoc(self):
        self.log.info(f"parent settings: {self.parent.settings}")
        return self.parent.parent.settings["jupyter_server_ydoc"]
    
    def __init__(self, room_id: str, path: str, parent: Any, **kwargs: Any):
        self.parent = parent
        self.path = path
        self.log = logging.getLogger(f"{self.__class__.__name__}.{room_id}")

        self.room_id = room_id

    async def get_ydoc(self):
        notebook = await self.jupyter_server_ydoc.get_document(path=self.path, copy=False, file_format='json', content_type='notebook')
        return notebook