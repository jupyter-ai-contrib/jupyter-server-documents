import pytest
from unittest.mock import patch

from jupyter_server_documents.kernels.kernel_manager import NextGenKernelManager
from jupyter_server_documents.kernels.states import ExecutionStates, LifecycleStates


class TestNextGenKernelManager:
    """Test cases for NextGenKernelManager."""

    def test_set_state_lifecycle_only(self):
        """Test setting only lifecycle state."""
        km = NextGenKernelManager()
        km.set_state(LifecycleStates.STARTING)
        assert km.lifecycle_state == LifecycleStates.STARTING.value

    def test_set_state_execution_only(self):
        """Test setting only execution state."""
        km = NextGenKernelManager()
        km.set_state(execution_state=ExecutionStates.IDLE)
        assert km.execution_state == ExecutionStates.IDLE.value

    def test_set_state_both(self):
        """Test setting both lifecycle and execution states."""
        km = NextGenKernelManager()
        km.set_state(LifecycleStates.CONNECTED, ExecutionStates.BUSY)
        assert km.lifecycle_state == LifecycleStates.CONNECTED.value
        assert km.execution_state == ExecutionStates.BUSY.value

    def test_lifecycle_state_validation(self):
        """Test lifecycle state validation."""
        km = NextGenKernelManager()
        with pytest.raises(Exception):
            km.lifecycle_state = "invalid_state"

    def test_execution_state_validation(self):
        """Test execution state validation."""
        km = NextGenKernelManager()
        with pytest.raises(Exception):
            km.execution_state = "invalid_state"

    def test_execution_state_listener_non_iopub_channel(self):
        """Test execution state listener ignores non-iopub channels."""
        km = NextGenKernelManager()
        original_state = km.execution_state
        
        km.execution_state_listener("shell", [b"test", b"message"])
        
        # State should remain unchanged
        assert km.execution_state == original_state

    @pytest.mark.asyncio
    async def test_disconnect_without_client(self):
        """Test disconnecting when no client exists."""
        km = NextGenKernelManager()
        km.main_client = None
        
        # Should not raise an exception
        await km.disconnect()

    @pytest.mark.asyncio
    async def test_restart_kernel_sets_state(self):
        """Test that restart_kernel sets restarting state."""
        km = NextGenKernelManager()
        
        with patch('jupyter_client.manager.AsyncKernelManager.restart_kernel') as mock_restart:
            mock_restart.return_value = None
            await km.restart_kernel()
            
            assert km.lifecycle_state == LifecycleStates.RESTARTING.value
            mock_restart.assert_called_once()