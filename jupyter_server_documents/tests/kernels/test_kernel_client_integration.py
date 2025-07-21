import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch
from jupyter_client.session import Session
from jupyter_server_documents.ydocs import YNotebook
import pycrdt

from jupyter_server_documents.kernels.kernel_client import DocumentAwareKernelClient
from jupyter_server_documents.rooms.yroom import YRoom
from jupyter_server_documents.outputs import OutputProcessor


class TestDocumentAwareKernelClientIntegration:
    """Integration tests for DocumentAwareKernelClient with YDoc updates."""

    @pytest.fixture
    def mock_yroom_with_notebook(self):
        """Create a mock YRoom with a real YNotebook."""
        # Create a real YDoc and YNotebook
        ydoc = pycrdt.Doc()
        awareness = MagicMock(spec=pycrdt.Awareness)  # Mock awareness instead of using real one
        ynotebook = YNotebook(ydoc, awareness)
        
        # Add a simple notebook structure with one cell
        ynotebook.set({
            "cells": [
                {
                    "cell_type": "code",
                    "id": "test-cell-1",
                    "source": "2 + 2",
                    "metadata": {},
                    "outputs": [],
                    "execution_count": None
                }
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3"
                },
                "language_info": {
                    "name": "python",
                    "version": "3.9.0"
                }
            },
            "nbformat": 4,
            "nbformat_minor": 4
        })
        
        # Create mock YRoom
        yroom = MagicMock(spec=YRoom)
        yroom.get_jupyter_ydoc = AsyncMock(return_value=ynotebook)
        yroom.get_awareness = MagicMock(return_value=awareness)
        
        return yroom, ynotebook

    @pytest.fixture
    def kernel_client_with_yroom(self, mock_yroom_with_notebook):
        """Create a DocumentAwareKernelClient with a real YRoom and YNotebook."""
        yroom, ynotebook = mock_yroom_with_notebook
        
        client = DocumentAwareKernelClient()
        client.session = Session()
        client.log = MagicMock()
        
        # Add the YRoom to the client
        client._yrooms = {yroom}
        
        # Mock output processor
        client.output_processor = MagicMock(spec=OutputProcessor)
        client.output_processor.process_output = MagicMock()
        
        return client, yroom, ynotebook

    def create_kernel_message(self, session, msg_type, content, parent_msg_id=None, cell_id=None):
        """Helper to create properly formatted kernel messages."""
        parent_header = {"msg_id": parent_msg_id} if parent_msg_id else {}
        metadata = {"cellId": cell_id} if cell_id else {}
        
        msg = session.msg(msg_type, content, parent=parent_header, metadata=metadata)
        return session.serialize(msg)

    @pytest.mark.asyncio
    async def test_execute_input_updates_execution_count(self, kernel_client_with_yroom):
        """Test that execute_input messages update execution count in YDoc."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={"cell_id": cell_id})
        
        # Create execute_input message
        content = {"code": "2 + 2", "execution_count": 1}
        msg_parts = self.create_kernel_message(
            client.session, "execute_input", content, parent_msg_id, cell_id
        )
        
        # Process the message
        await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify the execution count was updated in the YDoc
        cells = ynotebook.get_cell_list()
        target_cell = next((cell for cell in cells if cell.get("id") == cell_id), None)
        assert target_cell is not None
        assert target_cell.get("execution_count") == 1

    @pytest.mark.asyncio
    async def test_status_message_updates_cell_execution_state(self, kernel_client_with_yroom):
        """Test that status messages update cell execution state in YDoc."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id and channel
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={
            "cell_id": cell_id,
            "channel": "shell"
        })
        
        # Create status message with 'busy' state
        content = {"execution_state": "busy"}
        msg_parts = self.create_kernel_message(
            client.session, "status", content, parent_msg_id, cell_id
        )
        
        # Process the message
        await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify the cell execution state was updated to 'running' (converted from 'busy')
        cells = ynotebook.get_cell_list()
        target_cell = next((cell for cell in cells if cell.get("id") == cell_id), None)
        assert target_cell is not None
        assert target_cell.get("execution_state") == "running"

    @pytest.mark.asyncio
    async def test_kernel_info_reply_updates_language_info(self, kernel_client_with_yroom):
        """Test that kernel_info_reply updates language info in YDoc metadata."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache
        parent_msg_id = "kernel-info-request-123"
        client.message_cache.get = MagicMock(return_value={"cell_id": None})
        
        # Create kernel_info_reply message
        content = {
            "language_info": {
                "name": "python",
                "version": "3.9.0",
                "mimetype": "text/x-python",
                "file_extension": ".py"
            }
        }
        msg_parts = self.create_kernel_message(
            client.session, "kernel_info_reply", content, parent_msg_id
        )
        
        # Process the message
        await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify language info was updated in notebook metadata
        metadata = ynotebook.get_meta()
        assert "language_info" in metadata["metadata"]
        assert metadata["metadata"]["language_info"]["name"] == "python"
        assert metadata["metadata"]["language_info"]["version"] == "3.9.0"

    @pytest.mark.asyncio
    async def test_output_message_processed_and_suppressed(self, kernel_client_with_yroom):
        """Test that output messages are processed by output processor and suppressed."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={"cell_id": cell_id})
        
        # Create execute_result message (output)
        content = {
            "data": {"text/plain": "4"},
            "metadata": {},
            "execution_count": 1
        }
        msg_parts = self.create_kernel_message(
            client.session, "execute_result", content, parent_msg_id, cell_id
        )
        
        # Process the message
        result = await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify the output processor was called
        client.output_processor.process_output.assert_called_once_with(
            "execute_result", cell_id, content
        )
        
        # Verify the message was suppressed (returned None)
        assert result is None

    @pytest.mark.asyncio
    async def test_stream_output_message_processed(self, kernel_client_with_yroom):
        """Test that stream output messages are processed correctly."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={"cell_id": cell_id})
        
        # Create stream message
        content = {
            "name": "stdout",
            "text": "4\n"
        }
        msg_parts = self.create_kernel_message(
            client.session, "stream", content, parent_msg_id, cell_id
        )
        
        # Process the message
        result = await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify the output processor was called
        client.output_processor.process_output.assert_called_once_with(
            "stream", cell_id, content
        )
        
        # Verify the message was suppressed
        assert result is None

    @pytest.mark.asyncio
    async def test_error_output_message_processed(self, kernel_client_with_yroom):
        """Test that error output messages are processed correctly."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={"cell_id": cell_id})
        
        # Create error message
        content = {
            "ename": "NameError",
            "evalue": "name 'x' is not defined",
            "traceback": ["Traceback (most recent call last):", "NameError: name 'x' is not defined"]
        }
        msg_parts = self.create_kernel_message(
            client.session, "error", content, parent_msg_id, cell_id
        )
        
        # Process the message
        result = await client.handle_document_related_message(msg_parts[1:])  # Skip delimiter
        
        # Verify the output processor was called
        client.output_processor.process_output.assert_called_once_with(
            "error", cell_id, content
        )
        
        # Verify the message was suppressed
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_execution_flow(self, kernel_client_with_yroom):
        """Test complete execution flow: execute_input -> status -> output -> status."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        
        # Mock message cache to return cell_id and channel
        client.message_cache.get = MagicMock(return_value={
            "cell_id": cell_id,
            "channel": "shell"
        })
        
        # Step 1: Execute input
        execute_input_content = {"code": "2 + 2", "execution_count": 1}
        msg_parts = self.create_kernel_message(
            client.session, "execute_input", execute_input_content, parent_msg_id, cell_id
        )
        await client.handle_document_related_message(msg_parts[1:])
        
        # Step 2: Status busy
        status_busy_content = {"execution_state": "busy"}
        msg_parts = self.create_kernel_message(
            client.session, "status", status_busy_content, parent_msg_id, cell_id
        )
        await client.handle_document_related_message(msg_parts[1:])
        
        # Step 3: Execute result
        result_content = {
            "data": {"text/plain": "4"},
            "metadata": {},
            "execution_count": 1
        }
        msg_parts = self.create_kernel_message(
            client.session, "execute_result", result_content, parent_msg_id, cell_id
        )
        await client.handle_document_related_message(msg_parts[1:])
        
        # Step 4: Status idle
        status_idle_content = {"execution_state": "idle"}
        msg_parts = self.create_kernel_message(
            client.session, "status", status_idle_content, parent_msg_id, cell_id
        )
        await client.handle_document_related_message(msg_parts[1:])
        
        # Verify final state of the cell in YDoc
        cells = ynotebook.get_cell_list()
        target_cell = next((cell for cell in cells if cell.get("id") == cell_id), None)
        assert target_cell is not None
        assert target_cell.get("execution_count") == 1
        assert target_cell.get("execution_state") == "idle"
        
        # Verify output processor was called for the result
        client.output_processor.process_output.assert_called_with(
            "execute_result", cell_id, result_content
        )

    @pytest.mark.asyncio
    async def test_awareness_state_updates_for_kernel_status(self, kernel_client_with_yroom):
        """Test that kernel status updates awareness state."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return shell channel (for notebook-level status)
        parent_msg_id = "kernel-info-request-123"
        client.message_cache.get = MagicMock(return_value={
            "cell_id": None,
            "channel": "shell"
        })
        
        # Create status message for kernel-level state
        content = {"execution_state": "busy"}
        msg_parts = self.create_kernel_message(
            client.session, "status", content, parent_msg_id
        )
        
        # Process the message
        await client.handle_document_related_message(msg_parts[1:])
        
        # Verify awareness was updated
        awareness = yroom.get_awareness()
        awareness.set_local_state_field.assert_called_once_with(
            "kernel", {"execution_state": "busy"}
        )

    @pytest.mark.asyncio
    async def test_multiple_cells_execution_states(self, kernel_client_with_yroom):
        """Test that multiple cells can have different execution states."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Add another cell to the notebook
        cells = ynotebook.get_cell_list()
        ynotebook.append_cell({
            "cell_type": "code",
            "id": "test-cell-2",
            "source": "print('hello')",
            "metadata": {},
            "outputs": [],
            "execution_count": None
        })
        
        # Mock message cache to return different cell_ids
        def mock_get(msg_id):
            if msg_id == "execute-request-123":
                return {"cell_id": "test-cell-1", "channel": "shell"}
            elif msg_id == "execute-request-456":
                return {"cell_id": "test-cell-2", "channel": "shell"}
            return None
        
        client.message_cache.get = MagicMock(side_effect=mock_get)
        
        # Set first cell to busy
        content1 = {"execution_state": "busy"}
        msg_parts1 = self.create_kernel_message(
            client.session, "status", content1, "execute-request-123", "test-cell-1"
        )
        await client.handle_document_related_message(msg_parts1[1:])
        
        # Set second cell to idle
        content2 = {"execution_state": "idle"}
        msg_parts2 = self.create_kernel_message(
            client.session, "status", content2, "execute-request-456", "test-cell-2"
        )
        await client.handle_document_related_message(msg_parts2[1:])
        
        # Verify both cells have correct states
        cells = ynotebook.get_cell_list()
        cell1 = next((cell for cell in cells if cell.get("id") == "test-cell-1"), None)
        cell2 = next((cell for cell in cells if cell.get("id") == "test-cell-2"), None)
        
        assert cell1 is not None
        assert cell1.get("execution_state") == "running"  # 'busy' -> 'running'
        assert cell2 is not None
        assert cell2.get("execution_state") == "idle"

    @pytest.mark.asyncio
    async def test_message_without_cell_id_skips_cell_updates(self, kernel_client_with_yroom):
        """Test that messages without cell_id don't update cell-specific data."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return no cell_id
        parent_msg_id = "some-request-123"
        client.message_cache.get = MagicMock(return_value={"cell_id": None})
        
        # Create execute_input message without cell_id
        content = {"code": "2 + 2", "execution_count": 1}
        msg_parts = self.create_kernel_message(
            client.session, "execute_input", content, parent_msg_id
        )
        
        # Process the message
        await client.handle_document_related_message(msg_parts[1:])
        
        # Verify no cell was updated (execution_count should remain None)
        cells = ynotebook.get_cell_list()
        for cell in cells:
            assert cell.get("execution_count") is None

    @pytest.mark.asyncio
    async def test_display_data_message_processing(self, kernel_client_with_yroom):
        """Test that display_data messages are processed correctly."""
        client, yroom, ynotebook = kernel_client_with_yroom
        
        # Mock message cache to return cell_id
        parent_msg_id = "execute-request-123"
        cell_id = "test-cell-1"
        client.message_cache.get = MagicMock(return_value={"cell_id": cell_id})
        
        # Create display_data message
        content = {
            "data": {
                "text/plain": "Hello World",
                "text/html": "<p>Hello World</p>"
            },
            "metadata": {}
        }
        msg_parts = self.create_kernel_message(
            client.session, "display_data", content, parent_msg_id, cell_id
        )
        
        # Process the message
        result = await client.handle_document_related_message(msg_parts[1:])
        
        # Verify the output processor was called
        client.output_processor.process_output.assert_called_once_with(
            "display_data", cell_id, content
        )
        
        # Verify the message was suppressed
        assert result is None