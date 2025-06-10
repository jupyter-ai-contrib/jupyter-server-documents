from jupyter_events import EventLogger
from ..events import JSD_ROOM_EVENT_URI
from typing import Optional
from jupyter_server_fileid.manager import BaseFileIdManager
from logging import Logger
from typing import Literal


class YRoomEventsAPI:
    """
    Class that provides an API to emit events to the
    `jupyter_events.EventLogger` singleton in `jupyter_server`.

    JSD room and awareness events have the same structure as
    `jupyter_collaboration` v4 session and awareness events and emit on the same
    schema IDs. Fork events are not emitted.

    The event schemas must be registered via
    `event_logger.register_event_schema()` in advance. This should be done when
    the server extension initializes.
    """

    _event_logger: EventLogger
    _fileid_manager: BaseFileIdManager
    room_id: str
    log: Logger

    def __init__(self, event_logger: EventLogger, fileid_manager: BaseFileIdManager, room_id: str, log: Logger):
        self._event_logger = event_logger
        self._fileid_manager = fileid_manager
        self.room_id = room_id
        self.log = log
    
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
            self._event_logger.emit(schema_id=JSD_ROOM_EVENT_URI, data=event_data)
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
        rel_path = self._fileid_manager.get_path(file_id)

        # Raise exception if the path could not be found, then return
        assert rel_path is not None
        return rel_path