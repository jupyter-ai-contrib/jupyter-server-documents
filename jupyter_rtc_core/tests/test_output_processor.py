import json
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from ..outputs import OutputProcessor, OutputsManager


class OutputProcessorForTest(OutputProcessor):
    """Test subclass of OutputProcessor that overrides the settings property."""
    _test_settings = {}
    
    @property
    def settings(self):
        """Override the settings property to return a test dictionary."""
        return self._test_settings

@pytest.fixture
def output_processor():
    """Fixture that returns an instance of TestOutputProcessor."""
    return OutputProcessorForTest()

def create_incoming_message(cell_id):
    msg_id = str(uuid4())
    header = {"msg_id": msg_id, "msg_type": "execute_request"}
    parent_header = {}
    metadata = {"cellId": cell_id}
    msg = [json.dumps(item) for item in [header, parent_header, metadata]]
    return msg_id, msg

def test_instantiation():
    """Test instantiation of the output processor."""
    op = OutputProcessor()
    assert isinstance(op, OutputProcessor)

def test_incoming_message(output_processor):
    """Test incoming message processing."""
    with TemporaryDirectory() as td:
        op = output_processor
        om = OutputsManager()
        op.settings["outputs_manager"] = om
        op.outputs_path = Path(td) / "outputs"
        # Simulate the running of a cell
        cell_id = str(uuid4())
        msg_id, msg = create_incoming_message(cell_id)
        op.process_incoming_message('shell', msg)
        assert op.get_cell_id(msg_id) == cell_id
        assert op.get_msg_id(cell_id) == msg_id
        # Clear the cell_id
        op.clear(cell_id)
        assert op.get_cell_id(msg_id) is None
        assert op.get_msg_id(cell_id) is None
        # Simulate the running of a cell
        cell_id = str(uuid4())
        msg_id, msg = create_incoming_message(cell_id)
        op.process_incoming_message('shell', msg)
        assert op.get_cell_id(msg_id) == cell_id
        assert op.get_msg_id(cell_id) == msg_id
        # # Run it again without clearing to ensure it self clears
        cell_id = str(uuid4())
        msg_id, msg = create_incoming_message(cell_id)
        op.process_incoming_message('shell', msg)
        assert op.get_cell_id(msg_id) == cell_id
        assert op.get_msg_id(cell_id) == msg_id
