from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4

from ..outputs import OutputsManager

text = ''.join([str(i) for i in range(10)])

def so(i):
    return {
        "output_type": "stream",
        "name": "stdout",
        "text": str(i),
    }

stream_outputs = list([so(i) for i in range(10)])


def test_instantiation():
    op = OutputsManager()
    assert isinstance(op, OutputsManager)

def test_stream():
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        output_index = 0
        assert op._build_path(file_id, cell_id, output_index) == \
            op.outputs_path / file_id / cell_id / f"{output_index}.output"
        for stream in stream_outputs:
            op.write_stream(file_id, cell_id, stream)
        assert op.get_stream(file_id, cell_id) == text

