"""Utilities for `YRoom`.

This module currently holds the observer-removal drain workaround. It is kept
separate from `yroom.py` because it is a **temporary workaround** for a bug in
pycrdt >= 0.14 / yrs >= 0.27 and is expected to be removed once that is fixed
upstream.
"""
from __future__ import annotations

from typing import Any

import pycrdt

# Sentinel key/value used by `drain_observer_removals()`. Chosen to be extremely
# unlikely to collide with real document content.
GC_DRAIN_SENTINEL = "__jsd_gc_drain_sentinel__"


def drain_observer_removals(ydoc: pycrdt.Doc) -> None:
    """
    Force `pycrdt`/`yrs` to release observer callbacks that have been unsubscribed.

    `yrs` >= 0.27 (pycrdt >= 0.14) defers observer removal: dropping a subscription
    only queues the callback for removal, and the queue is drained lazily on the
    next `observe`/transaction of that shared type. On an idle room being torn down
    that drain never happens, so the callbacks -- which (being bound methods)
    capture the owning `YRoom` and its `YDoc` -- are never released, leaking the
    whole room.

    This works around it by committing a content-neutral mutation (and immediately
    reverting it) on every shared type reachable from the document, which triggers
    `yrs` to drain the pending-removal queue for each. The write+revert is a true
    no-op from the content/persistence perspective (JSD does not persist YDoc
    history). Callers should invoke this only after all clients are disconnected
    and the file API is stopped, so no client or save observes the transient state.

    This is a temporary workaround; remove it once deferred observer removal is
    fixed upstream.
    """
    Map = pycrdt.Map
    Array = pycrdt.Array
    Text = pycrdt.Text

    # Collect every shared type reachable from the document roots (BFS). We must
    # touch nested shared types too, since consumers may observe them.
    nodes: list[Any] = []
    frontier: list[Any] = [value for _, value in ydoc.items()]
    while frontier:
        node = frontier.pop()
        nodes.append(node)
        if isinstance(node, Map):
            for key in list(node.keys()):
                value = node[key]
                if isinstance(value, (Map, Array, Text)):
                    frontier.append(value)
        elif isinstance(node, Array):
            for value in list(node):
                if isinstance(value, (Map, Array, Text)):
                    frontier.append(value)

    if not nodes:
        return

    def touch(node: Any) -> None:
        if isinstance(node, Text):
            node += "\x00"
        elif isinstance(node, Map):
            node[GC_DRAIN_SENTINEL] = 1
        elif isinstance(node, Array):
            node.append(None)

    def revert(node: Any) -> None:
        if isinstance(node, Text):
            del node[len(node) - 1 : len(node)]
        elif isinstance(node, Map):
            del node[GC_DRAIN_SENTINEL]
        elif isinstance(node, Array):
            del node[len(node) - 1 : len(node)]

    with ydoc.transaction():
        for node in nodes:
            touch(node)
    with ydoc.transaction():
        for node in nodes:
            revert(node)
