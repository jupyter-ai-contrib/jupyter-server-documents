from pathlib import Path
from typing import Literal

EVENTS_DIR = Path(__file__).parent

# Use the same schema ID as `jupyter_collaboration` for compatibility
JSD_ROOM_EVENT_URI = "https://schema.jupyter.org/jupyter_collaboration/session/v1"
JSD_AWARENESS_EVENT_URI = "https://schema.jupyter.org/jupyter_collaboration/awareness/v1"

JSD_ROOM_EVENT_SCHEMA = EVENTS_DIR / "room.yaml"
JSD_AWARENESS_EVENT_SCHEMA = EVENTS_DIR / "awareness.yaml"

type EventLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

type RoomAction = Literal["initialize", "load", "save", "overwrite", "clean"]
