"""Tests for `jupyter_server_documents.rooms.yroom_utils`.

These test `drain_observer_removals()` directly against a `pycrdt.Doc`, without a
`YRoom`. It is the workaround for deferred observer removal in pycrdt >= 0.14 /
yrs >= 0.27 (dropping a subscription only *queues* removal; the queue drains lazily
on the next observe/transaction, so on an idle document it never drains). See
`yroom_utils` for details, and `test_yroom_gc.py` for the room-level behavior.
"""

from __future__ import annotations

import gc
import weakref

import pycrdt
import pytest

from jupyter_server_documents.rooms.yroom_utils import (
    GC_DRAIN_SENTINEL,
    drain_observer_removals,
)


class _Owner:
    """Observer owner whose bound-method callback captures ``self`` (and, via
    pycrdt's wrapping, the ``Doc``)."""

    def on_change(self, *args) -> None:
        pass


def _observe(ydoc: pycrdt.Doc, level: str, owner: _Owner):
    """Register ``owner``'s observer at the given level; return ``(target, sub)``."""
    if level == "doc":
        target = ydoc
        sub = ydoc.observe(owner.on_change)
    elif level == "root":
        target = ydoc.get("source", type=pycrdt.Text)
        sub = target.observe(owner.on_change)
    elif level == "nested":
        root = ydoc.get("root", type=pycrdt.Map)
        with ydoc.transaction():
            root["child"] = pycrdt.Map()
        target = root["child"]
        sub = target.observe(owner.on_change)
    else:  # pragma: no cover
        raise ValueError(level)
    return target, sub


class TestDrainObserverRemovals:
    @pytest.mark.parametrize("level", ["doc", "root", "nested"])
    def test_drain_releases_unobserved_callback(self, level: str):
        """After a consumer unobserves (deferred) and the drain runs, the observer
        owner is released -- proving the drain reached that shared type. Covers
        doc-level, root, and nested shared types."""
        ydoc = pycrdt.Doc()
        owner = _Owner()
        target, sub = _observe(ydoc, level, owner)
        owner_ref = weakref.ref(owner)

        # Consumer unobserves; yrs defers the actual removal.
        target.unobserve(sub)
        # Without a drain the callback would remain, keeping `owner` alive.
        drain_observer_removals(ydoc)

        del owner, target, sub
        for _ in range(3):
            gc.collect()
        assert owner_ref() is None, (
            f"drain did not release a {level!r}-level observer's owner"
        )

    def test_drain_without_prior_drain_leaks(self):
        """Control: without the drain, a deferred unobserve leaves the owner alive.
        Confirms the test above is actually exercising the drain, not GC alone."""
        ydoc = pycrdt.Doc()
        owner = _Owner()
        target, sub = _observe(ydoc, "root", owner)
        owner_ref = weakref.ref(owner)

        target.unobserve(sub)  # deferred; no drain

        del owner, target, sub
        for _ in range(3):
            gc.collect()
        assert owner_ref() is not None, (
            "expected the owner to leak without a drain (deferred removal); if this "
            "fails, pycrdt/yrs may no longer defer and the workaround can be removed"
        )

    def test_drain_preserves_content_and_leaves_no_sentinel(self):
        """The write+revert must be content-neutral across every shared type kind
        and must not leave the drain sentinel behind."""
        ydoc = pycrdt.Doc()
        text = ydoc.get("source", type=pycrdt.Text)
        mp = ydoc.get("meta", type=pycrdt.Map)
        arr = ydoc.get("cells", type=pycrdt.Array)
        with ydoc.transaction():
            text += "hello"
            mp["k"] = "v"
            arr.append(1)
            arr.append(2)

        drain_observer_removals(ydoc)

        assert str(text) == "hello"
        assert dict(mp.to_py()) == {"k": "v"}
        assert list(arr.to_py()) == [1, 2]
        assert GC_DRAIN_SENTINEL not in dict(mp.to_py())

    def test_drain_is_safe_on_empty_document(self):
        """Draining a document with no root types (nothing to touch) is a no-op."""
        ydoc = pycrdt.Doc()
        drain_observer_removals(ydoc)  # must not raise

    def test_drain_touches_doc_root_and_nested(self):
        """A single drain call releases observers at all three levels at once,
        confirming it traverses doc-level, root, and nested shared types in one
        pass."""
        ydoc = pycrdt.Doc()
        owners = {level: _Owner() for level in ("doc", "root", "nested")}
        targets = {}
        for level, owner in owners.items():
            target, sub = _observe(ydoc, level, owner)
            targets[level] = (target, sub)
        refs = {level: weakref.ref(o) for level, o in owners.items()}

        for target, sub in targets.values():
            target.unobserve(sub)
        drain_observer_removals(ydoc)

        del owners, targets, owner, target, sub
        for _ in range(3):
            gc.collect()
        leaked = [level for level, ref in refs.items() if ref() is not None]
        assert not leaked, f"drain missed observers at levels: {leaked}"
