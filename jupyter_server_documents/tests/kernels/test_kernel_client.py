import pytest
from unittest.mock import MagicMock, patch

from jupyter_server_documents.kernels.kernel_client import DocumentAwareKernelClient
from jupyter_server_documents.kernels.message_cache import KernelMessageCache
from jupyter_server_documents.outputs import OutputProcessor


class TestDocumentAwareKernelClient:
    """Test cases for DocumentAwareKernelClient."""

    def test_default_message_cache(self):
        """Test that message cache is created by default."""
        client = DocumentAwareKernelClient()
        assert isinstance(client.message_cache, KernelMessageCache)

    def test_default_output_processor(self):
        """Test that output processor is created by default."""
        client = DocumentAwareKernelClient()
        assert isinstance(client.output_processor, OutputProcessor)

    @pytest.mark.asyncio
    async def test_stop_listening_no_task(self):
        """Test that stop_listening does nothing when no task exists."""
        client = DocumentAwareKernelClient()
        client._listening_task = None
        
        # Should not raise an exception
        await client.stop_listening()

    def test_add_listener(self):
        """Test adding a listener."""
        client = DocumentAwareKernelClient()
        
        def test_listener(channel, msg):
            pass
        
        client.add_listener(test_listener)
        
        assert test_listener in client._listeners

    def test_remove_listener(self):
        """Test removing a listener."""
        client = DocumentAwareKernelClient()
        
        def test_listener(channel, msg):
            pass
        
        client.add_listener(test_listener)
        client.remove_listener(test_listener)
        
        assert test_listener not in client._listeners

    @pytest.mark.asyncio
    async def test_add_yroom(self):
        """Test adding a YRoom."""
        client = DocumentAwareKernelClient()
        
        mock_yroom = MagicMock()
        await client.add_yroom(mock_yroom)
        
        assert mock_yroom in client._yrooms

    @pytest.mark.asyncio
    async def test_remove_yroom(self):
        """Test removing a YRoom."""
        client = DocumentAwareKernelClient()
        
        mock_yroom = MagicMock()
        client._yrooms.add(mock_yroom)
        
        await client.remove_yroom(mock_yroom)
        
        assert mock_yroom not in client._yrooms

    def test_send_kernel_info_creates_message(self):
        """Test that send_kernel_info creates a kernel info message."""
        client = DocumentAwareKernelClient()
        
        # Mock session
        from jupyter_client.session import Session
        client.session = Session()
        
        with patch.object(client, 'handle_incoming_message') as mock_handle:
            client.send_kernel_info()
            
            # Verify that handle_incoming_message was called with shell channel
            mock_handle.assert_called_once()
            args, kwargs = mock_handle.call_args
            assert args[0] == "shell"  # Channel name
            assert isinstance(args[1], list)  # Message list

    @pytest.mark.asyncio
    async def test_handle_outgoing_message_control_channel(self):
        """Test that control channel messages bypass document handling."""
        client = DocumentAwareKernelClient()
        
        msg = [b"test", b"message"]
        
        with patch.object(client, 'handle_document_related_message') as mock_handle_doc:
            with patch.object(client, 'send_message_to_listeners') as mock_send:
                await client.handle_outgoing_message("control", msg)
                
                mock_handle_doc.assert_not_called()
                mock_send.assert_called_once_with("control", msg)