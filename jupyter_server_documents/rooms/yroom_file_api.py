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
from tornado.web import HTTPError

if TYPE_CHECKING:
    from typing import Any, Callable, Literal
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
    _save_scheduled: bool
    _ydoc_content_loading: bool
    _ydoc_content_loaded: asyncio.Event

    _last_modified: datetime | None
    """
    The last file modified timestamp known to this instance. If this value
    changes unexpectedly, that indicates an out-of-band change to the file.
    """

    _last_path: str | None
    """
    The last file path known to this instance. If this value changes
    unexpectedly, that indicates an out-of-band move/deletion on the file.
    """

    _on_outofband_change: Callable[[], Any]
    """
    The callback to run when an out-of-band file change is detected.
    """

    _on_outofband_move: Callable[[], Any]
    """
    The callback to run when an out-of-band file move/deletion is detected.
    """

    _on_inband_deletion: Callable[[], Any]
    """
    The callback to run when an in-band move file deletion is detected.
    """

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
        on_outofband_change: Callable[[], Any],
        on_outofband_move: Callable[[], Any],
        on_inband_deletion: Callable[[], Any]
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
        self._on_outofband_move = on_outofband_move
        self._on_inband_deletion = on_inband_deletion
        self._save_scheduled = False
        self._last_path = None
        self._last_modified = None

        # Initialize loading & loaded states
        self._ydoc_content_loading = False
        self._ydoc_content_loaded = asyncio.Event()

        # Start processing scheduled saves in a loop running concurrently
        self._save_loop_task = self._loop.create_task(self._watch_file())


    def get_path(self) -> str | None:
        """
        Returns the relative path to the file by querying the FileIdManager. The
        path is relative to the `ServerApp.root_dir` configurable trait.

        Raises a `RuntimeError` if the file ID does not refer to a valid file
        path.
        """
        return self._fileid_manager.get_path(self.file_id)
    

    @property
    def ydoc_content_loaded(self) -> asyncio.Event:
        """
        Returns an `asyncio.Event` that is set when the YDoc content is loaded.

        To suspend a coroutine until the content is loaded:

        ```
        await file_api.ydoc_content_loaded.wait()
        ```

        To synchronously (i.e. immediately) check if the content is loaded:
        
        ```
        file_api.ydoc_content_loaded.is_set()
        ```
        """

        return self._ydoc_content_loaded
    

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
        
        self._ydoc_content_loading = True
        self._loop.create_task(self._load_ydoc_content())

    
    async def _load_ydoc_content(self) -> None:
        # Get the path specified on the file ID
        path = self.get_path()
        if not path:
            raise RuntimeError(f"Could not find path for room '{self.room_id}'.")
        self._last_path = path

        # Load the content of the file from the path
        self.log.info(f"Loading content for room ID '{self.room_id}', found at path: '{path}'.")
        file_data = await ensure_async(self._contents_manager.get(
            path,
            type=self.file_type,
            format=self.file_format
        ))

        # Set JupyterYDoc content and set `dirty = False` to hide the "unsaved
        # changes" icon in the UI
        self.jupyter_ydoc.source = file_data['content']
        self.jupyter_ydoc.dirty = False

        # Set `_last_modified` timestamp
        self._last_modified = file_data['last_modified']

        # Finally, set loaded event to inform consumers that the YDoc is ready
        # Also set loading to `False` for consistency and log success
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
        Defines a background task that continuously saves the YDoc every 500ms,
        checking for out-of-band changes before doing so.

        Note that consumers must call `self.schedule_save()` for the next tick
        of this task to save.
        """

        # Wait for content to be loaded before processing scheduled saves
        await self._ydoc_content_loaded.wait()

        while True:
            try:
                await asyncio.sleep(0.5)
                await self._check_file()
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
                    f"for YRoom '{self.room_id}'. Halting for 5 seconds."
                )
                # Wait 5 seconds to reduce error log spam if the exception
                # occurs repeatedly.
                await asyncio.sleep(5)

        self.log.info(
            "Stopped `self._watch_file()` background task "
            f"for YRoom '{self.room_id}'."
        )

    async def _check_file(self):
        """
        Checks for in-band/out-of-band file operations in the
        `self._watch_file()` background task. This is guaranteed to always run
        before each save in `self._watch_file()` This detects the following
        events and acts in response:

        - In-band move: logs warning (no handling needed)
        - In-band deletion: calls `self._on_inband_deletion()`
        - Out-of-band move/deletion: calls `self._on_outofband_move()`
        - Out-of-band change: calls `self._on_outofband_change()`
        """
        # Ensure that the last known path is defined. This should always be set
        # by `load_ydoc_content()`.
        if not self._last_path:
            raise RuntimeError(f"No last known path for '{self.room_id}'. This should never happen.")

        # Get path. If the path does not match the last known path, the file was
        # moved/deleted in-band via the `ContentsManager`, as it was detected by
        # `jupyter_server_fileid.manager:ArbitraryFileIdManager`.
        # If this happens, run the designated callback and return early.
        path = self.get_path()
        if path != self._last_path:
            if path:
                self.log.warning(
                    f"File was moved to '{path}'. "
                    f"Room ID: '{self.room_id}', "
                    f"Last known path: '{self._last_path}'."
                )
            else:
                self.log.warning(
                    "File was deleted. "
                    f"Room ID: '{self.room_id}', "
                    f"Last known path: '{self._last_path}'."
                )
                self._on_inband_deletion()
                return

        # Otherwise, set the last known path
        self._last_path = path

        # Build arguments to `CM.get()`
        file_format = self.file_format
        file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

        # Get the file metadata from the `ContentsManager`.
        # If this raises `HTTPError(404)`, that indicates the file was
        # moved/deleted out-of-band.
        try:
            file_data = await ensure_async(self._contents_manager.get(
                path=path, format=file_format, type=file_type, content=False
            ))
        except HTTPError as e:
            # If not 404, re-raise the exception as it is unknown
            if (e.status_code != 404):
                raise e

            # Otherwise, this indicates the file was moved/deleted out-of-band.
            # Run the designated callback and return early.
            self.log.warning(
                "File was deleted out-of-band. "
                f"Room ID: '{self.room_id}', "
                f"Last known path: '{self._last_path}'."
            )
            self._on_outofband_move()
            return


        # Finally, if the file was not moved/deleted, check for out-of-band
        # changes to the file content using the metadata.
        # If an out-of-band file change is detected, run the designated callback.
        if self._last_modified != file_data['last_modified']:
            self.log.warning(
                "Out-of-band file change detected. "
                f"Room ID: '{self.room_id}', "
                f"Last detected change: '{self._last_modified}', "
                f"Most recent change: '{file_data['last_modified']}'."
            )
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
