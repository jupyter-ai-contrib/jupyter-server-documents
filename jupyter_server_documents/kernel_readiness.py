"""Waiting for a kernel manager to become connectable.

Some provisioners launch kernels asynchronously — e.g. any kernel manager
with ``use_pending_kernels=True`` on the MultiKernelManager. In those
setups, ``start_kernel_for_session`` returns before the provisioner has
assigned ZMQ ports on the kernel process. Consumers that open sockets
against the manager's connection info before ports are populated bind
to port 0 and receive no kernel messages.

This module exposes a single utility, ``wait_for_kernel_ready``, that
blocks until ``kernel_manager.get_connection_info()`` reports real port
assignments. It also checks ``kernel_manager.ready`` for a resolved
exception so provisioner failures surface immediately rather than after
the full timeout.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 60.0
_POLL_INTERVAL_SECONDS = 0.1


class KernelNotReachableError(RuntimeError):
    """The kernel manager did not populate ZMQ ports in time."""


async def wait_for_kernel_ready(
    kernel_manager: Any,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Block until the kernel manager is ready to serve ZMQ traffic.

    Two gates are checked, in order:

    1. If ``kernel_manager.ready`` is a Future that is still pending,
       wait — ``get_connection_info()`` may still be reporting the
       previous kernel's stale ports during a (re)start.
    2. Once ``ready`` has resolved (or is absent), poll
       ``kernel_manager.get_connection_info()`` until ``shell_port`` is
       a truthy non-zero value.

    If ``ready`` resolves with an exception, that exception is
    re-raised immediately (fast-fail on provisioner error rather than
    waiting the full timeout).

    Parameters
    ----------
    kernel_manager
        Any object with ``get_connection_info() -> dict``. Optionally has
        a ``ready`` attribute that is a ``concurrent.futures.Future`` or
        ``asyncio.Future``; if present, its resolution is awaited before
        connection info is trusted.
    timeout
        Deadline in seconds. Callers should pass an explicit value; the
        module default matches jupyter_server's
        ``AsyncMappingKernelManager.kernel_info_timeout`` default (60s).

    Returns
    -------
    dict
        The fresh connection info once both gates pass.

    Raises
    ------
    KernelNotReachableError
        If ``timeout`` elapses without ports being assigned.
    Exception
        Whatever exception was set on ``kernel_manager.ready``.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        ready = getattr(kernel_manager, "ready", None)
        ready_resolved = True
        if ready is not None and hasattr(ready, "done"):
            if ready.done() and not _is_cancelled(ready):
                exc = ready.exception()
                if exc is not None:
                    raise exc
            else:
                ready_resolved = False

        if ready_resolved:
            info = kernel_manager.get_connection_info()
            if info.get("shell_port"):
                return info

        if loop.time() > deadline:
            kernel_id = getattr(kernel_manager, "kernel_id", "<unknown>")
            raise KernelNotReachableError(
                f"Kernel {kernel_id} did not assign ZMQ ports within "
                f"{timeout}s"
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _is_cancelled(future: Any) -> bool:
    """Return True if ``future`` is a cancelled Future.

    Handles both ``asyncio.Future`` and ``concurrent.futures.Future``.
    Any error accessing the cancelled state is treated as "not
    cancelled" — a resolved-and-usable future is a safer default than
    raising through the caller's polling loop.
    """
    cancelled = getattr(future, "cancelled", None)
    if cancelled is None:
        return False
    try:
        return bool(cancelled())
    except Exception:
        return False
