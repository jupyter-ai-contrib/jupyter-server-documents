import typing 


LIFECYCLE_STATES = typing.Literal[
    "unknown",
    "starting",
    "started",
    "terminating",
    "terminated",
    "connecting",
    "connected",
    "restarting",
    "restarted",
    "disconnected",
    "dead"
]

EXECUTION_STATES = typing.Literal[
    "busy", 
    "idle", 
    "starting", 
    "unknown", 
    "dead"
]
