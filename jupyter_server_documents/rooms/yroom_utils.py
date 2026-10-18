"""Utilities for `YRoom`.

This module currently holds the observer-removal drain workaround. It is kept
separate from `yroom.py` because it is a **temporary workaround** for a bug in
pycrdt >= 0.14 / yrs >= 0.27 and is expected to be removed once that is fixed
upstream.
"""
from __future__ import annotations

from typing import Any

import pycrdt

def _noop(*args: Any) -> None:
    """Placeholder observer. Captures nothing, so its own deferred removal is
    harmless."""


def drain_observer_removals(ydoc: pycrdt.Doc) -> None:
    """
    Force `pycrdt`/`yrs` to release observer callbacks that have been unsubscribed.

    `yrs` >= 0.27 (pycrdt >= 0.14) defers observer removal: dropping a subscription
    only queues the callback for removal, and the queue is drained lazily on the
    next `observe`/transaction of that shared type. On an idle room being torn down
    that drain never happens, so the callbacks -- which (being bound methods)
    capture the owning `YRoom` and its `YDoc` -- are never released, leaking the
    whole room.

    This works around it by subscribing and immediately unsubscribing a no-op
    observer on the document and on every shared type reachable from it, which
    triggers `yrs` to drain the pending-removal queue for each. Unlike writing to
    the document, this changes no content and fires no observer callbacks, so it
    is safe even if a consumer (e.g. a `YChat` message observer) is still
    subscribed when the room is torn down.

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

    ydoc.unobserve(ydoc.observe(_noop))
    for node in nodes:
        node.unobserve(node.observe(_noop))
        node.unobserve(node.observe_deep(_noop))
