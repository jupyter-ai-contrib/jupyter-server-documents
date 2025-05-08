import typing
from . import types

EXECUTION_STATES: typing.Tuple[types.EXECUTION_STATES] = typing.get_args(types.EXECUTION_STATES)
LIFECYCLE_STATES: typing.Tuple[types.LIFECYCLE_STATES] = typing.get_args(types.LIFECYCLE_STATES)
LIFECYCLE_DEAD_STATES = ["dead", "disconnected", "terminated"]