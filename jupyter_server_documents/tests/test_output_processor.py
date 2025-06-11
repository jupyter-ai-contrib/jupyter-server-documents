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

def test_instantiation(output_processor):
    """Test instantiation of the output processor."""
    op = output_processor
    assert isinstance(op, OutputProcessor)

# TODO: Implement this
def test_output_task():
    pass
