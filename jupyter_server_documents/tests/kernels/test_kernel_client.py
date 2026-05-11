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


class TestConsoleOutputPassthrough:
    """Tests for kernel console output passthrough (#225).

    When no YRooms are registered (e.g. kernel consoles), output messages
    must pass through to listeners unmodified rather than being intercepted
    by the output processor.
    """

    def _make_msg(self, session, msg_type, parent_msg_id, cell_id, content):
        """Build a properly signed message list for handle_document_related_message."""
        msg = session.msg(msg_type, content=content)
        msg["parent_header"] = {"msg_id": parent_msg_id}
        # Serialize produces: [ident, delimiter, signature, header, parent, metadata, content, buffers...]
        # handle_document_related_message expects the parts after delimiter: [sig, header, parent, meta, content, ...]
        parts = session.serialize(msg)
        # session.serialize returns [ident_bytes..., DELIM, sig, header, parent, meta, content, buffers]
        # feed_identities strips idents+delim, returning the rest
        _, msg_list = session.feed_identities(parts)
        return msg_list

    @pytest.mark.asyncio
    async def test_output_passes_through_without_yrooms(self):
        """Output messages must not be suppressed when _yrooms is empty."""
        from jupyter_client.session import Session

        client = DocumentAwareKernelClient()
        session = Session(key=b"test-key")
        client.session = session

        cell_id = "cell-123"
        parent_msg_id = "msg-456"

        client.message_cache.add({
            "msg_id": parent_msg_id,
            "channel": "shell",
            "cell_id": cell_id
        })

        msg_list = self._make_msg(
            session, "stream", parent_msg_id, cell_id,
            {"text": "hello\n", "name": "stdout"}
        )

        # No yrooms registered (console scenario)
        assert len(client._yrooms) == 0

        result = await client.handle_document_related_message(msg_list)

        # Message should pass through (not None)
        assert result is not None

    @pytest.mark.asyncio
    async def test_output_suppressed_with_yrooms(self):
        """Output messages must be intercepted when _yrooms is non-empty."""
        from jupyter_client.session import Session

        client = DocumentAwareKernelClient()
        session = Session(key=b"test-key")
        client.session = session

        cell_id = "cell-123"
        parent_msg_id = "msg-456"

        client.message_cache.add({
            "msg_id": parent_msg_id,
            "channel": "shell",
            "cell_id": cell_id
        })

        msg_list = self._make_msg(
            session, "stream", parent_msg_id, cell_id,
            {"text": "hello\n", "name": "stdout"}
        )

        # Add a mock yroom (notebook scenario)
        mock_yroom = MagicMock()
        client._yrooms.add(mock_yroom)

        with patch.object(client.output_processor, 'process_output') as mock_process:
            result = await client.handle_document_related_message(msg_list)

        # Message should be suppressed (output processor handled it)
        assert result is None
        mock_process.assert_called_once()
        args = mock_process.call_args[0]
        assert args[0] == "stream"
        assert args[1] == cell_id
