"""
Kernel state probing via dual-channel kernel_info_request.

The nudge determines whether a running kernel is idle or busy by sending
kernel_info_request on both the shell and control channels simultaneously.
Control bypasses the execution queue and always replies; shell is blocked
while a cell is executing.

  control + shell reply  → "idle"
  control reply only     → "busy"
  no reply within timeout → "unknown"

Also listens for iopub_welcome (JEP #65 / ipykernel >= 7.2.0), which arrives
~5 ms after connection on XPUB-capable kernels and allows early termination
of the wait before the shell_window expires.

This follows the same approach used in jupyter_server for detecting kernel
state on reconnect, generalised so it can be called from any context that
has an AsyncKernelClient — not just the WebSocket handler.
"""
from __future__ import annotations

import asyncio
import json
import typing as t


async def nudge_kernel(
    client,
    *,
    kernel_info_timeout: float = 5.0,
    kernel_info_reply_window: float = 0.2,
    pending_tasks: t.Set[asyncio.Task] | None = None,
) -> str:
    """Probe a kernel's busy/idle state and return one of "idle", "busy", or "unknown".

    Args:
        client: A started AsyncKernelClient (channels must already be running).
        kernel_info_timeout: Overall deadline in seconds.  Increase for
            high-latency or slow-starting remote kernels.
        kernel_info_reply_window: After the control channel replies, how many
            additional seconds to wait for the shell channel before declaring
            the kernel busy.  Covers network jitter; idle kernels reply on
            both channels nearly simultaneously (<50 ms locally).
        pending_tasks: Optional set to register the internal probe tasks into.
            The caller can cancel() all tasks in this set if it needs to abort
            the probe early (e.g. WebSocket disconnect before nudge completes).
            Tasks are removed from the set when the nudge finishes.
    """
    session = client.session
    shell_socket = client.shell_channel.socket
    control_socket = client.control_channel.socket
    iopub_socket = client.iopub_channel.socket

    session.send(shell_socket, session.msg("kernel_info_request"))
    session.send(control_socket, session.msg("kernel_info_request"))

    async def recv_reply(socket) -> bool:
        try:
            msg_list = await socket.recv_multipart()
            _, fed = session.feed_identities(msg_list)
            if len(fed) < 2:
                return False
            return json.loads(fed[1]).get("msg_type") == "kernel_info_reply"
        except Exception:
            return False

    async def recv_welcome() -> bool:
        """Listen for iopub_welcome with a short inner timeout.

        Capped at kernel_info_reply_window so it doesn't delay probing on
        kernels that don't support XPUB (ipykernel < 7.2.0).
        """
        try:
            msg_list = await asyncio.wait_for(
                iopub_socket.recv_multipart(),
                timeout=kernel_info_reply_window,
            )
            _, fed = session.feed_identities(msg_list)
            if len(fed) < 2:
                return False
            return json.loads(fed[1]).get("msg_type") == "iopub_welcome"
        except (asyncio.TimeoutError, Exception):
            return False

    shell_task = asyncio.create_task(recv_reply(shell_socket))
    control_task = asyncio.create_task(recv_reply(control_socket))
    welcome_task = asyncio.create_task(recv_welcome())

    tasks = {shell_task, control_task, welcome_task}
    if pending_tasks is not None:
        pending_tasks.update(tasks)

    deadline = asyncio.get_event_loop().time() + kernel_info_timeout
    active = set(tasks)

    try:
        while active:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break

            done, active = await asyncio.wait(
                active,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                break  # deadline reached

            if control_task.done():
                # Control replied — wait up to kernel_info_reply_window for
                # shell to also reply (idle confirmation).
                if not shell_task.done():
                    shell_remaining = min(
                        kernel_info_reply_window,
                        deadline - asyncio.get_event_loop().time(),
                    )
                    if shell_remaining > 0:
                        await asyncio.wait(
                            [t for t in active if t is shell_task],
                            timeout=shell_remaining,
                        )
                break

            # Only welcome (or nothing useful) arrived — keep waiting.

    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        if pending_tasks is not None:
            pending_tasks.difference_update(tasks)

    def _result(task) -> bool:
        if task.done() and not task.cancelled():
            try:
                return bool(task.result())
            except Exception:
                return False
        return False

    control_replied = _result(control_task)
    shell_replied = _result(shell_task)

    if control_replied and shell_replied:
        return "idle"
    elif control_replied:
        return "busy"
    else:
        return "unknown"
