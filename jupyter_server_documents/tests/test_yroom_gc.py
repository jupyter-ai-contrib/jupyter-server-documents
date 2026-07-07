"""Garbage-collection tests for `YRoom` teardown.

These verify that when a room stops, observer callbacks registered by *consumers*
of the room -- and the objects those callbacks capture -- are released, so the
consumer, the room, and the underlying `YDoc` can be garbage collected.

This matters because `pycrdt` >= 0.14 / `yrs` >= 0.27 defers observer removal, so
without `YRoom`'s teardown drain (see `yroom_utils.drain_observer_removals`) an
observing consumer would keep the whole room alive after `stop()`. See the
companion `test_yroom_utils.py` for direct tests of the drain itself.

Matrix: 3 observer levels x 2 stop modes.

Levels:
  - doc      : consumer observes the `Doc` directly (`ydoc.observe`).
  - root     : consumer observes a root shared type (`ydoc.get("source", Text)`).
  - nested   : consumer observes a shared type nested inside another.

Stop modes:
  - immediately=False : graceful stop (drains queue, schedules a final save).
  - immediately=True  : forced stop (drops pending updates, no save).
"""

from __future__ import annotations

import asyncio
import gc
import uuid
import weakref
from pathlib import Path
from typing import TYPE_CHECKING

import pycrdt
import pytest

if TYPE_CHECKING:
    from ...conftest import MakeYRoomManager


class _Consumer:
    """Stand-in for a room consumer that observes the document via a bound method,
    so the registered callback captures ``self`` (the consumer)."""

    def __init__(self) -> None:
        self.events = 0

    def on_change(self, *args) -> None:
        self.events += 1


async def _make_document_room(manager, tmp_path: Path):
    path = tmp_path / f"{uuid.uuid4()}.txt"
    path.touch()
    file_id = manager.fileid_manager.index(str(path))
    room_id = f"text:file:{file_id}"
    room = manager.create_room(room_id, inactivity_timeout=1)
    await room.file_api.until_content_loaded
    return room


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
    """A consumer that observes a room and unobserves it is fully released once
    the room stops.

    A well-behaved consumer unregisters its observer before the room is torn down.
    Because ``yrs`` >= 0.27 defers observer removal, that ``unobserve()`` alone
    does not release the callback -- it only takes effect when the room's teardown
    drain flushes the pending-removal queue. These tests assert that, after the
    consumer unobserves and the room stops, the consumer and the ``YDoc`` are
    garbage collected -- at every observer level and for both stop modes.
    """

    @pytest.mark.parametrize("level", ["doc", "root", "nested"])
    @pytest.mark.parametrize("immediately", [False, True], ids=["graceful", "immediate"])
    @pytest.mark.asyncio
    async def test_consumer_is_freed_after_stop(
        self,
        make_yroom_manager: MakeYRoomManager,
        tmp_path: Path,
        level: str,
        immediately: bool,
    ):
        manager = make_yroom_manager(auto_free_interval=1)
        room = await _make_document_room(manager, tmp_path)
        ydoc = await room.get_ydoc()

        consumer = _Consumer()
        target, sub = _observe(ydoc, level, consumer)
        consumer_ref = weakref.ref(consumer)
        doc_ref = weakref.ref(ydoc)

        # A well-behaved consumer unregisters its observer (deferred by yrs).
        target.unobserve(sub)

        room_id = room.room_id
        del consumer, ydoc, target, sub
        room.stop(immediately=immediately)
        await room.until_saved
        # Mirror `YRoomManager.delete_room`: drop the manager's reference so the
        # room is no longer retained after it has stopped.
        manager._rooms_by_id.pop(room_id, None)
        del room

        # `stop()` schedules background tasks (e.g. `awareness.stop()`, draining the
        # message-queue processor) that transiently hold the room until the event
        # loop runs them. Yield so they complete before checking collectability.
        await asyncio.sleep(0)
        for _ in range(3):
            gc.collect()

        assert consumer_ref() is None, (
            f"consumer observing at {level!r} level was not freed after "
            f"stop(immediately={immediately})"
        )
        assert doc_ref() is None, (
            f"YDoc was not freed after stop(immediately={immediately}) with a "
            f"{level!r}-level observer"
        )
