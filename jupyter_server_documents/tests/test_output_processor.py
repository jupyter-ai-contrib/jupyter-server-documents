import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from ..outputs import OutputProcessor, OutputsManager

class TestOutputProcessor(OutputProcessor):

    settings = {}

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

# TODO: Implement this
def test_output_task():
    pass
