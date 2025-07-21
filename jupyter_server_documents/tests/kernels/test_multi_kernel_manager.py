import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jupyter_server_documents.kernels.multi_kernel_manager import NextGenMappingKernelManager


@pytest.fixture
def multi_kernel_manager():
    """Create a NextGenMappingKernelManager instance for testing."""
    mkm = NextGenMappingKernelManager()
    mkm._check_kernel_id = MagicMock()
    mkm.pinned_superclass = MagicMock()
    mkm.pinned_superclass._async_restart_kernel = AsyncMock()
    return mkm


class TestNextGenMappingKernelManager:
    """Test cases for NextGenMappingKernelManager."""

    def test_start_watching_activity_noop(self, multi_kernel_manager):
        """Test that start_watching_activity does nothing."""
        # Should not raise an exception
        multi_kernel_manager.start_watching_activity("test-kernel-id")

    def test_stop_buffering_noop(self, multi_kernel_manager):
        """Test that stop_buffering does nothing."""
        # Should not raise an exception
        multi_kernel_manager.stop_buffering("test-kernel-id")

    @pytest.mark.asyncio
    async def test_restart_kernel_checks_id(self, multi_kernel_manager):
        """Test that restart_kernel checks kernel ID."""
        kernel_id = "test-kernel-id"
        
        await multi_kernel_manager.restart_kernel(kernel_id)
        
        multi_kernel_manager._check_kernel_id.assert_called_once_with(kernel_id)

    @pytest.mark.asyncio
    async def test_restart_kernel_calls_superclass(self, multi_kernel_manager):
        """Test that restart_kernel calls the superclass method."""
        kernel_id = "test-kernel-id"
        
        await multi_kernel_manager.restart_kernel(kernel_id, now=True)
        
        multi_kernel_manager.pinned_superclass._async_restart_kernel.assert_called_once_with(
            multi_kernel_manager, kernel_id, now=True
        )

    @pytest.mark.asyncio
    async def test_restart_kernel_default_now_parameter(self, multi_kernel_manager):
        """Test that restart_kernel uses default now=False."""
        kernel_id = "test-kernel-id"
        
        await multi_kernel_manager.restart_kernel(kernel_id)
        
        multi_kernel_manager.pinned_superclass._async_restart_kernel.assert_called_once_with(
            multi_kernel_manager, kernel_id, now=False
        )

    @pytest.mark.asyncio
    async def test_restart_kernel_propagates_exceptions(self, multi_kernel_manager):
        """Test that restart_kernel propagates exceptions from superclass."""
        kernel_id = "test-kernel-id"
        test_exception = Exception("Test restart error")
        multi_kernel_manager.pinned_superclass._async_restart_kernel.side_effect = test_exception
        
        with pytest.raises(Exception, match="Test restart error"):
            await multi_kernel_manager.restart_kernel(kernel_id)

    @pytest.mark.asyncio
    async def test_restart_kernel_propagates_id_check_exceptions(self, multi_kernel_manager):
        """Test that restart_kernel propagates exceptions from kernel ID check."""
        kernel_id = "invalid-kernel-id"
        test_exception = ValueError("Invalid kernel ID")
        multi_kernel_manager._check_kernel_id.side_effect = test_exception
        
        with pytest.raises(ValueError, match="Invalid kernel ID"):
            await multi_kernel_manager.restart_kernel(kernel_id)
        
        # Superclass method should not be called if ID check fails
        multi_kernel_manager.pinned_superclass._async_restart_kernel.assert_not_called()