import pytest
from unittest.mock import MagicMock, patch
from tornado.websocket import WebSocketClosedError

from jupyter_server_documents.kernels.websocket_connection import NextGenKernelWebsocketConnection


class TestNextGenKernelWebsocketConnection:
    """Test cases for NextGenKernelWebsocketConnection."""

    def test_kernel_ws_protocol(self):
        """Test that the websocket protocol is set correctly."""
        assert NextGenKernelWebsocketConnection.kernel_ws_protocol == "v1.kernel.websocket.jupyter.org"

    def test_inheritance(self):
        """Test that the class inherits from BaseKernelWebsocketConnection."""
        from jupyter_server.services.kernels.connection.base import BaseKernelWebsocketConnection
        
        assert issubclass(NextGenKernelWebsocketConnection, BaseKernelWebsocketConnection)
        
        # Test that required methods are implemented
        conn = NextGenKernelWebsocketConnection()
        assert hasattr(conn, 'connect')
        assert hasattr(conn, 'disconnect')
        assert hasattr(conn, 'handle_incoming_message')
        assert hasattr(conn, 'handle_outgoing_message')
        assert hasattr(conn, 'kernel_ws_protocol')

    @patch('jupyter_server_documents.kernels.websocket_connection.deserialize_msg_from_ws_v1')
    def test_handle_incoming_message_deserializes(self, mock_deserialize):
        """Test that incoming messages are deserialized correctly."""
        conn = NextGenKernelWebsocketConnection()
        
        # Mock the kernel_manager property
        mock_kernel_manager = MagicMock()
        mock_kernel_manager.main_client = MagicMock()
        
        with patch.object(type(conn), 'kernel_manager', mock_kernel_manager):
            mock_deserialize.return_value = ("shell", [b"test", b"message"])
            
            incoming_msg = b"test_websocket_message"
            conn.handle_incoming_message(incoming_msg)
            
            mock_deserialize.assert_called_once_with(incoming_msg)

    @patch('jupyter_server_documents.kernels.websocket_connection.deserialize_msg_from_ws_v1')
    def test_handle_incoming_message_no_client(self, mock_deserialize):
        """Test that incoming messages are ignored when no client exists."""
        conn = NextGenKernelWebsocketConnection()
        
        # Mock the kernel_manager property with no client
        mock_kernel_manager = MagicMock()
        mock_kernel_manager.main_client = None
        
        with patch.object(type(conn), 'kernel_manager', mock_kernel_manager):
            mock_deserialize.return_value = ("shell", [b"test", b"message"])
            
            incoming_msg = b"test_websocket_message"
            
            # Should not raise an exception
            conn.handle_incoming_message(incoming_msg)

    @patch('jupyter_server_documents.kernels.websocket_connection.serialize_msg_to_ws_v1')
    def test_handle_outgoing_message_removes_signature(self, mock_serialize):
        """Test that the signature is properly removed from outgoing messages."""
        conn = NextGenKernelWebsocketConnection()
        
        # Mock websocket_handler and log to avoid traitlet validation
        mock_handler = MagicMock()
        mock_log = MagicMock()
        
        with patch.object(type(conn), 'websocket_handler', mock_handler):
            with patch.object(type(conn), 'log', mock_log):
                mock_serialize.return_value = b"serialized_message"
                
                # Message with signature at index 0
                msg = [b"signature", b"header", b"parent", b"metadata", b"content"]
                conn.handle_outgoing_message("iopub", msg)
                
                # Should call serialize with msg[1:] (signature removed)
                mock_serialize.assert_called_once_with(
                    [b"header", b"parent", b"metadata", b"content"], "iopub"
                )

    @patch('jupyter_server_documents.kernels.websocket_connection.serialize_msg_to_ws_v1')
    def test_handle_outgoing_message_websocket_closed(self, mock_serialize):
        """Test that closed websocket errors are handled gracefully."""
        conn = NextGenKernelWebsocketConnection()
        
        mock_serialize.return_value = b"serialized_message"
        
        # Mock websocket_handler to raise WebSocketClosedError
        mock_handler = MagicMock()
        mock_handler.write_message.side_effect = WebSocketClosedError()
        mock_log = MagicMock()
        
        with patch.object(type(conn), 'websocket_handler', mock_handler):
            with patch.object(type(conn), 'log', mock_log):
                msg = [b"signature", b"header", b"parent", b"metadata", b"content"]
                conn.handle_outgoing_message("iopub", msg)
                
                mock_log.warning.assert_called_once_with(
                    "A ZMQ message arrived on a closed websocket channel."
                )

    @patch('jupyter_server_documents.kernels.websocket_connection.serialize_msg_to_ws_v1')
    def test_handle_outgoing_message_general_exception(self, mock_serialize):
        """Test that general exceptions are handled gracefully."""
        conn = NextGenKernelWebsocketConnection()
        
        mock_serialize.return_value = b"serialized_message"
        test_exception = Exception("Test exception")
        
        # Mock websocket_handler to raise exception
        mock_handler = MagicMock()
        mock_handler.write_message.side_effect = test_exception
        mock_log = MagicMock()
        
        with patch.object(type(conn), 'websocket_handler', mock_handler):
            with patch.object(type(conn), 'log', mock_log):
                msg = [b"signature", b"header", b"parent", b"metadata", b"content"]
                conn.handle_outgoing_message("iopub", msg)
                
                mock_log.error.assert_called_once_with(test_exception)