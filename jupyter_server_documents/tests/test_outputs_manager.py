from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4

import pytest

from ..outputs import OutputsManager


def stream(text: str):
    return {
        "output_type": "stream",
        "name": "stdout",
        "text": text
    }

def display_data_text(text: str):
    return {
        "output_type": "display_data",
        "data": {
            "text/plain": text
        }
}

def test_instantiation():
    op = OutputsManager()
    assert isinstance(op, OutputsManager)

def test_paths():
    """Verify that the paths are working properly."""
    op = OutputsManager()
    file_id = str(uuid4())
    cell_id = str(uuid4())
    with TemporaryDirectory() as td:
        op.outputs_path = Path(td) / "outputs"
        output_index = 0
        assert op._build_path(file_id, cell_id, output_index) == \
            op.outputs_path / file_id / cell_id / f"{output_index}.output"

def test_stream():
    """Test stream outputs."""
    text = "0123456789"
    streams = list([stream(c) for c in text])
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        for s in streams:
            placeholder = op.write_output(file_id, cell_id, s)
            op.write_stream(file_id, cell_id, s, placeholder)
        assert op.get_stream(file_id, cell_id) == text

def test_display_data():
    """Test display data."""
    texts = [
        "Hello World!",
        "Hola Mundo!",
        "Bonjour le monde!"
    ]
    outputs = list([display_data_text(t) for t in texts])
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        for (i, output) in enumerate(outputs):
            op.write_output(file_id, cell_id, output)
        for (i, output) in enumerate(outputs):
            assert op.get_output(file_id, cell_id, i) == outputs[i]

def test_clear():
    """Test the clearing of outputs for a file_id."""
    output = display_data_text("Hello World!")
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        op.write_output(file_id, cell_id, output)
        path = op._build_path(file_id, cell_id, output_index=0)
        assert path.exists()
        op.clear(file_id)
        assert not path.exists()

def file_not_found():
    """Test to ensure FileNotFoundError is raised."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        with pytest.raises(FileNotFoundError):
            op.get_output('a','b',0)
        with pytest.raises(FileNotFoundError):
            op.get_stream('a','b')       


def test__compute_output_index_basic():
    """
    Test basic output index allocation for a cell without display ID
    """
    op = OutputsManager()
    
    # First output for a cell should be 0
    assert op._compute_output_index('cell1') == 0
    assert op._compute_output_index('cell1') == 1
    assert op._compute_output_index('cell1') == 2

def test__compute_output_index_with_display_id():
    """
    Test output index allocation with display IDs
    """
    op = OutputsManager()
    
    # First output for a cell with display ID
    assert op._compute_output_index('cell1', 'display1') == 0
    
    # Subsequent calls with same display ID should return the same index
    assert op._compute_output_index('cell1', 'display1') == 0
    
    # Different display ID should get a new index
    assert op._compute_output_index('cell1', 'display2') == 1


def test__compute_output_index_multiple_cells():
    """
    Test output index allocation across multiple cells
    """
    op = OutputsManager()
    
    assert op._compute_output_index('cell1') == 0
    assert op._compute_output_index('cell1') == 1
    assert op._compute_output_index('cell2') == 0
    assert op._compute_output_index('cell2') == 1

def test_display_id_index_retrieval():
    """
    Test retrieving output index for a display ID
    """
    op = OutputsManager()
    
    op._compute_output_index('cell1', 'display1')
    
    assert op.get_output_index('display1') == 0
    assert op.get_output_index('non_existent_display') is None

def test_display_ids():
    """
    Test tracking of display IDs for a cell
    """
    op = OutputsManager()
    
    # Allocate multiple display IDs for a cell
    op._compute_output_index('cell1', 'display1')
    op._compute_output_index('cell1', 'display2')
    
    # Verify display IDs are tracked
    assert 'cell1' in op._display_ids_by_cell_id
    assert set(op._display_ids_by_cell_id['cell1']) == {'display1', 'display2'}
    
    # Clear cell indices
    op.clear('file1', 'cell1')
    
    # Verify display IDs are cleared
    assert 'display1' not in op._display_ids_by_cell_id
    assert 'display2' not in op._display_ids_by_cell_id
