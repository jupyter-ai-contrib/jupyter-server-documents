"""Tests for YDocSessionManager yroom-kernel connection logic.

These tests verify that the session manager properly maintains connections
between yrooms (collaborative document state) and kernel clients, especially
for persistent kernels that survive server restarts.
"""
import pytest
from unittest.mock import AsyncMock, Mock, MagicMock, patch
from jupyter_server_documents.session_manager import YDocSessionManager


@pytest.fixture
def session_manager():
    """Create a mock session manager for testing."""
    manager = YDocSessionManager()

    # Mock required dependencies
    manager.serverapp = Mock()
    manager.file_id_manager = Mock()
    manager.yroom_manager = Mock()
    manager.log = Mock()

    # Initialize the _room_ids dict
    manager._room_ids = {}

    return manager


@pytest.fixture
def mock_kernel_client():
    """Create a mock kernel client with _yrooms attribute."""
    client = Mock()
    client._yrooms = set()
    return client


@pytest.fixture
def mock_yroom():
    """Create a mock YRoom."""
    yroom = Mock()
    yroom.room_id = "json:notebook:test-file-id"
    return yroom


class TestEnsureYRoomConnected:
    """Tests for _ensure_yroom_connected method."""

    @pytest.mark.asyncio
    async def test_uses_cached_room_id(self, session_manager, mock_yroom, mock_kernel_client):
        """Test that cached room_id is used when available."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:cached-file-id"

        # Set up cached room_id
        session_manager._room_ids[session_id] = room_id

        # Mock yroom manager
        session_manager.yroom_manager.get_room.return_value = mock_yroom
        mock_yroom.room_id = room_id

        # Mock kernel manager
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        await session_manager._ensure_yroom_connected(session_id, kernel_id)

        # Verify cached room_id was used
        session_manager.yroom_manager.get_room.assert_called_once_with(room_id)

        # Verify yroom was added to kernel client
        assert mock_yroom in mock_kernel_client._yrooms

    @pytest.mark.asyncio
    async def test_reconstructs_room_id_from_session_path(self, session_manager, mock_yroom, mock_kernel_client):
        """Test that room_id is reconstructed from session path when not cached."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        path = "/path/to/notebook.ipynb"
        file_id = "reconstructed-file-id"
        room_id = f"json:notebook:{file_id}"

        # Mock get_session to return session with path
        mock_session = {
            "id": session_id,
            "type": "notebook",
            "path": path
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_get_session:
            # Use super() call to avoid recursion
            mock_get_session.return_value = mock_session

            # Mock file_id_manager
            session_manager.file_id_manager.index.return_value = file_id

            # Mock yroom manager
            session_manager.yroom_manager.get_room.return_value = mock_yroom
            mock_yroom.room_id = room_id

            # Mock kernel manager
            mock_kernel_manager = Mock()
            mock_kernel_manager.kernel_client = mock_kernel_client
            session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

            await session_manager._ensure_yroom_connected(session_id, kernel_id)

            # Verify room_id was reconstructed
            session_manager.file_id_manager.index.assert_called_once_with(path)

            # Verify room_id was cached
            assert session_manager._room_ids[session_id] == room_id

            # Verify yroom was added to kernel client
            assert mock_yroom in mock_kernel_client._yrooms

    @pytest.mark.asyncio
    async def test_skips_non_notebook_sessions(self, session_manager):
        """Test that non-notebook sessions are skipped."""
        session_id = "session-123"
        kernel_id = "kernel-456"

        # Mock get_session to return console session
        mock_session = {
            "id": session_id,
            "type": "console",
            "path": "/path/to/console"
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_get_session:
            mock_get_session.return_value = mock_session

            await session_manager._ensure_yroom_connected(session_id, kernel_id)

            # Verify no room_id was created
            assert session_id not in session_manager._room_ids

    @pytest.mark.asyncio
    async def test_skips_when_yroom_already_connected(self, session_manager, mock_yroom, mock_kernel_client):
        """Test that already-connected yrooms are not re-added."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        # Set up cached room_id
        session_manager._room_ids[session_id] = room_id

        # Mock yroom manager
        session_manager.yroom_manager.get_room.return_value = mock_yroom

        # Yroom already in kernel client's _yrooms
        mock_kernel_client._yrooms.add(mock_yroom)

        # Mock kernel manager
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        # Track initial state
        initial_yrooms_count = len(mock_kernel_client._yrooms)

        await session_manager._ensure_yroom_connected(session_id, kernel_id)

        # Verify yroom was not added again (count unchanged)
        assert len(mock_kernel_client._yrooms) == initial_yrooms_count

    @pytest.mark.asyncio
    async def test_handles_missing_yroom_gracefully(self, session_manager):
        """Test that missing yroom is handled gracefully without errors."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:missing-file-id"

        # Set up cached room_id
        session_manager._room_ids[session_id] = room_id

        # Mock yroom manager to return None (yroom doesn't exist)
        session_manager.yroom_manager.get_room.return_value = None

        # Should not raise an error
        await session_manager._ensure_yroom_connected(session_id, kernel_id)

    @pytest.mark.asyncio
    async def test_handles_kernel_client_without_yrooms_attribute(self, session_manager, mock_yroom):
        """Test graceful handling when kernel client doesn't have _yrooms attribute."""
        session_id = "session-123"
        kernel_id = "kernel-456"
        room_id = "json:notebook:test-file-id"

        # Set up cached room_id
        session_manager._room_ids[session_id] = room_id

        # Mock yroom manager
        session_manager.yroom_manager.get_room.return_value = mock_yroom

        # Mock kernel client WITHOUT _yrooms attribute
        mock_kernel_client = Mock(spec=[])  # Empty spec, no _yrooms

        # Mock kernel manager
        mock_kernel_manager = Mock()
        mock_kernel_manager.kernel_client = mock_kernel_client
        session_manager.serverapp.kernel_manager.get_kernel.return_value = mock_kernel_manager

        # Should not raise an error
        await session_manager._ensure_yroom_connected(session_id, kernel_id)


class TestGetSession:
    """Tests for get_session method override."""

    @pytest.mark.asyncio
    async def test_calls_ensure_yroom_connected(self, session_manager):
        """Test that get_session calls _ensure_yroom_connected for notebook sessions."""
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

                # Verify _ensure_yroom_connected was called
                mock_ensure.assert_called_once_with(session_id, kernel_id)

                # Verify session was returned
                assert result == mock_session

    @pytest.mark.asyncio
    async def test_handles_none_session(self, session_manager):
        """Test that get_session handles None session gracefully."""
        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_super_get_session:
            mock_super_get_session.return_value = None

            with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock) as mock_ensure:
                result = await session_manager.get_session(session_id="missing-session")

                # Verify _ensure_yroom_connected was NOT called
                mock_ensure.assert_not_called()

                # Verify None was returned
                assert result is None

    @pytest.mark.asyncio
    async def test_handles_session_without_kernel(self, session_manager):
        """Test that get_session handles sessions without kernel gracefully."""
        mock_session = {
            "id": "session-123",
            "kernel": None,
            "type": "notebook"
        }

        with patch.object(YDocSessionManager, 'get_session', new_callable=AsyncMock) as mock_super_get_session:
            mock_super_get_session.return_value = mock_session

            with patch.object(session_manager, '_ensure_yroom_connected', new_callable=AsyncMock) as mock_ensure:
                result = await session_manager.get_session(session_id="session-123")

                # Verify _ensure_yroom_connected was NOT called
                mock_ensure.assert_not_called()

                # Verify session was returned
                assert result == mock_session
