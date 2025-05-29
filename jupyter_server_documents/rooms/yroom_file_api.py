"""
WIP.

This file just contains interfaces to be filled out later.
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
from datetime import datetime
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_server.utils import ensure_async
import logging
import os

if TYPE_CHECKING:
    from typing import Any, Awaitable, Callable, Literal
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
    _last_modified: datetime | None

    _save_loop_task: asyncio.Task

    def __init__(
        self,
        *,
        room_id: str,
        jupyter_ydoc: YBaseDoc,
        log: logging.Logger,
        fileid_manager: BaseFileIdManager,
        contents_manager: AsyncContentsManager | ContentsManager,
        loop: asyncio.AbstractEventLoop,
        on_outofband_change: Callable[[], Any]
    ):
        # Bind instance attributes
        self.room_id = room_id
        self.file_format, self.file_type, self.file_id = room_id.split(":")
        self.jupyter_ydoc = jupyter_ydoc
        self.log = log
        self._loop = loop
        self._fileid_manager = fileid_manager
        self._contents_manager = contents_manager
        self._on_outofband_change = on_outofband_change
        self._last_modified = None

        # Initialize loading & loaded states
        self._ydoc_content_loading = False
        self._ydoc_content_loaded = asyncio.Event()

        # Start processing scheduled saves in a loop running concurrently
        self._save_loop_task = self._loop.create_task(self._watch_file())


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
        file_data = await ensure_async(self._contents_manager.get(
            path,
            type=self.file_type,
            format=self.file_format
        ))

        # Set JupyterYDoc content
        self.jupyter_ydoc.source = file_data['content']

        # Set `_last_modified` timestamp
        self._last_modified = file_data['last_modified']

        # Finally, set loaded event to inform consumers that the YDoc is ready
        # Also set loading to `False` for consistency
        self._ydoc_content_loaded.set()
        self._ydoc_content_loading = False
        self.log.info(f"Loaded content for room ID '{self.room_id}'.")


    def schedule_save(self) -> None:
        """
        Schedules a save of the Jupyter YDoc to disk. When called, the Jupyter
        YDoc will be saved on the next tick of the `self._watch_file()`
        background task.
        """
        self._save_scheduled = True
    
    async def _watch_file(self) -> None:
        """
        Defines a background task that continuously saves the YDoc every 500ms.

        Note that consumers must call `self.schedule_save()` for the next tick
        of this task to save.
        """

        # Wait for content to be loaded before processing scheduled saves
        await self._ydoc_content_loaded.wait()

        while True:
            try:
                await asyncio.sleep(0.5)
                await self._check_oob_changes()
                if self._save_scheduled:
                    # `asyncio.shield()` prevents the save task from being
                    # cancelled halfway and corrupting the file. We need to
                    # store a reference to the shielded task to prevent it from
                    # being garbage collected (see `asyncio.shield()` docs).
                    save_task = self._save_jupyter_ydoc()
                    await asyncio.shield(save_task)
            except asyncio.CancelledError:
                break
            except Exception:
                self.log.exception(
                    "Exception occurred in `_watch_file() background task "
                    f"for YRoom '{self.room_id}'."
                )

        self.log.info(
            "Stopped `self._watch_file()` background task "
            f"for YRoom '{self.room_id}'."
        )

    async def _check_oob_changes(self):
        """
        Checks for out-of-band changes. Called in the `self._watch_file()`
        background task.
        
        Calls the `on_outofband_change()` function passed to the constructor if
        an out-of-band change is detected. This is guaranteed to always run
        before each save through the `ContentsManager`.
        """
        # Build arguments to `CM.get()`
        path = self.get_path()
        file_format = self.file_format
        file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

        # Check for out-of-band file changes
        file_data = await ensure_async(self._contents_manager.get(
            path=path, format=file_format, type=file_type, content=False
        ))

        # If an out-of-band file change is detected, run the designated callback
        if self._last_modified != file_data['last_modified']:
            self.log.warning("Out-of-band file change detected.")
            self.log.warning(f"Last detected change: {self._last_modified}")
            self.log.warning(f"Most recent change: {file_data['last_modified']}")
            self._on_outofband_change()

    
    async def _save_jupyter_ydoc(self):
        """
        Saves the JupyterYDoc to disk immediately.

        This is a private method. Consumers should call
        `file_api.schedule_save()` to save the YDoc on the next tick of
        the `self._watch_file()` background task.
        """
        try:
            # Build arguments to `CM.save()`
            path = self.get_path()
            content = self.jupyter_ydoc.source
            file_format = self.file_format
            file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

            # Set `_save_scheduled=False` before the `await` to make sure we
            # save on the next tick when a save is scheduled while `CM.get()` is
            # being awaited.
            self._save_scheduled = False

            # Save the YDoc via the ContentsManager
            file_data = await ensure_async(self._contents_manager.save(
                {
                    "format": file_format,
                    "type": file_type,
                    "content": content,
                },
                path
            ))

            # Set most recent `last_modified` timestamp
            if file_data['last_modified']:
                self.log.info(f"Reseting last_modified to {file_data['last_modified']}")
                self._last_modified = file_data['last_modified']

            # Set `dirty` to `False` to hide the "unsaved changes" icon in the
            # JupyterLab tab for this YDoc in the frontend.
            self.jupyter_ydoc.dirty = False
        except Exception as e:
            self.log.error("An exception occurred when saving JupyterYDoc.")
            self.log.exception(e)
    

    def stop(self) -> None:
        """
        Gracefully stops the `YRoomFileAPI`. This immediately halts the
        background task saving the YDoc to the `ContentsManager`.

        To save the YDoc after stopping, call `await file_api.stop_then_save()`
        instead.
        """
        self._save_loop_task.cancel()


    async def stop_then_save(self) -> None:
        """
        Gracefully stops the YRoomFileAPI by calling `self.stop()`, then saves
        the content of `self.jupyter_ydoc` before exiting.
        """
        self.stop()
        await self._save_jupyter_ydoc()

    
# see https://github.com/jupyterlab/jupyter-collaboration/blob/main/projects/jupyter-server-ydoc/jupyter_server_ydoc/loaders.py#L146-L149
SAVEABLE_FILE_TYPES = { "directory", "file", "notebook" }
