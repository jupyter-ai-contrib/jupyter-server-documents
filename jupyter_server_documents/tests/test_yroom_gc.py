"""Garbage-collection tests for `YRoom` teardown.

`pycrdt` >= 0.14 / `yrs` >= 0.27 defers observer removal: dropping a subscription
only queues the callback for removal, and the queue is drained lazily on the next
observe/transaction. On an idle room being torn down that drain never happens, so
observer callbacks -- which are bound methods that capture the object they belong
to -- keep that object (and transitively the `YRoom` and its `YDoc`) alive. `YRoom`
works around this by draining observer removals on `stop()` (see
`yroom_utils.drain_observer_removals`).

These tests verify three distinct things can be garbage collected after a room is
stopped and dropped, each in its own suite so a future regression names its own
cause:

- `TestYRoomConsumerGC`     -- observer callbacks registered by *consumers* of the
                               room (at the doc / root / nested shared-type level).
- `TestYRoomGC`            -- the `YRoom` itself, for every shared model.
- `TestYRoomSharedModelGC`  -- the Jupyter YDoc *shared model* (the
                               `jupyter_ydoc.YBaseDoc` subclass, e.g. `YFile`,
                               `YNotebook`, `YChat`) the room wraps.

Stop modes exercised: `immediately=False` (graceful: drains the queue, schedules a
final save) and `immediately=True` (forced: drops pending updates, no save).
"""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import weakref
from typing import TYPE_CHECKING

import pycrdt
import pytest

if TYPE_CHECKING:
    from ...conftest import MakeYRoom


# Shared models to test. "chat" is provided by the optional `jupyterlab_chat`
# package; its parametrization is skipped when that package is not installed.
_HAS_JUPYTERLAB_CHAT = importlib.util.find_spec("jupyterlab_chat") is not None

_SHARED_MODEL_PARAMS = [
    pytest.param("file", id="file"),
    pytest.param("notebook", id="notebook"),
    pytest.param(
        "chat",
        id="chat",
        marks=pytest.mark.skipif(
            not _HAS_JUPYTERLAB_CHAT,
            reason="jupyterlab_chat is not installed",
        ),
    ),
]

_STOP_MODE_PARAMS = [
    pytest.param(False, id="graceful"),
    pytest.param(True, id="immediate"),
]


async def _stop_and_release(manager, room, *, immediately: bool) -> None:
    """Stop `room`, drop the manager's reference to it, and let background teardown
    tasks run -- mirroring `YRoomManager.delete_room` -- so the room becomes
    collectable. The caller must hold no other references to `room` afterward.
    """
    room_id = room.room_id
    room.stop(immediately=immediately)
    await room.until_saved
    # Mirror `YRoomManager.delete_room`: drop the manager's reference.
    manager._rooms_by_id.pop(room_id, None)


async def _collect() -> None:
    # `stop()` schedules background tasks (awareness stop, message-queue drain)
    # that transiently hold the room until the event loop runs them. Yield first,
    # then collect a few times (releasing a Rust-side ref can free a Python object
    # on the following pass).
    await asyncio.sleep(0)
    for _ in range(3):
        gc.collect()


class _Consumer:
    """Stand-in for a room consumer that observes the document via a bound method,
    so the registered callback captures ``self`` (the consumer)."""

    def __init__(self) -> None:
        self.events = 0

    def on_change(self, *args) -> None:
        self.events += 1


def _observe(ydoc: pycrdt.Doc, level: str, consumer: _Consumer):
    """Register ``consumer``'s bound-method observer at the requested level and
    return ``(target, subscription)`` so the caller can later unobserve."""
    if level == "doc":
        target = ydoc
        sub = ydoc.observe(consumer.on_change)
    elif level == "root":
        target = ydoc.get("source", type=pycrdt.Text)
        sub = target.observe(consumer.on_change)
    elif level == "nested":
        root = ydoc.get("root", type=pycrdt.Map)
        with ydoc.transaction():
            root["child"] = pycrdt.Map()
        target = root["child"]
        sub = target.observe(consumer.on_change)
    else:  # pragma: no cover - guard against typos in parametrization
        raise ValueError(f"unknown level {level!r}")
    return target, sub


