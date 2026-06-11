"""
Tests for YDocSessionManager.

When create_session() sets up a notebook it:
1. Calls connect_kernel() on the YRoom to attach the server-side executor.
2. Registers a stop callback that fires when the GC frees the room.

The stop callback must *only* disconnect the room from the kernel — it must
NOT delete the session or shut down the kernel.  Room GC reclaims memory;
kernel lifecycle is the user's responsibility.  If we deleted the session on
GC, the user would lose their kernel whenever the browser was idle too long.

Console sessions (type="console") have no backing YDoc or YRoom.  The session
manager must skip all YRoom operations for them and delegate straight to the
parent SessionManager.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from traitlets.config import LoggingConfigurable
from jupyter_server.services.kernels.kernelmanager import MappingKernelManager
from jupyter_server_documents.session_manager import YDocSessionManager


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def session_manager():
    """YDocSessionManager with all server dependencies mocked.

    We need spec=MappingKernelManager on the kernel manager mock so that
    the traitlet type validator accepts it.  Everything else is a plain Mock.
    """
    mock_file_id_manager = Mock()
    mock_yroom_manager = Mock()
    mock_kernel_manager = Mock(spec=MappingKernelManager)

    class MockServerApp(LoggingConfigurable):
        @property
        def kernel_manager(self):
            return mock_kernel_manager

        @property
        def web_app(self):
            m = Mock()
            m.settings = {
                "file_id_manager": mock_file_id_manager,
                "yroom_manager": mock_yroom_manager,
            }
            return m

    manager = YDocSessionManager(parent=MockServerApp())
    manager._room_ids = {}
    manager.kernel_manager = mock_kernel_manager
    return manager


async def _create_notebook_session(session_manager, session_id="session-123", kernel_id="kernel-456"):
    """Helper: run create_session for a notebook and return (yroom, callbacks).

    Returns the mock YRoom and the list of stop callbacks registered during
    create_session so callers can simulate GC.
    """
    file_id = "test-file-id"
    mock_yroom = Mock()
    mock_yroom.room_id = f"json:notebook:{file_id}"
    mock_yroom.connect_kernel = AsyncMock()
    mock_yroom.disconnect_kernel = AsyncMock()

    captured_callbacks = []
    mock_yroom.add_stop_callback = lambda cb: captured_callbacks.append(cb)

    session_manager.serverapp.kernel_manager.get_kernel.return_value = Mock()
    session_manager.yroom_manager.get_room.return_value = mock_yroom
    session_manager.file_id_manager.index.return_value = file_id

    mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
    with patch(
        "jupyter_server.services.sessions.sessionmanager.SessionManager.create_session",
        new_callable=AsyncMock,
        return_value=mock_session,
    ):
        await session_manager.create_session(
            path="/path/to/notebook.ipynb",
            name="notebook.ipynb",
            type="notebook",
            kernel_name="python3",
        )

    return mock_yroom, captured_callbacks


# ── notebook session stop callback ───────────────────────────────────────────

class TestStopCallback:
    """Verifies the YRoom stop callback registered by create_session.

    The callback fires when the YRoomManager GC frees an idle, empty room.
    Its only job is to disconnect the room from the kernel so stale ZMQ
    sockets are closed.
    """

    @pytest.mark.asyncio
    async def test_connect_kernel_called_on_create(self, session_manager):
        """create_session must attach the YRoom to its kernel via connect_kernel().

        Without this call the YRoom has no AsyncKernelClient and cannot run
        server-side cell executions.
        """
        mock_yroom, _ = await _create_notebook_session(session_manager)
        mock_yroom.connect_kernel.assert_called_once()

    @pytest.mark.asyncio
    async def test_gc_triggers_disconnect_kernel(self, session_manager):
        """GC'd room must call disconnect_kernel() to release ZMQ sockets.

        If the freed room stays connected, incoming kernel messages route to
        the stopped room, which calls room.restart() and defeats the GC.
        The callback is fire-and-forget (creates an asyncio.Task), so we
        yield control with sleep(0) before asserting.
        """
        mock_yroom, callbacks = await _create_notebook_session(session_manager)
        assert len(callbacks) == 1

        callbacks[0]()
        await asyncio.sleep(0)  # let the Task created by the callback run

        mock_yroom.disconnect_kernel.assert_called_once()

    @pytest.mark.asyncio
    async def test_gc_does_not_delete_session_or_shutdown_kernel(self, session_manager):
        """GC must not delete the session or shut down the kernel.

        Room GC is a memory-management operation.  Deleting the session would
        terminate the kernel and lose all user state (variables, open files).
        """
        mock_yroom, callbacks = await _create_notebook_session(session_manager)

        with patch.object(session_manager, "delete_session", new_callable=AsyncMock) as mock_delete:
            callbacks[0]()
            await asyncio.sleep(0)

        mock_delete.assert_not_called()
        session_manager.serverapp.kernel_manager.shutdown_kernel.assert_not_called()


# ── console session handling ──────────────────────────────────────────────────

class TestConsoleSession:
    """Console sessions (type='console') have no backing YDoc or YRoom.

    They must pass straight through to the parent SessionManager without
    touching file_id_manager, yroom_manager, or any YRoom methods.
    """

    @pytest.mark.asyncio
    async def test_create_skips_yroom_setup(self, session_manager):
        """Console create_session must not index the path or fetch a YRoom."""
        session_id = "console-session-1"
        mock_session = {"id": session_id, "kernel": {"id": "kernel-789"}}

        with patch(
            "jupyter_server.services.sessions.sessionmanager.SessionManager.create_session",
            new_callable=AsyncMock,
            return_value=mock_session,
        ):
            result = await session_manager.create_session(
                path="console-1-abc123",
                name="console-1-abc123",
                type="console",
                kernel_name="python3",
            )

        assert result == mock_session
        assert session_id in session_manager._console_session_ids
        session_manager.file_id_manager.index.assert_not_called()
        session_manager.yroom_manager.get_room.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_delegates_to_parent(self, session_manager):
        """update_session on a console must not look up a kernel client."""
        session_id = "console-session-1"
        session_manager._console_session_ids.add(session_id)

        with patch(
            "jupyter_server.services.sessions.sessionmanager.SessionManager.update_session",
            new_callable=AsyncMock,
        ) as mock_parent:
            await session_manager.update_session(session_id, kernel_id="new-kernel")

        mock_parent.assert_called_once_with(session_id, kernel_id="new-kernel")
        session_manager.serverapp.kernel_manager.get_kernel.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_delegates_to_parent_and_cleans_up(self, session_manager):
        """delete_session on a console must remove the console ID and delegate."""
        session_id = "console-session-1"
        session_manager._console_session_ids.add(session_id)

        with patch(
            "jupyter_server.services.sessions.sessionmanager.SessionManager.delete_session",
            new_callable=AsyncMock,
        ) as mock_parent:
            await session_manager.delete_session(session_id)

        mock_parent.assert_called_once_with(session_id)
        assert session_id not in session_manager._console_session_ids
