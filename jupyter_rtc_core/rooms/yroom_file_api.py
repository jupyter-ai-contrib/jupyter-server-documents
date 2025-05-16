"""
WIP.

This file just contains interfaces to be filled out later.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Literal
import asyncio
import pycrdt
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_server.utils import ensure_async
import logging
import os

if TYPE_CHECKING:
    from typing import Awaitable
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager

class YRoomFileAPI:
    """
    Provides an API to 1 file from Jupyter Server's ContentsManager for a YRoom,
    given the the room's JupyterYDoc and ID in the constructor.

    To load the content, consumers should call `file_api.load_ydoc_content()`,
    then `await file_api.ydoc_content_loaded` before performing any operations
    on the YDoc.

    To save a JupyterYDoc to the file, call
    `file_api.schedule_save(jupyter_ydoc)`.
    """

    # See `filemanager.py` in `jupyter_server` for references on supported file
    # formats & file types.
    room_id: str
    file_format: Literal["text", "base64"]
    file_type: Literal["file", "notebook"]
    file_id: str
    log: logging.Logger
    jupyter_ydoc: YBaseDoc

    _fileid_manager: BaseFileIdManager
    _contents_manager: AsyncContentsManager | ContentsManager
    _loop: asyncio.AbstractEventLoop
    _ydoc_content_loading: False
    _ydoc_content_loaded: asyncio.Event
    _scheduled_saves: asyncio.Queue[None]

    def __init__(
        self,
        *,
        room_id: str,
        jupyter_ydoc: YBaseDoc,
        log: logging.Logger,
        fileid_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
        loop: asyncio.AbstractEventLoop
    ):
        # Bind instance attributes
        self.room_id = room_id
        self.file_format, self.file_type, self.file_id = room_id.split(":")
        self.jupyter_ydoc = jupyter_ydoc
        self.log = log
        self._loop = loop
        self._fileid_manager = fileid_manager
        self._contents_manager = contents_manager

        # Initialize loading & loaded states
        self._ydoc_content_loading = False
        self._ydoc_content_loaded = asyncio.Event()

        # Initialize save request queue
        # Setting maxsize=1 allows 1 save in-progress with another save pending.
        self._scheduled_saves = asyncio.Queue(maxsize=1)

        # Start processing scheduled saves in a loop running concurrently
        self._loop.create_task(self._process_scheduled_saves())


    def get_path(self) -> str:
        """
        Returns the path to the file by querying the FileIdManager. This is a
        relative path to the `root_dir` in `ContentsManager`.

        Raises a `RuntimeError` if the file ID does not refer to a valid file
        path.
        """
        abs_path = self._fileid_manager.get_path(self.file_id)
        if not abs_path:
            raise RuntimeError(
                f"Unable to locate file with ID: '{self.file_id}'."
            )

        rel_path = os.path.relpath(abs_path, self._contents_manager.root_dir)
        return rel_path
    

    @property
    def ydoc_content_loaded(self) -> Awaitable[None]:
        """
        Returns an Awaitable that only resolves when the content of the YDoc is
        loaded.
        """
        return self._ydoc_content_loaded.wait()
    

    def load_ydoc_content(self) -> None:
        """
        Loads the file from disk asynchronously into `self.jupyter_ydoc`.
        Consumers should `await file_api.ydoc_content_loaded` before performing
        any operations on the YDoc.
        """
        # If already loaded/loading, return immediately.
        # Otherwise, set loading to `True` and start the loading task.
        if self._ydoc_content_loaded.is_set() or self._ydoc_content_loading:
            return
        
        self.log.info(f"Loading content for room ID '{self.room_id}'.")
        self._ydoc_content_loading = True
        self._loop.create_task(self._load_ydoc_content())

    
    async def _load_ydoc_content(self) -> None:
        # Load the content of the file from the given file ID.
        path = self.get_path()
        m = await ensure_async(self._contents_manager.get(
            path,
            type=self.file_type,
            format=self.file_format
        ))
        content = m['content']

        # Set JupyterYDoc content
        self.jupyter_ydoc.source = content

        # Finally, set loaded event to inform consumers that the YDoc is ready
        # Also set loading to `False` for consistency
        self._ydoc_content_loaded.set()
        self._ydoc_content_loading = False
        self.log.info(f"Loaded content for room ID '{self.room_id}'.")

    
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
        """
        Defines a background task that processes scheduled saves, after waiting
        for the JupyterYDoc content to be loaded.
        """

        # Wait for content to be loaded before processing scheduled saves
        await self._ydoc_content_loaded.wait()

        while True:
            try:
                await self._scheduled_saves.get()
            except asyncio.QueueShutDown:
                break
            
            await self._save_jupyter_ydoc()

        self.log.info(
            "Stopped `self._process_scheduled_save()` background task "
            f"for YRoom '{self.room_id}'."
        )

    
    async def _save_jupyter_ydoc(self):
        """
        Saves the JupyterYDoc to disk immediately.

        This is a private method, and should only be called through the
        `_process_scheduled_saves()` task and the `stop()` method. Consumers
        should instead call `schedule_save()` to save the document.
        """
        try:
            assert self.jupyter_ydoc
            path = self.get_path()
            content = self.jupyter_ydoc.source
            file_format = self.file_format
            file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

            # Save the YDoc via the ContentsManager
            await ensure_async(self._contents_manager.save(
                {
                    "format": file_format,
                    "type": file_type,
                    "content": content,
                },
                path
            ))

            # Setting `dirty` to `False` hides the "unsaved changes" icon in the
            # JupyterLab tab for this YDoc in the frontend.
            self.jupyter_ydoc.dirty = False
        except Exception as e:
            self.log.error("An exception occurred when saving JupyterYDoc.")
            self.log.exception(e)
    
    async def stop(self) -> None:
        """
        Gracefully stops the YRoomFileAPI, saving the content of
        `self.jupyter_ydoc` before exiting.
        """
        # Stop the `self._process_scheduled_saves()` background task
        # immediately. This is safe since we save before stopping anyways.
        self._scheduled_saves.shutdown(immediate=True)

        # Do nothing if content was not loaded first. This prevents overwriting
        # the existing file with an empty JupyterYDoc.
        if not (self._ydoc_content_loaded.is_set()):
            return
        
        # Save the file and return.
        await self._save_jupyter_ydoc()

    
# see https://github.com/jupyterlab/jupyter-collaboration/blob/main/projects/jupyter-server-ydoc/jupyter_server_ydoc/loaders.py#L146-L149
SAVEABLE_FILE_TYPES = { "directory", "file", "notebook" }
