"""Tests for the YDocSessionManager stop callback behavior.

When create_session() sets up a notebook, it registers a stop callback on
the yroom. This callback fires when the room is freed by the GC (via
yroom.stop()). The GC frees rooms that are inactive and empty (no WebSocket
clients connected for a while).

The stop callback must only disconnect the room from the kernel client — it
must NOT delete the session or shut down the kernel. Room GC reclaims memory;
kernel lifecycle is the user's responsibility.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, patch
from traitlets.config import LoggingConfigurable
from jupyter_server.services.kernels.kernelmanager import MappingKernelManager
from jupyter_server_documents.session_manager import YDocSessionManager


@pytest.fixture
def session_manager():
    """Create a YDocSessionManager with mocked server dependencies.

    Mocks the kernel_manager, file_id_manager, and yroom_manager so we
    can test the session manager's logic without a running Jupyter server.
    """
    mock_file_id_manager = Mock()
    mock_yroom_manager = Mock()
    # Use spec=MappingKernelManager to satisfy the traitlet type check
    mock_kernel_manager = Mock(spec=MappingKernelManager)

    class MockServerApp(LoggingConfigurable):
        @property
        def kernel_manager(self):
            return mock_kernel_manager

        @property
        def web_app(self):
            mock_web_app = Mock()
            mock_web_app.settings = {
                "file_id_manager": mock_file_id_manager,
                "yroom_manager": mock_yroom_manager
            }
            return mock_web_app

    manager = YDocSessionManager(parent=MockServerApp())
    manager._room_ids = {}
    # YDocSessionManager.kernel_manager is a traitlet inherited from
    # SessionManager. We set it with a spec'd mock to pass type validation.
    manager.kernel_manager = mock_kernel_manager
    return manager


class TestCreateSessionStopCallback:
    """Tests for the stop callback registered during create_session.

    These tests verify that when a room is freed by GC:
    1. The yroom is removed from the kernel client (stops message routing)
    2. The session is NOT deleted (kernel stays alive)
    3. The _room_ids mapping persists (enables reconnection)
    """

    @pytest.mark.asyncio
    async def test_stop_callback_removes_yroom_from_kernel_client(self, session_manager):
        """GC'd room must be unregistered from the kernel client.

        If the freed room remains in kernel_client._yrooms, incoming kernel
        messages route to the stopped room, triggering room.restart() and
        defeating the GC.
        """
        session_id = "session-123"
        kernel_id = "kernel-456"
        file_id = "test-file-id"

        # Mock the yroom — we intercept add_stop_callback to capture
        # what callback create_session registers, so we can invoke it later.
        mock_yroom = Mock()
        mock_yroom.room_id = f"json:notebook:{file_id}"

        captured_callbacks = []
        mock_yroom.add_stop_callback = lambda cb: captured_callbacks.append(cb)

        # Mock the kernel client — this is what the stop callback should
        # call remove_yroom() on.
        mock_kernel_client = Mock()
        mock_kernel_client.add_yroom = AsyncMock()
        mock_kernel_client.remove_yroom = AsyncMock()

        mock_kernel_mgr = Mock()
        mock_kernel_mgr.main_client = mock_kernel_client

        # Wire up the session manager's dependencies
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_mgr
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        session_manager.file_id_manager.index.return_value = file_id

        # --- Act: create a session (this registers the stop callback) ---
        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.create_session', new_callable=AsyncMock) as mock_parent:
            mock_parent.return_value = mock_session
            await session_manager.create_session(
                path="/path/to/notebook.ipynb",
                name="notebook.ipynb",
                type="notebook",
                kernel_name="python3"
            )

        # Verify a stop callback was registered during create_session
        assert len(captured_callbacks) == 1

        # --- Act: simulate the GC freeing the room (fires stop callbacks) ---
        callback_result = captured_callbacks[0]()

        # The callback returns a coroutine (remove_yroom is async).
        # In production, YRoom.stop() wraps this in asyncio.create_task().
        assert asyncio.iscoroutine(callback_result)
        await callback_result

        # --- Assert: the yroom was disconnected from the kernel client ---
        mock_kernel_client.remove_yroom.assert_called_once_with(mock_yroom)

    @pytest.mark.asyncio
    async def test_stop_callback_does_not_delete_session(self, session_manager):
        """GC'd room must NOT trigger delete_session or shutdown_kernel.

        delete_session() terminates the kernel process, destroying all
        in-memory state. Kernels are only shut down by explicit user action
        or an idle culler — never as a side effect of room GC.
        """
        session_id = "session-123"
        kernel_id = "kernel-456"
        file_id = "test-file-id"

        mock_yroom = Mock()
        mock_yroom.room_id = f"json:notebook:{file_id}"

        captured_callbacks = []
        mock_yroom.add_stop_callback = lambda cb: captured_callbacks.append(cb)

        mock_kernel_client = Mock()
        mock_kernel_client.add_yroom = AsyncMock()
        mock_kernel_client.remove_yroom = AsyncMock()

        mock_kernel_mgr = Mock()
        mock_kernel_mgr.main_client = mock_kernel_client

        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_mgr
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        session_manager.file_id_manager.index.return_value = file_id

        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.create_session', new_callable=AsyncMock) as mock_parent:
            mock_parent.return_value = mock_session

            # Spy on delete_session — if the stop callback calls it, this
            # mock will record the call.
            with patch.object(session_manager, 'delete_session', new_callable=AsyncMock) as mock_delete:
                await session_manager.create_session(
                    path="/path/to/notebook.ipynb",
                    name="notebook.ipynb",
                    type="notebook",
                    kernel_name="python3"
                )

                # --- Act: simulate the GC freeing the room ---
                callback_result = captured_callbacks[0]()
                if asyncio.iscoroutine(callback_result):
                    await callback_result

                # --- Assert: delete_session was NOT called ---
                # Room GC must never kill kernels.
                mock_delete.assert_not_called()

                # --- Assert: shutdown_kernel was NOT called ---
                session_manager.serverapp.kernel_manager.shutdown_kernel.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_callback_preserves_room_id_mapping(self, session_manager):
        """GC'd room must leave _room_ids intact for reconnection.

        _room_ids maps session_id -> room_id. When the user reconnects,
        _ensure_yroom_connected() uses this mapping to re-link the new
        room to the kernel. The room_id is deterministic (derived from the
        file's ID), so the mapping becomes valid again when the room is
        recreated.
        """
        session_id = "session-123"
        kernel_id = "kernel-456"
        file_id = "test-file-id"
        room_id = f"json:notebook:{file_id}"

        mock_yroom = Mock()
        mock_yroom.room_id = room_id

        captured_callbacks = []
        mock_yroom.add_stop_callback = lambda cb: captured_callbacks.append(cb)

        mock_kernel_client = Mock()
        mock_kernel_client.add_yroom = AsyncMock()
        mock_kernel_client.remove_yroom = AsyncMock()

        mock_kernel_mgr = Mock()
        mock_kernel_mgr.main_client = mock_kernel_client

        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_mgr
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        session_manager.file_id_manager.index.return_value = file_id

        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.create_session', new_callable=AsyncMock) as mock_parent:
            mock_parent.return_value = mock_session
            await session_manager.create_session(
                path="/path/to/notebook.ipynb",
                name="notebook.ipynb",
                type="notebook",
                kernel_name="python3"
            )

        # --- Act: simulate the GC freeing the room ---
        callback_result = captured_callbacks[0]()
        if asyncio.iscoroutine(callback_result):
            await callback_result

        # --- Assert: _room_ids still has the mapping ---
        # This entry is what allows _ensure_yroom_connected to reconnect
        # the user to their kernel when they return.
        assert session_id in session_manager._room_ids
        assert session_manager._room_ids[session_id] == room_id
