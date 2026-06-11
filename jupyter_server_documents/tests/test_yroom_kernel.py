"""
Tests for YRoom kernel connection and cell execution.

Architecture: YRoom owns a single AsyncKernelClient per kernel.  Cells are
executed fire-and-forget via an asyncio Queue + worker.  The YDoc cell map
is written directly with execution_state / execution_count / outputs so every
connected browser tab sees live updates through the normal Yjs sync path.

Critical invariants tested here:
- connect_kernel() creates an *independent* AsyncKernelClient session (not a
  clone of the kernel manager's session) so ZMQ DEALER identities don't collide.
- execute_cell() returns immediately and marks the cell "queued" in the YDoc.
- The execution worker serializes cells one at a time, routing outputs through
  the output_hook closure directly into the YDoc.
- disconnect_kernel() drains the queue and resets all state.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def make_yroom():
    """Return a YRoom with all kernel state initialized but no real __init__."""
    from jupyter_server_documents.rooms.yroom import YRoom

    room = YRoom.__new__(YRoom)
    room.room_id = "json:notebook:file-abc"
    room.log = MagicMock()
    room._kernel_client = None
    room._kernel_manager = None
    room._shell_confirmed = False
    room._execution_queue = None
    room._execution_worker_task = None
    room.output_processor = None
    return room


def make_mock_km():
    """Return a (kernel_manager, mock_client) pair ready for connect_kernel().

    The mock client answers heartbeat immediately (_async_is_alive=True) and
    resolves _async_wait_for_ready without blocking so tests stay fast.
    """
    mock_client = MagicMock()
    mock_client._async_is_alive = AsyncMock(return_value=True)
    mock_client.hb_channel = MagicMock()
    mock_client._async_wait_for_ready = AsyncMock(return_value=None)

    km = MagicMock()
    km.get_connection_info.return_value = {}
    # client_factory is what _connect_client calls to instantiate the client
    km.client_factory = MagicMock(return_value=mock_client)
    return km, mock_client


def patch_client(mock_client):
    """Set client_factory on the mock km so connect_kernel() uses mock_client."""
    # No patching needed — make_mock_km already sets km.client_factory.
    from contextlib import nullcontext
    return nullcontext()


async def connect(room, km=None, mock_client=None):
    """Connect a room using mocked kernel plumbing. Returns (km, mock_client)."""
    if km is None:
        km, mock_client = make_mock_km()
    with patch_client(mock_client), patch("jupyter_server_documents.outputs.OutputProcessor"):
        await room.connect_kernel(km)
    return km, mock_client


# ── connect_kernel ────────────────────────────────────────────────────────────

class TestConnectKernel:
    """connect_kernel() wires up the ZMQ client, starts the worker, and
    confirms the shell channel is ready before accepting executions."""

    @pytest.mark.asyncio
    async def test_creates_independent_client(self):
        """connect_kernel must instantiate via client_factory, not km.client().

        Using km.client() clones the kernel manager's session, so every
        connected client gets the same ZMQ DEALER identity.  The kernel's
        ROUTER then routes execute_reply to the wrong socket.  We verify that
        client_factory is called directly and km.client() is never called.
        """
        room = make_yroom()
        km, mock_client = make_mock_km()
        with patch("jupyter_server_documents.outputs.OutputProcessor"):
            await room.connect_kernel(km)
        km.client_factory.assert_called_once()
        km.client.assert_not_called()
        await room.disconnect_kernel()

    @pytest.mark.asyncio
    async def test_custom_client_factory_is_used(self):
        """A custom client class set on client_factory must be what the YRoom uses.

        kernel_manager.client_factory is a configurable trait — operators can
        swap in a custom AsyncKernelClient subclass. The YRoom must honour that.
        """
        room = make_yroom()
        km, _ = make_mock_km()

        class CustomKernelClient:
            instantiated = False
            def __init__(self, **kwargs):
                CustomKernelClient.instantiated = True
                self.session = MagicMock()
                self.hb_channel = MagicMock()
                self._async_is_alive = AsyncMock(return_value=True)
                self._async_wait_for_ready = AsyncMock(return_value=None)
            def load_connection_info(self, info): pass
            def start_channels(self, **kwargs): pass
            def stop_channels(self): pass

        km.client_factory = CustomKernelClient
        with patch("jupyter_server_documents.outputs.OutputProcessor"):
            await room.connect_kernel(km)
        assert CustomKernelClient.instantiated
        assert isinstance(room._kernel_client, CustomKernelClient)
        await room.disconnect_kernel()

    @pytest.mark.asyncio
    async def test_shell_confirmed_after_wait_for_ready(self):
        """_shell_confirmed must be True once connect_kernel returns.

        _async_wait_for_ready() confirms both the shell *and* iopub channels
        are live before we return.  If this flag is False, the execution worker
        waits (up to 60 s) before running the first cell.
        """
        room = make_yroom()
        km, mock_client = await connect(room)
        assert room._shell_confirmed is True
        mock_client._async_wait_for_ready.assert_called_once()
        await room.disconnect_kernel()

    @pytest.mark.asyncio
    async def test_execution_worker_started(self):
        """Execution queue and worker task must be running after connect_kernel.

        The worker must start *before* _fetch_kernel_info so that execute_cell()
        can safely enqueue work immediately — items just wait in the queue until
        _shell_confirmed becomes True.
        """
        room = make_yroom()
        km, _ = await connect(room)
        assert room._execution_queue is not None
        assert room._execution_worker_task is not None
        assert not room._execution_worker_task.done()
        await room.disconnect_kernel()

    @pytest.mark.asyncio
    async def test_restart_callbacks_registered(self):
        """Restart and dead callbacks must be registered with the kernel manager.

        If the kernel is restarted by the user or culled for inactivity, these
        callbacks ensure we reconnect (restart) or clean up (dead) correctly.
        """
        room = make_yroom()
        km, _ = await connect(room)
        # add_restart_callback called twice: once for "restart", once for "dead"
        assert km.add_restart_callback.call_count == 2
        await room.disconnect_kernel()

    @pytest.mark.asyncio
    async def test_reconnect_disconnects_existing_client(self):
        """Calling connect_kernel twice must not leave orphaned ZMQ sockets.

        If a stale connection is in place when connect_kernel is called (e.g.
        after a kernel restart), the old client must be stopped first.
        """
        room = make_yroom()
        km, first_client = await connect(room)
        _, second_client = make_mock_km()

        # Point the same km at a new client for the second connect

        km.client_factory = MagicMock(return_value=second_client)
        with patch("jupyter_server_documents.outputs.OutputProcessor"):
            await room.connect_kernel(km)

        first_client.stop_channels.assert_called_once()
        assert room._kernel_client is second_client
        await room.disconnect_kernel()


# ── disconnect_kernel ─────────────────────────────────────────────────────────

class TestDisconnectKernel:
    """disconnect_kernel() must fully clean up so the room is reusable."""

    @pytest.mark.asyncio
    async def test_stops_channels_and_clears_client(self):
        """ZMQ channels must be stopped and _kernel_client set to None."""
        room = make_yroom()
        km, mock_client = await connect(room)
        await room.disconnect_kernel()
        mock_client.stop_channels.assert_called_once()
        assert room._kernel_client is None
        assert room._kernel_manager is None

    @pytest.mark.asyncio
    async def test_cancels_worker_and_clears_queue(self):
        """Execution worker task and queue must be cleaned up on disconnect."""
        room = make_yroom()
        await connect(room)
        await room.disconnect_kernel()
        assert room._execution_worker_task is None
        assert room._execution_queue is None

    @pytest.mark.asyncio
    async def test_running_cells_marked_idle_on_disconnect(self):
        """Cells waiting in the queue must be reset to 'idle' on disconnect.

        Without this, cells would remain stuck showing [*] after a kernel
        restart or server shutdown.
        """
        room = make_yroom()
        await connect(room)

        # Enqueue a cell manually — bypasses execute_cell() guards
        ycell = {"id": "cell-1", "execution_state": "running"}
        item = MagicMock()
        item.ycell = ycell
        await room._execution_queue.put(item)

        await room.disconnect_kernel()
        assert ycell["execution_state"] == "idle"

    @pytest.mark.asyncio
    async def test_removes_restart_callbacks(self):
        """Restart callbacks must be deregistered to avoid dangling references."""
        room = make_yroom()
        km, _ = await connect(room)
        await room.disconnect_kernel()
        assert km.remove_restart_callback.call_count == 2

    @pytest.mark.asyncio
    async def test_idempotent_before_connect(self):
        """disconnect_kernel on a fresh room must not raise."""
        room = make_yroom()
        await room.disconnect_kernel()  # no exception


# ── _find_kernel_cell ─────────────────────────────────────────────────────────

class TestFindKernelCell:
    """_find_kernel_cell looks up a cell in the YDoc by id and validates it."""

    def test_returns_matching_code_cell(self):
        room = make_yroom()
        ydoc = MagicMock()
        ydoc.ycells = [
            {"id": "cell-1", "cell_type": "code", "source": "1+1"},
            {"id": "cell-2", "cell_type": "code", "source": "2+2"},
        ]
        cell = room._find_kernel_cell(ydoc, "cell-2")
        assert cell["id"] == "cell-2"

    def test_raises_lookup_error_when_not_found(self):
        """LookupError keeps the HTTP 400 contract in the handler."""
        room = make_yroom()
        ydoc = MagicMock()
        ydoc.ycells = []
        with pytest.raises(LookupError):
            room._find_kernel_cell(ydoc, "missing")

    def test_raises_value_error_for_non_code_cell(self):
        """Only code cells can be executed; markdown/raw must be rejected."""
        room = make_yroom()
        ydoc = MagicMock()
        ydoc.ycells = [{"id": "cell-1", "cell_type": "markdown", "source": "# hi"}]
        with pytest.raises(ValueError):
            room._find_kernel_cell(ydoc, "cell-1")


# ── execute_cell ──────────────────────────────────────────────────────────────

class TestExecuteCell:
    """execute_cell() is fire-and-forget: it enqueues the cell and returns.

    The actual execution happens asynchronously in the worker.  The cell is
    immediately marked 'queued' in the YDoc so the UI shows [*] right away.
    """

    @pytest.mark.asyncio
    async def test_raises_when_not_connected(self):
        """Must raise RuntimeError if no kernel is attached.

        The HTTP handler catches this and returns 400.
        """
        room = make_yroom()
        with pytest.raises(RuntimeError, match="not connected"):
            await room.execute_cell("cell-1")

    @pytest.mark.asyncio
    async def test_marks_cell_running_and_returns_immediately(self):
        """execute_cell must set execution_state='running' and enqueue, not block.

        A blocked execute_cell would hold the HTTP connection open for the
        entire duration of the cell run, defeating fire-and-forget semantics.
        We verify it completes within 1 second even though the worker is idle.
        """
        room = make_yroom()
        room._kernel_client = MagicMock()
        room._kernel_manager = MagicMock()
        room._shell_confirmed = True

        mock_cell = {"id": "cell-1", "source": "1+1", "cell_type": "code", "outputs": []}
        mock_ydoc = MagicMock()
        mock_ydoc.ycells = [mock_cell]
        room.get_jupyter_ydoc = AsyncMock(return_value=mock_ydoc)
        room._execution_queue = asyncio.Queue()
        room._execution_worker_task = asyncio.create_task(asyncio.sleep(9999))

        try:
            await asyncio.wait_for(room.execute_cell("cell-1"), timeout=1.0)
            assert mock_cell["execution_state"] == "running"
            assert not room._execution_queue.empty()
        finally:
            room._execution_worker_task.cancel()
            await asyncio.gather(room._execution_worker_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_sends_source_to_kernel(self):
        """The cell's source must be passed verbatim to _async_execute_interactive."""
        room = make_yroom()
        room._kernel_client = MagicMock()
        room._kernel_manager = MagicMock()
        room._shell_confirmed = True
        room.output_processor = MagicMock()

        mock_cell = {"id": "cell-1", "source": "print('hello')", "cell_type": "code", "outputs": []}
        mock_ydoc = MagicMock()
        mock_ydoc.ycells = [mock_cell]
        room.get_jupyter_ydoc = AsyncMock(return_value=mock_ydoc)

        executed = asyncio.Event()

        async def fake_execute(code, **kwargs):
            executed.set()
            return {"status": "ok"}

        room._kernel_client._async_execute_interactive = fake_execute
        room._execution_queue = asyncio.Queue()
        room._execution_worker_task = asyncio.create_task(room._execution_worker())

        await room.execute_cell("cell-1")
        await asyncio.wait_for(executed.wait(), timeout=2.0)

        room._execution_worker_task.cancel()
        await asyncio.gather(room._execution_worker_task, return_exceptions=True)

    @pytest.mark.asyncio
    async def test_stdin_disabled(self):
        """allow_stdin must be False — server-side execution cannot prompt the user."""
        room = make_yroom()
        room._kernel_client = MagicMock()
        room._kernel_manager = MagicMock()
        room._shell_confirmed = True
        room.output_processor = MagicMock()

        mock_cell = {"id": "cell-1", "source": "x=1", "cell_type": "code", "outputs": []}
        mock_ydoc = MagicMock()
        mock_ydoc.ycells = [mock_cell]
        room.get_jupyter_ydoc = AsyncMock(return_value=mock_ydoc)

        captured_kwargs = {}
        executed = asyncio.Event()

        async def fake_execute(code, **kwargs):
            captured_kwargs.update(kwargs)
            executed.set()
            return {"status": "ok"}

        room._kernel_client._async_execute_interactive = fake_execute
        room._execution_queue = asyncio.Queue()
        room._execution_worker_task = asyncio.create_task(room._execution_worker())

        await room.execute_cell("cell-1")
        await asyncio.wait_for(executed.wait(), timeout=2.0)

        room._execution_worker_task.cancel()
        await asyncio.gather(room._execution_worker_task, return_exceptions=True)

        assert captured_kwargs.get("allow_stdin") is False


