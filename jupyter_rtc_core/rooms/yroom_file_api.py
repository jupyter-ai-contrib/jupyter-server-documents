"""
WIP.

This file just contains interfaces to be filled out later.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Literal, cast
import asyncio
import pycrdt
from jupyter_ydoc import ydocs as jupyter_ydoc_classes
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_server.utils import ensure_async
import logging

if TYPE_CHECKING:
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager

class YRoomFileAPI:
    """
    Provides an API to 1 file from Jupyter Server's ContentsManager for a YRoom,
    given the file format, type, and ID passed to the constructor.

    To load a JupyterYDoc from the file, run `await
    file_api.get_jupyter_ydoc()`.

    To save a JupyterYDoc to the file, call
    `file_api.schedule_save(jupyter_ydoc)`.
    """

    # See `filemanager.py` in `jupyter_server` for references on supported file
    # formats & file types.
    file_format: Literal["text", "base64"]
    file_type: Literal["file", "notebook"]
    file_id: str
    jupyter_ydoc: YBaseDoc | None
    log: logging.Logger

    _fileid_manager: BaseFileIdManager
    _contents_manager: AsyncContentsManager | ContentsManager
    _loop: asyncio.AbstractEventLoop
    _scheduled_saves: asyncio.Queue[None]

    def __init__(
        self,
        file_format: Literal["text", "base64"],
        file_type: Literal["file", "notebook"],
        file_id: str,
        log: logging.Logger,
        fileid_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
        loop: asyncio.AbstractEventLoop
    ):
        # Bind instance attributes
        self.file_format = file_format
        self.file_type = file_type
        self.file_id = file_id
        self.jupyter_ydoc = None
        self.log = log
        self._loop = loop
        self._fileid_manager = fileid_manager
        self._contents_manager = contents_manager

        # Initialize save request queue
        # Setting maxsize=1 allows 1 save in-progress with another save pending.
        self._scheduled_saves = asyncio.Queue(maxsize=1)

        # Start processing scheduled saves in a loop running concurrently
        self._loop.create_task(self._process_scheduled_saves())


    def get_path(self) -> str:
        """
        Returns the path to the file by querying the FileIdManager.

        Raises a `RuntimeError` if the file ID does not refer to a valid file
        path.
        """
        path = self._fileid_manager.get_path(self.file_id)
        if not path:
            raise RuntimeError(
                f"Unable to locate file with ID: '{self.file_id}'."
            )
        
        return path

    async def get_jupyter_ydoc(self) -> YBaseDoc:
        """
        Loads the file from disk asynchronously into a new JupyterYDoc.

        Note that this returns a `jupyter_ydoc.basedoc.YBaseDoc`, not a
        `pycrdt.Doc`. We should distinguish the two by referring to them as
        "JupyterYDoc" and "YDoc" respectively in our code. A JupyterYDoc
        contains both YDoc & YAwareness, under the `ydoc` and `awareness`
        attributes on JupyterYDoc.

        For notebooks, this method will return a `jupyter_ydoc.YNotebook`
        instance.

        For most other files, this method will return `jupyter_ydoc.YUnicode`
        instance.
        """
        # Get the content of the file from the given file ID.
        path = self.get_path()
        m = await self._contents_manager.get(path, type=self.file_type, format=self.file_format)
        content = m['content']

        # Initialize YDoc & YAwareness
        ydoc: pycrdt.Doc = pycrdt.Doc()
        awareness = pycrdt.Awareness(ydoc=ydoc)

        # Initialize JupyterYDoc
        JupyterYDocClass = cast(
            type[YBaseDoc],
            jupyter_ydoc_classes.get(self.file_type, jupyter_ydoc_classes["file"])
        )
        self.jupyter_ydoc = JupyterYDocClass(ydoc=ydoc, awareness=awareness)

        # Load file content in the JupyterYDoc, then return it
        self.jupyter_ydoc.source = content
        return self.jupyter_ydoc

    
    def schedule_save(self) -> None:
        """
        Schedules a request to save the JupyterYDoc to disk. This method
        requires `self.get_jupyter_ydoc()` to have been awaited prior; otherwise
        this will raise a `RuntimeError`.

        If there are no pending requests, then this will immediately save the
        YDoc to disk in a separate background thread.

        If there is any pending request, then this method does nothing, as the
        YDoc will be saved when the pending request is fulfilled.

        TODO: handle out-of-band changes to the file when writing.
        """
        assert self.jupyter_ydoc
        if not self._scheduled_saves.full():
            self._scheduled_saves.put_nowait(None)


    async def _process_scheduled_saves(self) -> None:
        while True:
            try:
                await self._scheduled_saves.get()
            except asyncio.QueueShutDown:
                return

            try:
                assert self.jupyter_ydoc
                path = self.get_path()
                content = self.jupyter_ydoc.source
                file_format = self.file_format
                file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

                await ensure_async(self._contents_manager.save(
                    {
                        "format": file_format,
                        "type": file_type,
                        "content": content,
                    },
                    path
                ))
            except Exception as e:
                self.log.error("An exception occurred when saving JupyterYDoc.")
                self.log.exception(e)

    
# see https://github.com/jupyterlab/jupyter-collaboration/blob/main/projects/jupyter-server-ydoc/jupyter_server_ydoc/loaders.py#L146-L149
SAVEABLE_FILE_TYPES = { "directory", "file", "notebook" }
