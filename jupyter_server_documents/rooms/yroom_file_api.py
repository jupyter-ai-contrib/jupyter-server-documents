from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
import time
from datetime import datetime
from jupyter_ydoc.ybasedoc import YBaseDoc
from jupyter_server.utils import ensure_async
import logging
from tornado.web import HTTPError
from traitlets.config import LoggingConfigurable
from traitlets import Float, validate

if TYPE_CHECKING:
    from typing import Any, Coroutine, Literal
    from .yroom import YRoom
    from jupyter_server_fileid.manager import BaseFileIdManager  # type: ignore
    from jupyter_server.services.contents.manager import ContentsManager
    from ..outputs.manager import OutputsManager

DEFAULT_MIN_POLL_INTERVAL = 0.5
DEFAULT_POLL_INTERVAL_MULTIPLIER = 5.0
class YRoomFileAPI(LoggingConfigurable):
    """Provides an API to interact with a single file for a YRoom.

    This class manages the lifecycle of a file in the context of real-time collaboration,
    handling:
    - Loading file content from Jupyter Server's ContentsManager into a YDoc
    - Saving YDoc changes back to the filesystem with adaptive timing
    - Detecting and responding to in-band and out-of-band file changes
    - Managing notebook outputs through the OutputsManager

    Usage:
        1. Create instance with parent YRoom: `file_api = YRoomFileAPI(parent=yroom)`
        2. Load content: `file_api.load_content_into(jupyter_ydoc)`
        3. Wait for loading: `await file_api.until_content_loaded`
        4. Schedule saves: `file_api.schedule_save()` (saves happen automatically)
        5. Stop gracefully: `file_api.stop()`

    The class uses adaptive timing to optimize save intervals based on save duration,
    preventing performance degradation with large files while maintaining responsiveness
    for small files.

    Attributes:
        parent: The parent YRoom instance (set by LoggingConfigurable).
        file_format: The format of the file ('text' or 'base64').
        file_type: The type of the file ('file' or 'notebook').
        file_id: The unique identifier for this file.
    """

    min_poll_interval = Float(
        default_value=DEFAULT_MIN_POLL_INTERVAL,
        help="Minimum autosave interval in seconds. The adaptive timing will "
        "never go below this value. Defaults to 0.5 seconds.",
        config=True,
    )

    poll_interval_multiplier = Float(
        default_value=DEFAULT_POLL_INTERVAL_MULTIPLIER,
        help="Multiplier applied to save duration to calculate the next poll "
        "interval. For example, if a save takes 1 second and the multiplier is "
        "5.0, the next poll interval will be 5 seconds (bounded by min/max). "
        "Defaults to 5.0.",
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

    _adaptive_poll_interval: float
    """
    The current adaptive poll interval in seconds, calculated based on the last
    save duration and bounded by min_poll_interval and max_poll_interval.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the YRoomFileAPI instance.

        Parses the room_id to extract file format, type, and ID, then initializes
        internal state for content loading, saving, and adaptive timing.

        Args:
            *args: Positional arguments forwarded to LoggingConfigurable.
            **kwargs: Keyword arguments forwarded to LoggingConfigurable.
        """
        # Forward all arguments to parent class
        super().__init__(*args, **kwargs)

        # Bind instance attributes
        self.file_format, self.file_type, self.file_id = self.room_id.split(":")
        self._save_scheduled = False
        self._last_path = None
        self._last_modified = None
        self._stopped = False
        self._is_writable = True

        # Initialize content-related primitives
        self._content_loading = False
        self._content_load_event = asyncio.Event()
        self._content_lock = asyncio.Lock()

        # Initialize adaptive timing attributes
        self._adaptive_poll_interval = self.min_poll_interval
    
    @validate("min_poll_interval", "poll_interval_multiplier")
    def _validate_adaptive_timing_traits(self, proposal):
        trait_name = proposal['trait'].name
        value = proposal['value']

        if trait_name == "min_poll_interval":
            default_value = DEFAULT_MIN_POLL_INTERVAL
        else:
            default_value = DEFAULT_POLL_INTERVAL_MULTIPLIER

        if value <= 0:
            self.log.warning(
                f"`YRoomFileAPI.{trait_name}` must be >0. Received: {value}. "
                f"Reverting to default value {default_value}."
            )
            return default_value

        return proposal["value"]


    def get_path(self) -> str | None:
        """Get the current filesystem path for this file.

        Queries the FileIdManager to resolve the file_id to its current path.
        The path is relative to ServerApp.root_dir.

        Returns:
            The relative path to the file, or None if the file no longer exists.

        Raises:
            RuntimeError: If the file ID does not refer to a valid file path.
        """
        return self.fileid_manager.get_path(self.file_id)

    @property
    def room_id(self) -> str:
        """Get the room identifier from the parent YRoom.

        Returns:
            The room ID string in the format 'format:type:file_id'.
        """
        return self.parent.room_id

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        """Get the Jupyter Server's File ID Manager from the parent.

        Returns:
            The BaseFileIdManager instance for resolving file IDs to paths.
        """
        return self.parent.fileid_manager

    @property
    def contents_manager(self) -> ContentsManager:
        """Get the Jupyter Server's ContentsManager from the parent.

        Note:
            Any calls to methods on this manager should acquire and release
            the _content_lock to prevent concurrent read/write operations
            that could corrupt the file.

        Returns:
            The ContentsManager instance for file I/O operations.
        """
        return self.parent.contents_manager

    @property
    def outputs_manager(self) -> OutputsManager:
        """Get the OutputsManager from the parent.

        Returns:
            The OutputsManager instance for handling notebook outputs.
        """
        return self.parent.outputs_manager

    @property
    def content_loaded(self) -> bool:
        """Check if the YDoc content has finished loading.

        Returns:
            True if content is loaded, False otherwise.

        Note:
            To wait asynchronously for content to load, use
            `await file_api.until_content_loaded` instead.
        """
        return self._content_load_event.is_set()


    @property
    def until_content_loaded(self) -> Coroutine[Any, Any, Literal[True]]:
        """Get an awaitable that resolves when content finishes loading.

        Returns:
            A coroutine that can be awaited to block until content is loaded.

        Example:
            await file_api.until_content_loaded
            # Content is now loaded and safe to use
        """
        return self._content_load_event.wait()


    def load_content_into(self, jupyter_ydoc: YBaseDoc) -> None:
        """Load file content into the given JupyterYDoc.

        This method initiates asynchronous loading of the file content from disk
        into the provided YDoc. It is idempotent - calling it multiple times has
        no effect if loading is already in progress or complete.

        After calling this method, consumers should `await file_api.until_content_loaded`
        before performing operations on the YDoc.

        The method automatically starts the _watch_file() background task after
        content loading completes.

        Args:
            jupyter_ydoc: The YBaseDoc instance to load content into.
        """
        # If already loaded/loading, return immediately.
        # Otherwise, set loading to `True` and start the loading task.
        if self._content_load_event.is_set() or self._content_loading:
            return

        self._content_loading = True
        asyncio.create_task(self._load_content(jupyter_ydoc))


    async def _load_content(self, jupyter_ydoc: YBaseDoc) -> None:
        """Internal method to load file content asynchronously.

        Resolves the file path, loads content from ContentsManager, processes
        notebook outputs if applicable, and initializes the YDoc. Finally,
        starts the _watch_file() background task.

        Args:
            jupyter_ydoc: The YBaseDoc instance to load content into.

        Raises:
            RuntimeError: If the file path cannot be resolved from the file_id.
        """
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

        # The content manager uses this to tell consumers of the API if the file is writable.
        # We need to save this so we can use it during save.
        self._is_writable = file_data.get('writable', True)

        if self.file_type == "notebook":
            self.log.info(f"Processing outputs for loaded notebook: '{self.room_id}'.")
            file_data = self.outputs_manager.process_loaded_notebook(file_id=self.file_id, file_data=file_data)

        # Replace CRLF line terminators with LF line terminators
        # Fixes #176, see issue description for more context.
        content: str = file_data['content']
        if '\r\n' in content:
            self.log.warning(f"Detected CRLF line terminators in '{path}'.")
            content = content.replace('\r\n', '\n')
            self.log.info("Replaced CRLF line terminators with LF line terminators.")

        # Set JupyterYDoc content and set `dirty = False` to hide the "unsaved
        # changes" icon in the UI
        jupyter_ydoc.source = content
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
        """Schedule a save of the YDoc to disk.

        Sets a flag that causes the _watch_file() background task to save
        the YDoc on its next iteration. This is the preferred way to save
        changes during normal operation.

        Note:
            The actual save happens asynchronously in the _watch_file() loop.
            Multiple calls to schedule_save() before the save executes will
            result in only a single save operation.
        """
        self._save_scheduled = True
    
    async def _watch_file(self, jupyter_ydoc: YBaseDoc) -> None:
        """Background task that monitors the file and processes scheduled saves.

        This task runs continuously, performing the following on each iteration:
        1. Sleep for the adaptive poll interval
        2. Check for in-band and out-of-band file changes
        3. Save the YDoc if a save has been scheduled

        The poll interval adapts based on save duration to optimize performance:
        - Fast saves → shorter intervals (more responsive)
        - Slow saves → longer intervals (less overhead)

        The task is automatically started by _load_content() and runs until
        explicitly cancelled via stop().

        Args:
            jupyter_ydoc: The YBaseDoc instance being monitored and saved.

        Note:
            Saves are protected by asyncio.shield() to prevent corruption
            from cancellation during write operations.
        """

        while True:
            try:
                await asyncio.sleep(self._adaptive_poll_interval)
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
        """Check for file changes and handle in-band/out-of-band operations.

        This method is called before each save in the _watch_file() loop to detect
        and respond to file system changes. It distinguishes between:

        In-band operations (via ContentsManager):
        - Move: Detected via FileIdManager, logged as warning
        - Deletion: Detected via FileIdManager, calls parent.handle_inband_deletion()

        Out-of-band operations (external to Jupyter):
        - Move/deletion: Detected via 404 from ContentsManager, calls parent.handle_outofband_move()
        - Modification: Detected via last_modified timestamp, calls parent.handle_outofband_change()

        Raises:
            RuntimeError: If _last_path is not set (should never happen).
            HTTPError: If ContentsManager returns unexpected error (non-404).
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
        """Save the JupyterYDoc to disk immediately.

        This method performs a synchronous save operation, writing the YDoc
        content to the filesystem via ContentsManager. It also:
        - Processes notebook outputs through OutputsManager if applicable
        - Updates the last_modified timestamp
        - Clears the dirty flag on the YDoc
        - Calculates and updates the adaptive poll interval

        The method works even when the FileAPI is stopped, making it useful
        for final saves during shutdown.

        Args:
            jupyter_ydoc: The YBaseDoc instance to save.

        Note:
            In normal operation, consumers should use schedule_save() instead.
            Only call this directly when you need an immediate save while the
            FileAPI is stopped (e.g., during room shutdown).
        """
        # Record start time for adaptive timing
        start_time = time.perf_counter()

        try:
            # Return immediately if the content manager has marked this file as non-writable
            if not self._is_writable:
                return
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

            # Calculate save duration
            save_duration = time.perf_counter() - start_time

            # Calculate new adaptive interval
            old_interval = self._adaptive_poll_interval
            new_interval = save_duration * self.poll_interval_multiplier
            self._adaptive_poll_interval = max(
                self.min_poll_interval, new_interval
            )

            self.log.debug(
                f"Save completed for '{self.room_id}': "
                f"duration={save_duration:.3f}s, "
                f"old_interval={old_interval:.3f}s, "
                f"new_interval={new_interval:.3f}s, "
                f"adaptive_interval={self._adaptive_poll_interval:.3f}s"
            )

        except Exception as e:
            self.log.error("An exception occurred when saving JupyterYDoc.")
            self.log.exception(e)
    

    def stop(self) -> None:
        """Stop the FileAPI gracefully.

        Cancels the _watch_file() background task, immediately halting
        automatic saves. The FileAPI can still perform manual saves via
        the save() method after stopping.

        Note:
            To save pending changes after stopping, call `await file_api.save(jupyter_ydoc)`
            before the FileAPI is destroyed.
        """
        if self._watch_file_task:
            self._watch_file_task.cancel()
        self._stopped = True

    @property
    def stopped(self) -> bool:
        """Check if the FileAPI has been stopped.

        Returns:
            True if stop() has been called, False otherwise.
        """
        return self._stopped

    def restart(self) -> None:
        """Restart the FileAPI by resetting internal state.

        This method stops the FileAPI if running, then clears all state
        including content loading status, save scheduling, file metadata,
        and adaptive timing. After calling this, consumers must call
        load_content_into() again to resume normal operation.

        Note:
            Any pending saves are discarded when restarting.
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

        # Reset adaptive timing attributes
        self._adaptive_poll_interval = self.min_poll_interval

        self.log.info(f"Restarted FileAPI for room '{self.room_id}'.")



# File types that can be saved via ContentsManager
# See: https://github.com/jupyterlab/jupyter-collaboration/blob/main/projects/jupyter-server-ydoc/jupyter_server_ydoc/loaders.py#L146-L149
SAVEABLE_FILE_TYPES = {"directory", "file", "notebook"}
"""Set of file types that ContentsManager.save() accepts.

These types are recognized by Jupyter Server's ContentsManager for save operations.
Other types should be treated as generic 'file' type when saving.
"""