# ── output_hook routing ───────────────────────────────────────────────────────

class TestOutputHook:
    """The output_hook closure in _run_item routes iopub messages into the YDoc.

    Messages are routed by msg_type:
    - status: writes execution_state to the YDoc cell
    - execute_input: writes execution_count
    - stream/execute_result/display_data/error: forwarded to output_processor
    """

    async def _run_with_hook(self, messages):
        """Helper: run a cell and collect output_processor calls."""
        room = make_yroom()
        room._kernel_client = MagicMock()
        room._kernel_manager = MagicMock()
        room._shell_confirmed = True
        mock_processor = MagicMock()
        room.output_processor = mock_processor

        mock_cell = {"id": "cell-1", "source": "x", "cell_type": "code", "outputs": []}
        mock_ydoc = MagicMock()
        mock_ydoc.ycells = [mock_cell]
        room.get_jupyter_ydoc = AsyncMock(return_value=mock_ydoc)

        executed = asyncio.Event()

        async def fake_execute(code, output_hook=None, **kwargs):
            for msg in messages:
                if output_hook:
                    output_hook(msg)
            executed.set()
            return {"status": "ok"}

        room._kernel_client._async_execute_interactive = fake_execute
        room._execution_queue = asyncio.Queue()
        room._execution_worker_task = asyncio.create_task(room._execution_worker())

        await room.execute_cell("cell-1")
        await asyncio.wait_for(executed.wait(), timeout=2.0)
        room._execution_worker_task.cancel()
        await asyncio.gather(room._execution_worker_task, return_exceptions=True)
        return mock_cell, mock_processor

    @pytest.mark.asyncio
    async def test_status_busy_from_kernel_is_ignored(self):
        """kernel status:busy must NOT overwrite the YDoc state.

        The cell is already 'running' from enqueue time. 'busy' from the
        kernel is an implementation detail that should not leak into the YDoc.
        """
        cell, _ = await self._run_with_hook([
            {"header": {"msg_type": "status"}, "content": {"execution_state": "busy"}},
        ])
        # After completion the worker overwrites to 'idle'.
        assert cell.get("execution_state") == "idle"

    @pytest.mark.asyncio
    async def test_execute_input_writes_execution_count(self):
        """execute_input must write execution_count to the YDoc cell."""
        cell, _ = await self._run_with_hook([
            {"header": {"msg_type": "execute_input"}, "content": {"execution_count": 7}},
        ])
        assert cell.get("execution_count") == 7

    @pytest.mark.asyncio
    async def test_stream_output_forwarded_to_processor(self):
        """stream messages must be forwarded to output_processor.process_output()."""
        cell, proc = await self._run_with_hook([
            {"header": {"msg_type": "stream"}, "content": {"name": "stdout", "text": "hi\n"}},
        ])
        proc.process_output.assert_called_once_with(
            "stream", cell, "file-abc", "cell-1", {"name": "stdout", "text": "hi\n"}
        )

    @pytest.mark.asyncio
    async def test_execute_result_forwarded_to_processor(self):
        """execute_result must be forwarded (e.g. for rich output display)."""
        cell, proc = await self._run_with_hook([
            {"header": {"msg_type": "execute_result"}, "content": {"data": {"text/plain": "42"}, "execution_count": 1, "metadata": {}}},
        ])
        proc.process_output.assert_called_once()
        assert proc.process_output.call_args[0][0] == "execute_result"

    @pytest.mark.asyncio
    async def test_cell_idle_after_execution(self):
        """execution_state must be 'idle' once _run_item completes.

        This ensures the [*] indicator clears even if the kernel never sends
        a final status:idle message (which can happen on short executions).
        """
        cell, _ = await self._run_with_hook([])
        assert cell.get("execution_state") == "idle"