class TestYRoomConsumerGC:
    """A consumer that observes a room and unobserves it is fully released once the
    room stops.

    A well-behaved consumer unregisters its observer before the room is torn down.
    Because ``yrs`` >= 0.27 defers observer removal, that ``unobserve()`` alone does
    not release the callback -- it only takes effect when the room's teardown drain
    flushes the pending-removal queue. These tests assert that, after the consumer
    unobserves and the room stops, the consumer and the ``YDoc`` are collected -- at
    every observer level and for both stop modes.
    """

    @pytest.mark.parametrize("level", ["doc", "root", "nested"])
    @pytest.mark.parametrize("immediately", _STOP_MODE_PARAMS)
    @pytest.mark.asyncio
    async def test_consumer_is_freed_after_stop(
        self, make_yroom: MakeYRoom, level: str, immediately: bool
    ):
        room = await make_yroom()
        manager = room.parent
        ydoc = await room.get_ydoc()

        consumer = _Consumer()
        target, sub = _observe(ydoc, level, consumer)
        consumer_ref = weakref.ref(consumer)
        doc_ref = weakref.ref(ydoc)

        # A well-behaved consumer unregisters its observer (deferred by yrs).
        target.unobserve(sub)

        del consumer, ydoc, target, sub
        await _stop_and_release(manager, room, immediately=immediately)
        del room
        await _collect()

        assert consumer_ref() is None, (
            f"consumer observing at {level!r} level was not freed after "
            f"stop(immediately={immediately})"
        )
        assert doc_ref() is None, (
            f"YDoc was not freed after stop(immediately={immediately}) with a "
            f"{level!r}-level observer"
        )


class TestYRoomGC:
    """The `YRoom` itself is garbage collected after it is stopped and dropped.

    This is the behavior a room's "freed" log message tracks. It must hold for
    every shared model, since the model's own internal observers (registered in
    its ``__init__``) would otherwise keep the room alive under deferred removal.
    """

    @pytest.mark.parametrize("file_type", _SHARED_MODEL_PARAMS)
    @pytest.mark.parametrize("immediately", _STOP_MODE_PARAMS)
    @pytest.mark.asyncio
    async def test_room_is_freed_after_stop(
        self, make_yroom: MakeYRoom, file_type: str, immediately: bool
    ):
        room = await make_yroom(file_type=file_type)
        manager = room.parent
        # Ensure the shared model is created/loaded, as it is in real usage.
        await room.get_jupyter_ydoc()

        room_ref = weakref.ref(room)

        await _stop_and_release(manager, room, immediately=immediately)
        del room
        await _collect()

        assert room_ref() is None, (
            f"YRoom for a {file_type!r} document was not garbage collected after "
            f"stop(immediately={immediately})"
        )


class TestYRoomSharedModelGC:
    """The Jupyter YDoc shared model (`YFile` / `YNotebook` / `YChat`, ...) is
    garbage collected after the room is stopped and dropped.

    Models inheriting from `jupyter_ydoc.YBaseDoc` register observers on their own
    shared types. If a model does not remove those on ``unobserve()``, the bound
    methods keep the model alive under deferred removal -- a leak this suite
    catches directly (independent of whether the `YRoom` is freed).
    """

    @pytest.mark.parametrize("file_type", _SHARED_MODEL_PARAMS)
    @pytest.mark.parametrize("immediately", _STOP_MODE_PARAMS)
    @pytest.mark.asyncio
    async def test_shared_model_is_freed_after_stop(
        self, make_yroom: MakeYRoom, file_type: str, immediately: bool
    ):
        room = await make_yroom(file_type=file_type)
        manager = room.parent
        jupyter_ydoc = await room.get_jupyter_ydoc()

        model_ref = weakref.ref(jupyter_ydoc)

        del jupyter_ydoc
        await _stop_and_release(manager, room, immediately=immediately)
        del room
        await _collect()

        assert model_ref() is None, (
            f"the shared model for a {file_type!r} document was not garbage "
            f"collected after stop(immediately={immediately})"
        )
