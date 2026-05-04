"""Tests for the YDocSessionManager.

Covers:
1. Stop callback behavior — verifies GC decouples from kernel shutdown
2. _ensure_yroom_connected — verifies yroom-kernel connection management
3. get_session — verifies the override that ensures yroom connections
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from traitlets.config import LoggingConfigurable
from jupyter_server.services.kernels.kernelmanager import MappingKernelManager
from jupyter_server_documents.session_manager import YDocSessionManager


@pytest.fixture
def session_manager():
    """Create a YDocSessionManager with mocked server dependencies."""
    mock_file_id_manager = Mock()
    mock_yroom_manager = Mock()
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
    manager.kernel_manager = mock_kernel_manager
    return manager


@pytest.fixture
def mock_kernel_client():
    """Create a mock kernel client with _yrooms attribute."""
    client = Mock()
    client._yrooms = set()
    client.add_yroom = AsyncMock()
    client.remove_yroom = AsyncMock()
    return client


@pytest.fixture
def mock_yroom():
    """Create a mock YRoom."""
    yroom = Mock()
    yroom.room_id = "json:notebook:test-file-id"
    return yroom


class TestCreateSessionStopCallback:
    """Tests for the stop callback registered during create_session."""

    @pytest.mark.asyncio
    async def test_stop_callback_removes_yroom_from_kernel_client(self, session_manager):
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
            await session_manager.create_session(
                path="/path/to/notebook.ipynb",
                name="notebook.ipynb",
                type="notebook",
                kernel_name="python3"
            )

        assert len(captured_callbacks) == 1

        callback_result = captured_callbacks[0]()
        assert asyncio.iscoroutine(callback_result)
        await callback_result

        mock_kernel_client.remove_yroom.assert_called_once_with(mock_yroom)

    @pytest.mark.asyncio
    async def test_stop_callback_does_not_delete_session(self, session_manager):
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

            with patch.object(session_manager, 'delete_session', new_callable=AsyncMock) as mock_delete:
                await session_manager.create_session(
                    path="/path/to/notebook.ipynb",
                    name="notebook.ipynb",
                    type="notebook",
                    kernel_name="python3"
                )

                callback_result = captured_callbacks[0]()
                if asyncio.iscoroutine(callback_result):
                    await callback_result

                mock_delete.assert_not_called()
                session_manager.serverapp.kernel_manager.shutdown_kernel.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_callback_preserves_room_id_mapping(self, session_manager):
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

        callback_result = captured_callbacks[0]()
        if asyncio.iscoroutine(callback_result):
            await callback_result

        assert session_id in session_manager._room_ids
        assert session_manager._room_ids[session_id] == room_id


class TestEnsureYRoomConnected:
    """Tests for _ensure_yroom_connected method."""

    @pytest.mark.asyncio
    async def test_uses_cached_room_id(self, session_manager, mock_yroom, mock_kernel_client):
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:cached-file-id"

        session_manager._room_ids[session_id] = room_id
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        mock_yroom.room_id = room_id

        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        await session_manager._ensure_yroom_connected(session_id, kernel_id)

        session_manager.yroom_manager.get_room.assert_called_once_with(room_id)
        assert mock_yroom in mock_kernel_client._yrooms

    @pytest.mark.asyncio
    async def test_reconstructs_room_id_from_session_path(self, session_manager, mock_yroom, mock_kernel_client):
        session_id = "session-123"
        kernel_id = "kernel-456"
        path = "/path/to/notebook.ipynb"
        file_id = "reconstructed-file-id"
        room_id = f"json:notebook:{file_id}"

        mock_session = {
            "id": session_id,
            "type": "notebook",
            "path": path
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session
            session_manager.file_id_manager.index.return_value = file_id
            session_manager.yroom_manager.get_room.return_value = mock_yroom
            mock_yroom.room_id = room_id

            mock_kernel_manager = Mock()
            mock_kernel_manager.kernel_client = mock_kernel_client
            session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

            await session_manager._ensure_yroom_connected(session_id, kernel_id)

            session_manager.file_id_manager.index.assert_called_once_with(path)
            assert session_manager._room_ids[session_id] == room_id
            assert mock_yroom in mock_kernel_client._yrooms

    @pytest.mark.asyncio
    async def test_skips_non_notebook_sessions(self, session_manager):
        session_id = "session-123"
        kernel_id = "kernel-456"

        mock_session = {
            "id": session_id,
            "type": "console",
            "path": "/path/to/console"
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session
            await session_manager._ensure_yroom_connected(session_id, kernel_id)
            assert session_id not in session_manager._room_ids

    @pytest.mark.asyncio
    async def test_skips_when_yroom_already_connected(self, session_manager, mock_yroom, mock_kernel_client):
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        session_manager._room_ids[session_id] = room_id
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        mock_kernel_client._yrooms.add(mock_yroom)

        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        initial_yrooms_count = len(mock_kernel_client._yrooms)
        await session_manager._ensure_yroom_connected(session_id, kernel_id)
        assert len(mock_kernel_client._yrooms) == initial_yrooms_count

    @pytest.mark.asyncio
    async def test_handles_missing_yroom_gracefully(self, session_manager):
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:missing-file-id"

        session_manager._room_ids[session_id] = room_id
        session_manager.yroom_manager.get_room.return_value = None
        await session_manager._ensure_yroom_connected(session_id, kernel_id)

    @pytest.mark.asyncio
    async def test_handles_kernel_client_without_yrooms_attribute(self, session_manager, mock_yroom):
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        session_manager._room_ids[session_id] = room_id
        session_manager.yroom_manager.get_room.return_value = mock_yroom

        mock_kernel_client = Mock(spec=[])
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        await session_manager._ensure_yroom_connected(session_id, kernel_id)


class TestGetSession:
    """Tests for get_session method override."""

    @pytest.mark.asyncio
    async def test_calls_ensure_yroom_connected(self, session_manager):
        session_id = "session-123"
        kernel_id = "kernel-456"

        mock_session = {
            "id": session_id,
            "kernel": {"id": kernel_id},
            "type": "notebook"
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_super_get_session:
            mock_super_get_session.return_value = mock_session

            with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock) as mock_ensure:
                result = await session_manager.get_session(session_id=session_id)
                mock_ensure.assert_called_once_with(session_id, kernel_id)
                assert result == mock_session

    @pytest.mark.asyncio
    async def test_handles_none_session(self, session_manager):
        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_super_get_session:
            mock_super_get_session.return_value = None

            with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock) as mock_ensure:
                result = await session_manager.get_session(session_id="missing-session")
                mock_ensure.assert_not_called()
                assert result is None

    @pytest.mark.asyncio
    async def test_handles_session_without_kernel(self, session_manager):
        mock_session = {
            "id": "session-123",
            "kernel": None,
            "type": "notebook"
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_super_get_session:
            mock_super_get_session.return_value = mock_session

            with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock) as mock_ensure:
                result = await session_manager.get_session(session_id="session-123")
                mock_ensure.assert_not_called()
                assert result == mock_session


class TestDeleteSession:
    """Tests for delete_session kernel awareness behavior."""

    @pytest.mark.asyncio
    async def test_sets_awareness_to_dead(self, session_manager, mock_yroom, mock_kernel_client):
        """delete_session should write 'dead' to notebook awareness before disconnecting."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        # Set up cached room_id
        session_manager._room_ids[session_id] = room_id

        # Mock notebook with set_kernel_execution_state
        mock_notebook = Mock()
        mock_notebook.set_kernel_execution_state = Mock()
        mock_yroom.jupyter_ydoc = mock_notebook
        mock_yroom.room_id = room_id

        # Mock yroom manager
        session_manager.yroom_manager.get_room.return_value = mock_yroom

        # Mock kernel client
        mock_kernel_client.remove_yroom = AsyncMock()
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        # Mock get_session to return a valid session
        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.delete_session', new_callable=AsyncMock):
                with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock):
                    await session_manager.delete_session(session_id)

        # Verify awareness was set to "dead"
        mock_notebook.set_kernel_execution_state.assert_called_once_with("dead")

    @pytest.mark.asyncio
    async def test_sets_dead_before_removing_yroom(self, session_manager, mock_yroom, mock_kernel_client):
        """Awareness must be set to 'dead' BEFORE the yroom is disconnected."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        session_manager._room_ids[session_id] = room_id

        # Track call order
        call_order = []

        mock_notebook = Mock()
        mock_notebook.set_kernel_execution_state = Mock(
            side_effect=lambda s: call_order.append(("set_dead", s))
        )
        mock_yroom.jupyter_ydoc = mock_notebook
        mock_yroom.room_id = room_id

        session_manager.yroom_manager.get_room.return_value = mock_yroom

        mock_kernel_client.remove_yroom = AsyncMock(
            side_effect=lambda yroom: call_order.append("remove_yroom")
        )
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.delete_session', new_callable=AsyncMock):
                with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock):
                    await session_manager.delete_session(session_id)

        assert call_order == [("set_dead", "dead"), "remove_yroom"]

    @pytest.mark.asyncio
    async def test_handles_missing_notebook_gracefully(self, session_manager, mock_yroom, mock_kernel_client):
        """delete_session should not crash if notebook is None."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        session_manager._room_ids[session_id] = room_id

        # No notebook on yroom
        mock_yroom.jupyter_ydoc = None
        mock_yroom.room_id = room_id

        session_manager.yroom_manager.get_room.return_value = mock_yroom

        mock_kernel_client.remove_yroom = AsyncMock()
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        mock_session = {"id": session_id, "kernel": {"id": kernel_id}}
        with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.get_session', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_session
            with patch('jupyter_server.services.sessions.sessionmanager.SessionManager.delete_session', new_callable=AsyncMock):
                with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock):
                    await session_manager.delete_session(session_id)

        # Should complete without error
        mock_kernel_client.remove_yroom.assert_called_once_with(mock_yroom)
