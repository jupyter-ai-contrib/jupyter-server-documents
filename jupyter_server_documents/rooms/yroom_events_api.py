from __future__ import annotations
from jupyter_events import EventLogger
from jupyter_server_fileid.manager import BaseFileIdManager
from traitlets.config import LoggingConfigurable
from typing import TYPE_CHECKING

from ..events import JSD_ROOM_EVENT_URI

if TYPE_CHECKING:
    from .yroom import YRoom
    from typing import Literal, Optional
    import logging

class YRoomEventsAPI(LoggingConfigurable):
    """
    An API object that provides methods to emit events on the
    `jupyter_events.EventLogger` singleton in `jupyter_server`. This class
    requires only a single argument: `parent: YRoom`.

    JSD room and awareness events have the same structure as
    `jupyter_collaboration` v4 session and awareness events and emit on the same
    schema IDs. Fork events are not emitted.

    The event schemas must be registered via
    `event_logger.register_event_schema()` in advance. This should be done when
    the server extension initializes.
    """

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

    @property
    def room_id(self) -> str:
        return self.parent.room_id
    
    @property
    def event_logger(self) -> EventLogger:
        return self.parent.event_logger
    
    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self.parent.fileid_manager

    def emit_room_event(
        self,
        action: Literal["initialize", "load", "save", "overwrite", "clean"],
        level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]] = "INFO"
    ):
        """
        Emits a room event. This method is guaranteed to log any caught
        exceptions and never raise them to the `YRoom`.
        """
        try:
            path = self._get_path()
            event_data = {
                "level": level,
                "room": self.room_id,
                "path": path,
                "action": action
            }

            # TODO: Jupyter AI requires the `msg` field to be set to 'Room
            # initialized' on 'initialize' room events. Remove this when the
            # Jupyter AI issue is fixed.
            if action == "initialize":
                event_data["msg"] = "Room initialized"
            self.event_logger.emit(schema_id=JSD_ROOM_EVENT_URI, data=event_data)
        except:
            self.log.exception("Exception occurred when emitting a room event.")

    def emit_awareness_event(self):
        """
        TODO
        """
        pass


    def _get_path(self) -> str:
        """
        Returns the relative path to the file by querying the FileIdManager. The
        path is relative to the `ServerApp.root_dir` configurable trait.
        """
        # Query for the path from the file ID in the room ID
        file_id = self.room_id.split(":")[-1]
        rel_path = self.fileid_manager.get_path(file_id)

        # Raise exception if the path could not be found, then return
        assert rel_path is not None
        return rel_path