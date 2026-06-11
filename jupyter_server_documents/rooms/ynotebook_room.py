"""
YNotebookRoom — a YRoom subclass that owns a kernel connection and
provides server-side cell execution.

Keeping kernel-related state and methods in a dedicated subclass means:
- YRoom stays focused on collaborative document sync
- Consumers can do isinstance(room, YNotebookRoom) before calling
  connect_kernel() or execute_cell(), preventing runtime errors when
  a room serves a text file or chat document instead of a notebook
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Optional
import asyncio
from dataclasses import dataclass

from .yroom import YRoom

if TYPE_CHECKING:
    from jupyter_client.asynchronous.client import AsyncKernelClient
    from ..outputs.output_processor import OutputProcessor


@dataclass
class _ExecutionItem:
    """A cell execution request queued for the YNotebookRoom execution worker."""
    cell_id: str
    ycell: Any
    file_id: str
    clear_outputs: bool
    timeout: Optional[float]


class YNotebookRoom(YRoom):
    """
    A YRoom subclass that connects to a Jupyter kernel and supports
    server-side cell execution.

    Use connect_kernel() after creating a session and disconnect_kernel()
    when the session ends.  execute_cell() enqueues a cell for fire-and-forget
    execution; outputs and execution state are written directly into the YDoc
    so all connected clients see them via normal Yjs sync.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Kernel connection state — set by connect_kernel(), cleared by disconnect_kernel()
        self._kernel_client: AsyncKernelClient | None = None
        self._kernel_manager = None
        self._shell_confirmed: bool = False
        self._execution_queue: asyncio.Queue | None = None
        self._execution_worker_task: asyncio.Task | None = None
        self.output_processor: OutputProcessor | None = None

    # ── Kernel client lifecycle ───────────────────────────────────────────────────

    async def connect_kernel(self, kernel_manager) -> None:
        """Attach this room to a running kernel.

        If already connected, disconnects cleanly before reconnecting.
        Creates a fresh client (independent session to avoid ZMQ DEALER
        identity collisions), waits for heartbeat, starts the execution
        queue + worker, then fetches kernel info.
        """
        from ..outputs import OutputProcessor

        if self._kernel_client is not None:
            await self.disconnect_kernel()

        self._kernel_manager = kernel_manager
        kernel_manager.add_restart_callback(self._on_kernel_restart, "restart")
        kernel_manager.add_restart_callback(self._on_kernel_dead, "dead")

        await self._connect_client(kernel_manager)

        # Start queue + worker BEFORE fetching kernel_info so that execute_cell()
        # can enqueue items immediately.  Items wait in the worker until
        # _shell_confirmed is True (set by _fetch_kernel_info below).
        if self._execution_worker_task is None or self._execution_worker_task.done():
            self._execution_queue = asyncio.Queue()
            self._execution_worker_task = asyncio.create_task(
                self._execution_worker()
            )

        # Fetch kernel_info in this coroutine (not the worker) to avoid
        # pyzmq asyncio recv cancellation issues inside asyncio Tasks.
        await self._fetch_kernel_info()

    async def disconnect_kernel(self) -> None:
        """Detach from the kernel. Cancels the execution worker and drains the queue."""
        if self._kernel_manager is not None:
            try:
                self._kernel_manager.remove_restart_callback(self._on_kernel_restart, "restart")
                self._kernel_manager.remove_restart_callback(self._on_kernel_dead, "dead")
            except Exception:
                pass

        # Cancel the worker BEFORE draining the queue.  If we drained first
        # the still-running worker could pick items off the queue between our
        # get_nowait() calls, leaving the queue non-empty after we finish.
        if self._execution_worker_task is not None and not self._execution_worker_task.done():
            self._execution_worker_task.cancel()
            try:
                await self._execution_worker_task
            except asyncio.CancelledError:
                pass
        self._execution_worker_task = None

        if self._execution_queue is not None:
            while not self._execution_queue.empty():
                try:
                    item = self._execution_queue.get_nowait()
                    item.ycell["execution_state"] = "idle"
                    self._execution_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            self._execution_queue = None

        if self._kernel_client is not None:
            self._kernel_client.stop_channels()
            self._kernel_client = None

        self._kernel_manager = None
        self._shell_confirmed = False

    async def _on_kernel_restart(self) -> None:
        # Save the kernel manager before disconnect_kernel() nulls it out,
        # so we can pass it back to connect_kernel() below.
        km = self._kernel_manager
        await self.disconnect_kernel()
        if km is not None:
            await self.connect_kernel(km)

    async def _on_kernel_dead(self) -> None:
        await self.disconnect_kernel()

    # ── Internal client helpers ───────────────────────────────────────────────────

    async def _connect_client(self, kernel_manager) -> None:
        """Create a fresh ZMQ client, connect it, and wait for heartbeat.

        Shared by connect_kernel().  Does NOT touch the execution queue or worker.

        We use kernel_manager.client_factory (the configured client class) rather
        than hardcoding AsyncKernelClient.  This respects whatever client_class the
        user or the kernel manager has set, keeping our instantiation consistent
        with the rest of the jupyter_client stack.

        We do NOT use kernel_manager.client() even though it also uses client_factory
        internally.  client() clones the manager's session, giving every client the
        same ZMQ DEALER identity.  The kernel's ROUTER then routes execute_reply to
        the wrong socket.  Instantiating client_factory directly gives us an
        independent session and correct reply routing.
        """
        from ..outputs import OutputProcessor

        client_class = kernel_manager.client_factory
        try:
            self._kernel_client = client_class(
                parent=kernel_manager,
                config=getattr(kernel_manager, "config", None),
            )
        except Exception:
            # parent might not be a Configurable (e.g. in tests)
            self._kernel_client = client_class()

        connection_info = kernel_manager.get_connection_info()
        self._kernel_client.load_connection_info(connection_info)
        # start_channels() with default hb=True — we need heartbeat running
        # so _async_is_alive() works for the liveness check below.
        self._kernel_client.start_channels()
        self.output_processor = OutputProcessor(parent=self)
        self.output_processor.use_outputs_service = False
        self._shell_confirmed = False

        # The heartbeat channel starts paused; unpause it before polling.
        # Without this _async_is_alive() always returns False.
        self._kernel_client.hb_channel.unpause()
        deadline = asyncio.get_event_loop().time() + 30.0
        while not await self._kernel_client._async_is_alive():
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError(
                    f"Kernel heartbeat timeout "
                    f"(shell_port={connection_info.get('shell_port')})"
                )
            await asyncio.sleep(0.2)

    async def _fetch_kernel_info(self) -> None:
        """Wait for the kernel to be fully ready (shell + iopub both confirmed).

        _async_wait_for_ready() sends kernel_info_request, reads the shell reply,
        AND confirms iopub is receiving messages before returning. This is all
        we need — no second kernel_info call needed, which was leaving stale
        iopub messages in the buffer and risking shell socket corruption via
        the Python 3.12 + asyncio.wait_for + pyzmq cancellation bug.

        IMPORTANT: this must be called from a regular coroutine context
        (i.e. from connect_kernel), NOT from inside an asyncio.Task.  When
        asyncio.wait_for cancels the inner coroutine inside a Task, pyzmq's
        socket asyncio registration can be corrupted, causing all subsequent
        recv calls on that socket to hang indefinitely.
        """
        try:
            assert self._kernel_client is not None
            await asyncio.wait_for(
                self._kernel_client._async_wait_for_ready(), timeout=30.0
            )
        except Exception as e:
            self.log.warning("_fetch_kernel_info: failed: %s", e)
            return

        self._shell_confirmed = True

    # ── Execution queue and worker ────────────────────────────────────────────────

    async def _execution_worker(self) -> None:
        """Process queued cell executions one at a time."""
        assert self._execution_queue is not None
        try:
            while True:
                item = await self._execution_queue.get()
                try:
                    # Wait for kernel_info to be fetched (connect_kernel is async).
                    if not self._shell_confirmed:
                        wait_deadline = asyncio.get_event_loop().time() + 60.0
                        while not self._shell_confirmed:
                            if asyncio.get_event_loop().time() > wait_deadline:
                                item.ycell["execution_state"] = "idle"
                                self.log.warning("Timed out waiting for kernel to be ready")
                                break
                            await asyncio.sleep(0.2)
                        if not self._shell_confirmed:
                            continue

                    await self._run_item(item)

                except asyncio.CancelledError:
                    # Worker was cancelled (kernel disconnect or server shutdown).
                    # Reset the in-flight cell before re-raising so the UI
                    # doesn't stay stuck showing [*].
                    item.ycell["execution_state"] = "idle"
                    raise
                except Exception as e:
                    item.ycell["execution_state"] = "idle"
                    self.log.error("Execution worker error for cell %s: %s", item.cell_id, e)
                finally:
                    self._execution_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _run_item(self, item: _ExecutionItem) -> None:
        """Execute one queued cell using execute_interactive."""
        ycell = item.ycell

        if item.clear_outputs:
            # Use in-place deletion, NOT ycell["outputs"] = [].
            # Assigning a plain list would replace the pycrdt Array with a
            # Python list, breaking YDoc sync for all connected clients.
            del ycell["outputs"][:]
        # (outputs already cleared in execute_cell at enqueue time)

        self.log.debug("_run_item: cell_id=%r", item.cell_id)
        output_processor = self.output_processor
        # Capture execution_count from execute_input but don't write it yet.
        # Writing it immediately triggers executionCountChange on the frontend
        # which sets executionState='idle', clearing [*] before the cell finishes.
        # We write it atomically with execution_state='idle' after completion.
        _execution_count = None

        def output_hook(msg: dict) -> None:
            nonlocal _execution_count
            msg_type = msg["header"]["msg_type"]
            content = msg.get("content", {})
            if msg_type == "status":
                state = content.get("execution_state", "")
                # Map kernel status:idle → YDoc "idle".
                # kernel status:busy is intentionally ignored — the cell is
                # already "running" in the YDoc from the time it was enqueued.
                if state == "idle":
                    ycell["execution_state"] = "idle"
            elif msg_type == "execute_input":
                # Capture but don't write yet — see comment above.
                _execution_count = content.get("execution_count")
            elif msg_type in (
                "execute_result", "display_data", "update_display_data",
                "stream", "error", "clear_output",
            ):
                if output_processor:
                    output_processor.process_output(
                        msg_type, ycell, item.file_id, item.cell_id, content
                    )

        try:
            assert self._kernel_client is not None
            await self._kernel_client._async_execute_interactive(
                str(ycell.get("source", "")),
                output_hook=output_hook,
                allow_stdin=False,
                timeout=item.timeout,
            )
            # Write execution_count and state together so the frontend
            # sees them in the same YDoc transaction — avoids a brief
            # flash where the count shows before the state clears [*].
            ycell["execution_state"] = "idle"
            if _execution_count is not None:
                ycell["execution_count"] = _execution_count
            self.log.debug("execute_cell completed: cell_id=%s outputs_len=%s",
                          item.cell_id, len(ycell.get("outputs", [])))
        except TimeoutError:
            ycell["execution_state"] = "idle"
            self.log.warning("Cell %s execution timed out", item.cell_id)
        except Exception as e:
            ycell["execution_state"] = "idle"
            self.log.error("execute_cell error cell_id=%s: %s", item.cell_id, e)

    # ── Cell execution ────────────────────────────────────────────────────────────

    async def execute_cell(
        self,
        cell_id: str,
        clear_outputs: bool = False,
        timeout: Optional[float] = None,
    ) -> None:
        """Enqueue a cell for execution and return immediately (fire-and-forget).

        Marks the cell as 'running' in the YDoc so the UI shows [*] right away.
        The actual execution happens in the background worker; outputs appear
        via YDoc sync as the kernel produces them. This allows long-running
        cells (hours) without holding an HTTP connection open.

        'running' matches the IExecutionState type defined in @jupyter/ydoc
        (values: 'running' | 'idle') and is what the standard JupyterLab
        _updatePrompt() checks to render [*].
        """
        if self._kernel_client is None:
            raise RuntimeError("YNotebookRoom is not connected to a kernel")
        if self._execution_queue is None:
            raise RuntimeError("YNotebookRoom execution worker is not running")

        ydoc = await self.get_jupyter_ydoc()
        ycell = self._find_kernel_cell(ydoc, cell_id)
        file_id = self.room_id.split(":", 2)[2]
        if clear_outputs:
            del ycell["outputs"][:]
        ycell["execution_state"] = "running"

        item = _ExecutionItem(
            cell_id=cell_id,
            ycell=ycell,
            file_id=file_id,
            clear_outputs=clear_outputs,
            timeout=timeout,
        )
        await self._execution_queue.put(item)
        # Returns immediately — the worker executes in the background.

    def _find_kernel_cell(self, ydoc, cell_id: str):
        """Find a code cell by id. Raises LookupError if not found, ValueError if not code."""
        for cell in ydoc.ycells:
            if cell.get("id") == cell_id:
                if cell.get("cell_type") != "code":
                    raise ValueError(f"Cell {cell_id!r} is not a code cell")
                return cell
        raise LookupError(f"Cell {cell_id!r} not found in document")
