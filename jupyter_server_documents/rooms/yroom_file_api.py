from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
from datetime import datetime
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_server.utils import ensure_async
import logging
from tornado.web import HTTPError
from traitlets.config import LoggingConfigurable
from traitlets import Float

if TYPE_CHECKING:
    from typing import Any, Coroutine, Literal
    from .yroom import YRoom
    from jupyter_server_fileid.manager import BaseFileIdManager  # type: ignore
    from jupyter_server.services.contents.manager import ContentsManager
    from ..outputs.manager import OutputsManager

class YRoomFileAPI(LoggingConfigurable):
    """
    Provides an API to 1 file from Jupyter Server's ContentsManager for a YRoom.
    This class takes only a single argument: `parent: YRoom`.

    - To load the content, consumers call `load_content_into()` with a
    JupyterYDoc. This also starts the `_watch_file()` loop.

    - Consumers should `await file_api.until_content_loaded` before performing
    any operations on the YDoc.

    - To save a JupyterYDoc to the file, call
    `file_api.schedule_save(jupyter_ydoc)` after calling `load_content_into()`.
    """

    poll_interval = Float(
        default_value=0.5,
        help="Sets how frequently this class saves the YDoc & checks the file "
        "for changes. Defaults to every 0.5 seconds.",
        config=True,
    )

    parent: YRoom
    """
    The parent `YRoom` instance that is using this instance.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    log: logging.Logger
    """
    The `logging.Logger` instance used by this class to log.

    NOTE: This is automatically set by the `LoggingConfigurable` parent class;
    this declaration only hints the type for type checkers.
    """

    # See `filemanager.py` in `jupyter_server` for references on supported file
    # formats & file types.
    file_format: Literal["text", "base64"]
    file_type: Literal["file", "notebook"]
    file_id: str

    _save_scheduled: bool
    _content_loading: bool
    _content_load_event: asyncio.Event

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

    _watch_file_task: asyncio.Task | None
    """
    The task running the `_watch_file()` loop that processes scheduled saves and
    watches for in-band & out-of-band changes.
    """

    _stopped: bool
    """
    Whether the FileAPI has been stopped, i.e. when the `_watch_file()` task is
    not running.
    """

    _content_lock: asyncio.Lock
    """
    An `asyncio.Lock` that ensures `ContentsManager` calls reading/writing for a
    single file do not overlap. This prevents file corruption scenarios like
    dual-writes or dirty-reads.
    """

    def __init__(self, *args, **kwargs):
        # Forward all arguments to parent class
        super().__init__(*args, **kwargs)

        # Bind instance attributes
        self.file_format, self.file_type, self.file_id = self.room_id.split(":")
        self._save_scheduled = False
        self._last_path = None
        self._last_modified = None
        self._stopped = False

        # Initialize content-related primitives
        self._content_loading = False
        self._content_load_event = asyncio.Event()
        self._content_lock = asyncio.Lock()


    def get_path(self) -> str | None:
        """
        Returns the relative path to the file by querying the FileIdManager. The
        path is relative to the `ServerApp.root_dir` configurable trait.

        Raises a `RuntimeError` if the file ID does not refer to a valid file
        path.
        """
        return self.fileid_manager.get_path(self.file_id)
    
    @property
    def room_id(self) -> str:
        return self.parent.room_id

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        """
        Returns the Jupyter Server's File ID Manager.
        """
        return self.parent.fileid_manager
    
    @property
    def contents_manager(self) -> ContentsManager:
        """
        Stores a reference to the Jupyter Server's ContentsManager.

        NOTE: any calls made on this attribute should acquire & release the
        `_content_lock`. See `_content_lock` for more info.
        """
        return self.parent.contents_manager

    @property
    def outputs_manager(self) -> OutputsManager:
        return self.parent.outputs_manager

    @property
    def content_loaded(self) -> bool:
        """
        Immediately returns whether the YDoc content is loaded.

        To have a coroutine wait until the content is loaded, call `await
        file_api.until_content_loaded` instead.
        """
        return self._content_load_event.is_set()


    @property
    def until_content_loaded(self) -> Coroutine[Any, Any, Literal[True]]:
        """
        Returns an awaitable that resolves when the content is loaded.
        """
        return self._content_load_event.wait()


    def load_content_into(self, jupyter_ydoc: YBaseDoc) -> None:
        """
        Loads the file content into the given JupyterYDoc.
        Consumers should `await file_api.ydoc_content_loaded` before performing
        any operations on the YDoc.

        This method starts the `_watch_file()` task after the content is loaded.
        """
        # If already loaded/loading, return immediately.
        # Otherwise, set loading to `True` and start the loading task.
        if self._content_load_event.is_set() or self._content_loading:
            return
        
        self._content_loading = True
        asyncio.create_task(self._load_content(jupyter_ydoc))

    
    async def _load_content(self, jupyter_ydoc: YBaseDoc) -> None:
        # Get the path specified on the file ID
        path = self.get_path()
        if not path:
            raise RuntimeError(f"Could not find path for room '{self.room_id}'.")
        self._last_path = path

        # Load the content of the file from the path
        self.log.info(f"Loading content for room ID '{self.room_id}', found at path: '{path}'.")
        async with self._content_lock:
            file_data = await ensure_async(self.contents_manager.get(
                path,
                type=self.file_type,
                format=self.file_format
            ))

        if self.file_type == "notebook":
            self.log.info(f"Processing outputs for loaded notebook: '{self.room_id}'.")
            file_data = self.outputs_manager.process_loaded_notebook(file_id=self.file_id, file_data=file_data)

        # Set JupyterYDoc content and set `dirty = False` to hide the "unsaved
        # changes" icon in the UI
        jupyter_ydoc.source = file_data['content']
        jupyter_ydoc.dirty = False

        # Set `_last_modified` timestamp
        self._last_modified = file_data['last_modified']

        # Set loaded event to inform consumers that the YDoc is ready
        # Also set loading to `False` for consistency and log success
        self._content_load_event.set()
        self._content_loading = False
        self.log.info(f"Loaded content for room ID '{self.room_id}'.")

        # Start _watch_file() task
        self._watch_file_task = asyncio.create_task(
            self._watch_file(jupyter_ydoc)
        )


    def schedule_save(self) -> None:
        """
        Schedules a save of the Jupyter YDoc to disk. When called, the Jupyter
        YDoc will be saved on the next tick of the `self._watch_file()`
        background task.
        """
        self._save_scheduled = True
    
    async def _watch_file(self, jupyter_ydoc: YBaseDoc) -> None:
        """
        Defines a background task that processes scheduled saves to the YDoc
        on an interval, checking for in-band & out-of-band changes before doing
        so.

        - The interval duration is set by the `self.poll_interval` configurable
        trait, which defaults to saving & checking every 0.5 seconds.

        - This task is started by a call to `load_ydoc_content()`. Consumers
        must call `self.schedule_save()` for the next tick of this task to save.
        """

        while True:
            try:
                await asyncio.sleep(self.poll_interval)
                await self._check_file()
                if self._save_scheduled:
                    # `asyncio.shield()` prevents the save task from being
                    # cancelled halfway and corrupting the file. We need to
                    # store a reference to the shielded task to prevent it from
                    # being garbage collected (see `asyncio.shield()` docs).
                    save_task = self.save(jupyter_ydoc)
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

        self.log.debug(
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
        - In-band deletion: calls `self.parent.handle_inband_deletion()`
        - Out-of-band move/deletion: calls `self.parent.handle_outofband_move()`
        - Out-of-band change: calls `self.parent.handle_outofband_change()`
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
                self.parent.handle_inband_deletion()
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
            async with self._content_lock:
                file_data = await ensure_async(self.contents_manager.get(
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
            self.parent.handle_outofband_move()
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
            self.parent.handle_outofband_change()

    
    async def save(self, jupyter_ydoc: YBaseDoc):
        """
        Saves the given JupyterYDoc to disk. This method works even if the
        FileAPI is stopped.

        This method should only be called by consumers if the YDoc needs to be
        saved while the FileAPI is stopped, e.g. when the parent room is
        stopping. In all other cases, consumers should call `schedule_save()`
        instead.
        """
        try:
            # Build arguments to `CM.save()`
            path = self.get_path()
            content = jupyter_ydoc.source
            file_format = self.file_format
            file_type = self.file_type if self.file_type in SAVEABLE_FILE_TYPES else "file"

            # Set `_save_scheduled=False` before the `await` to make sure we
            # save on the next tick when a save is scheduled while `CM.get()` is
            # being awaited.
            self._save_scheduled = False

            if self.file_type == "notebook":
                content = self.outputs_manager.process_saving_notebook(content, self.file_id)

            # Save the YDoc via the ContentsManager
            async with self._content_lock:
                file_data = await ensure_async(self.contents_manager.save(
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
            jupyter_ydoc.dirty = False
        except Exception as e:
            self.log.error("An exception occurred when saving JupyterYDoc.")
            self.log.exception(e)
    

    def stop(self) -> None:
        """
        Gracefully stops the `YRoomFileAPI`. This immediately halts the
        background task saving the YDoc to the `ContentsManager`.

        To save the YDoc after stopping, call `await
        file_api.save_immediately()` after calling this method.
        """
        if self._watch_file_task:
            self._watch_file_task.cancel()
        self._stopped = True

    @property
    def stopped(self) -> bool:
        """
        Returns whether the FileAPI has been stopped via the `stop()` method.
        """
        return self._stopped

    def restart(self) -> None:
        """
        Restarts the instance by stopping if the room is not stopped, then
        clearing its internal state.

        Consumers should call `load_content_into()` again after this method to
        restart the `_watch_file()` task.
        """
        # Stop if not stopped already
        if not self.stopped:
            self.stop()

        # Reset instance attributes
        self._stopped = False
        self._content_load_event = asyncio.Event()
        self._content_loading = False
        self._save_scheduled = False
        self._last_modified = None
        self._last_path = None
        self.log.info(f"Restarted FileAPI for room '{self.room_id}'.")

    
# see https://github.com/jupyterlab/jupyter-collaboration/blob/main/projects/jupyter-server-ydoc/jupyter_server_ydoc/loaders.py#L146-L149
SAVEABLE_FILE_TYPES = { "directory", "file", "notebook" }
