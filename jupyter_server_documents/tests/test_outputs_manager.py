from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4

import pytest
import json
import nbformat
from unittest.mock import patch

from ..outputs import OutputsManager
from ..outputs.manager import _create_output_url, _create_output_placeholder


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

def execute_result_text(text: str, execution_count: int = 1):
    return {
        "output_type": "execute_result",
        "execution_count": execution_count,
        "data": {
            "text/plain": text
        }
    }

def error_output(ename: str = "ValueError", evalue: str = "test error"):
    return {
        "output_type": "error",
        "ename": ename,
        "evalue": evalue,
        "traceback": [f"Traceback: {ename}: {evalue}"]
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
            op.write(file_id, cell_id, output)
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
        op.write(file_id, cell_id, output)
        path = op._build_path(file_id, cell_id, output_index=0)
        assert path.exists()
        op.clear(file_id)
        assert not path.exists()

def test_file_not_found_legacy():
    """Test to ensure FileNotFoundError is raised (legacy test)."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        with pytest.raises(FileNotFoundError):
            op.get_output('a','b',0)       


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


# Tests for private utility functions

def test_create_output_url():
    """Test URL creation for outputs."""
    file_id = "file123"
    cell_id = "cell456"
    output_index = 5

    url = _create_output_url(file_id, cell_id, output_index)
    expected = f"/api/outputs/{file_id}/{cell_id}/{output_index}.output"
    assert url == expected


def test_create_output_placeholder_all_types():
    """Test placeholder creation for all valid output types."""
    url = "/api/outputs/file1/cell1/0.output"

    # Test stream placeholder
    stream_placeholder = _create_output_placeholder("stream", url)
    assert stream_placeholder == {
        "output_type": "stream",
        "text": "",
        "metadata": {"url": url}
    }

    # Test display_data placeholder
    display_placeholder = _create_output_placeholder("display_data", url)
    assert display_placeholder == {
        "output_type": "display_data",
        "metadata": {"url": url}
    }

    # Test execute_result placeholder
    result_placeholder = _create_output_placeholder("execute_result", url)
    assert result_placeholder == {
        "output_type": "execute_result",
        "metadata": {"url": url}
    }

    # Test error placeholder
    error_placeholder = _create_output_placeholder("error", url)
    assert error_placeholder == {
        "output_type": "error",
        "metadata": {"url": url}
    }


def test_create_output_placeholder_invalid_type():
    """Test that invalid output types raise ValueError."""
    url = "/api/outputs/file1/cell1/0.output"

    with pytest.raises(ValueError, match="Unknown output_type: invalid_type"):
        _create_output_placeholder("invalid_type", url)


# Error handling and edge case tests

def test_get_output_file_not_found():
    """Test FileNotFoundError when output file doesn't exist."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"

        with pytest.raises(FileNotFoundError, match="The output file doesn't exist"):
            op.get_output('nonexistent_file', 'nonexistent_cell', 0)


def test_get_outputs_nonexistent_directory():
    """Test get_outputs returns empty list for non-existent directory."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"

        outputs = op.get_outputs('nonexistent_file', 'nonexistent_cell')
        assert outputs == []


def test_clear_nonexistent_path():
    """Test clear handles non-existent paths gracefully."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"

        # Should not raise an exception
        op.clear('nonexistent_file', 'nonexistent_cell')


def test_write_missing_output_type():
    """Test write handles missing output_type gracefully."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Missing output_type should cause an error in placeholder creation
        output_without_type = {"data": {"text/plain": "test"}}

        with pytest.raises(KeyError):
            op.write(file_id, cell_id, output_without_type)


def test_ensure_path_creation():
    """Test that _ensure_path creates necessary directories."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Path shouldn't exist initially
        nested_dir = op.outputs_path / file_id / cell_id
        assert not nested_dir.exists()

        # _ensure_path should create it
        op._ensure_path(file_id, cell_id)
        assert nested_dir.exists()
        assert nested_dir.is_dir()


# Tests for different output types

def test_stream_outputs():
    """Test stream output handling."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        stream_output = stream("Hello from stdout!")
        placeholder = op.write(file_id, cell_id, stream_output, asdict=True)

        # Verify placeholder structure
        assert placeholder["output_type"] == "stream"
        assert placeholder["text"] == ""
        assert "url" in placeholder["metadata"]

        # Verify output can be retrieved
        retrieved = op.get_output(file_id, cell_id, 0)
        assert retrieved == stream_output


def test_execute_result_outputs():
    """Test execute_result output handling."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        result_output = execute_result_text("42", execution_count=5)
        placeholder = op.write(file_id, cell_id, result_output, asdict=True)

        # Verify placeholder structure
        assert placeholder["output_type"] == "execute_result"
        assert "url" in placeholder["metadata"]

        # Verify output can be retrieved
        retrieved = op.get_output(file_id, cell_id, 0)
        assert retrieved == result_output


def test_error_outputs():
    """Test error output handling."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        err_output = error_output("NameError", "name 'x' is not defined")
        placeholder = op.write(file_id, cell_id, err_output, asdict=True)

        # Verify placeholder structure
        assert placeholder["output_type"] == "error"
        assert "url" in placeholder["metadata"]

        # Verify output can be retrieved
        retrieved = op.get_output(file_id, cell_id, 0)
        assert retrieved == err_output


def test_mixed_output_types():
    """Test handling multiple different output types in one cell."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        outputs = [
            stream("Starting computation..."),
            display_data_text("intermediate result"),
            execute_result_text("final result", 1),
            error_output("Warning", "deprecated function")
        ]

        # Write all outputs
        for output in outputs:
            op.write(file_id, cell_id, output)

        # Verify all can be retrieved
        for i, expected_output in enumerate(outputs):
            retrieved = op.get_output(file_id, cell_id, i)
            assert retrieved == expected_output


# Advanced functionality tests

def test_write_with_display_id():
    """Test write with display_id parameter for updatable outputs."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        display_id = "display_123"

        # First write with display_id
        output1 = display_data_text("First version")
        placeholder1 = op.write(file_id, cell_id, output1, display_id=display_id, asdict=True)

        # Second write with same display_id should reuse same index
        output2 = display_data_text("Updated version")
        placeholder2 = op.write(file_id, cell_id, output2, display_id=display_id, asdict=True)

        # Should have same URL (same index)
        assert placeholder1["metadata"]["url"] == placeholder2["metadata"]["url"]

        # Should retrieve the updated output
        retrieved = op.get_output(file_id, cell_id, 0)
        assert retrieved == output2

        # Verify display_id index tracking
        assert op.get_output_index(display_id) == 0


def test_write_asdict_parameter():
    """Test write with asdict parameter."""
    from pycrdt import Map

    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        output = display_data_text("test")

        # Test asdict=False (default) - should return pycrdt.Map
        placeholder_map = op.write(file_id, cell_id, output, asdict=False)
        assert isinstance(placeholder_map, Map)

        # Test asdict=True - should return plain dict
        placeholder_dict = op.write(file_id, cell_id, output, asdict=True)
        assert isinstance(placeholder_dict, dict)
        assert not isinstance(placeholder_dict, Map)


def test_get_outputs_integration():
    """Test get_outputs returns properly ordered output strings."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Write multiple outputs
        outputs = [
            display_data_text("output 1"),
            stream("output 2"),
            execute_result_text("output 3", 1)
        ]

        for output in outputs:
            op.write(file_id, cell_id, output)

        # Get all outputs as JSON strings
        output_strings = op.get_outputs(file_id, cell_id)
        assert len(output_strings) == 3

        # Parse and verify they match original outputs
        parsed_outputs = [json.loads(output_string) for output_string in output_strings]
        assert parsed_outputs == outputs


def test_multiple_cells_isolation():
    """Test that outputs from different cells are properly isolated."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell1_id = str(uuid4())
        cell2_id = str(uuid4())

        # Write to cell 1
        output1 = display_data_text("cell 1 output")
        op.write(file_id, cell1_id, output1)

        # Write to cell 2
        output2 = display_data_text("cell 2 output")
        op.write(file_id, cell2_id, output2)

        # Verify isolation
        retrieved1 = op.get_output(file_id, cell1_id, 0)
        retrieved2 = op.get_output(file_id, cell2_id, 0)

        assert retrieved1 == output1
        assert retrieved2 == output2
        assert retrieved1 != retrieved2


def test_build_path_variations():
    """Test _build_path with different parameter combinations."""
    op = OutputsManager()
    op.outputs_path = Path("/test/outputs")

    file_id = "file123"
    cell_id = "cell456"
    output_index = 7

    # Test file_id only
    path1 = op._build_path(file_id)
    assert path1 == Path("/test/outputs/file123")

    # Test file_id + cell_id
    path2 = op._build_path(file_id, cell_id)
    assert path2 == Path("/test/outputs/file123/cell456")

    # Test all parameters
    path3 = op._build_path(file_id, cell_id, output_index)
    assert path3 == Path("/test/outputs/file123/cell456/7.output")


# Notebook processing method tests

def test_ensure_cell_id():
    """Test _ensure_cell_id creates ID when missing."""
    op = OutputsManager()

    # Cell without ID
    cell_without_id = {"cell_type": "code", "source": "print('hello')"}
    op._ensure_cell_id(cell_without_id)
    assert "id" in cell_without_id
    assert len(cell_without_id["id"]) == 36  # UUID length

    # Cell with existing ID should not change
    cell_with_id = {"cell_type": "code", "source": "print('hello')", "id": "existing_id"}
    original_id = cell_with_id["id"]
    op._ensure_cell_id(cell_with_id)
    assert cell_with_id["id"] == original_id


def test_upgrade_notebook_format():
    """Test _upgrade_notebook_format upgrades notebook."""
    op = OutputsManager()

    # Create a minimal old-format notebook using nbformat
    old_nb = nbformat.v4.new_notebook()
    old_nb.nbformat_minor = 4  # Pre-4.5 (no cell IDs)
    old_nb.cells = [nbformat.v4.new_code_cell("print('hello')")]

    upgraded_nb = op._upgrade_notebook_format(old_nb)

    # Should be upgraded to 4.5+
    assert upgraded_nb["nbformat"] == 4
    assert upgraded_nb["nbformat_minor"] >= 5


def test_process_outputs_from_cell():
    """Test _process_outputs_from_cell creates placeholders."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Original outputs
        outputs = [
            display_data_text("output 1"),
            stream("output 2")
        ]

        # Process outputs
        placeholder_outputs = op._process_outputs_from_cell(file_id, cell_id, outputs)

        # Should get list of placeholder NotebookNodes
        assert len(placeholder_outputs) == 2
        for placeholder in placeholder_outputs:
            assert hasattr(placeholder, 'metadata')  # NotebookNode characteristic
            assert 'url' in placeholder['metadata']

        # Original outputs should be saved to disk
        retrieved1 = op.get_output(file_id, cell_id, 0)
        retrieved2 = op.get_output(file_id, cell_id, 1)
        assert retrieved1 == outputs[0]
        assert retrieved2 == outputs[1]


def test_process_loaded_notebook():
    """Test process_loaded_notebook workflow."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())

        # Create notebook data with outputs using nbformat
        nb = nbformat.v4.new_notebook()
        nb.nbformat_minor = 4  # Will be upgraded
        code_cell = nbformat.v4.new_code_cell("print('hello')")
        code_cell.outputs = [display_data_text("hello output")]
        nb.cells = [
            code_cell,
            nbformat.v4.new_markdown_cell("# Title")
        ]

        file_data = {"content": nb}

        # Process loaded notebook
        result = op.process_loaded_notebook(file_id, file_data)

        # Verify notebook was upgraded
        nb = result["content"]
        assert nb["nbformat_minor"] >= 5

        # Verify cells have IDs
        for cell in nb["cells"]:
            assert "id" in cell

        # Verify code cell outputs were replaced with placeholders
        code_cell = nb["cells"][0]
        assert len(code_cell["outputs"]) == 1
        placeholder = code_cell["outputs"][0]
        assert "url" in placeholder["metadata"]

        # Verify original output was saved
        cell_id = code_cell["id"]
        retrieved = op.get_output(file_id, cell_id, 0)
        assert retrieved == display_data_text("hello output")


def test_process_saving_notebook():
    """Test process_saving_notebook restores outputs."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Write some outputs first
        outputs = [
            display_data_text("saved output 1"),
            stream("saved output 2")
        ]
        for output in outputs:
            op.write(file_id, cell_id, output)

        # Create notebook with placeholders (simulating loaded state)
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "code",
                    "id": cell_id,
                    "source": "print('hello')",
                    "outputs": []  # Placeholders would be here, but simplified
                }
            ]
        }

        # Process for saving
        result = op.process_saving_notebook(nb, file_id)

        # Verify outputs were restored
        code_cell = result["cells"][0]
        assert len(code_cell["outputs"]) == 2
        assert code_cell["outputs"] == outputs


def test_process_saving_notebook_missing_cell_id():
    """Test process_saving_notebook handles missing cell IDs."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())

        # Notebook with cell missing ID
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "cells": [
                {
                    "cell_type": "code",
                    "source": "print('hello')",
                    "outputs": [display_data_text("some output")]
                }
            ]
        }

        # Process for saving
        result = op.process_saving_notebook(nb, file_id)

        # Should have created cell ID and cleared outputs
        code_cell = result["cells"][0]
        assert "id" in code_cell
        assert len(code_cell["id"]) == 36  # UUID length
        assert code_cell["outputs"] == []


# Integration and workflow tests

def test_complete_load_modify_save_cycle():
    """Test complete workflow: load notebook → modify outputs → save notebook."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())

        # Step 1: Load notebook with outputs using nbformat
        nb = nbformat.v4.new_notebook()
        nb.nbformat_minor = 4
        code_cell = nbformat.v4.new_code_cell("print('original')")
        code_cell.outputs = [display_data_text("original output")]
        nb.cells = [code_cell]

        file_data = {"content": nb}

        loaded_result = op.process_loaded_notebook(file_id, file_data)
        cell_id = loaded_result["content"]["cells"][0]["id"]

        # Step 2: Modify by adding new output (simulating execution)
        new_output = stream("new execution output")
        op.write(file_id, cell_id, new_output)

        # Step 3: Save notebook (should include both outputs)
        save_result = op.process_saving_notebook(loaded_result["content"], file_id)

        # Verify both outputs are in saved notebook
        code_cell = save_result["cells"][0]
        assert len(code_cell["outputs"]) == 2
        assert code_cell["outputs"][0] == display_data_text("original output")
        assert code_cell["outputs"][1] == new_output


def test_error_handling_in_process_outputs_from_cell():
    """Test _process_outputs_from_cell handles write errors gracefully."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Mock the write method to fail
        def failing_write(*args, **kwargs):
            raise Exception("Simulated write failure")

        original_write = op.write
        op.write = failing_write

        try:
            # Should not raise exception, should keep original output
            outputs = [display_data_text("test output")]
            result = op._process_outputs_from_cell(file_id, cell_id, outputs)

            # Should get the original output back (not a placeholder)
            assert len(result) == 1
            # Should be NotebookNode but contain original data
            assert result[0]["data"]["text/plain"] == "test output"

        finally:
            op.write = original_write


def test_default_outputs_path():
    """Test that default outputs_path is set correctly."""
    op = OutputsManager()

    # Should be a Path object
    assert isinstance(op.outputs_path, (Path, type(Path())))

    # Should contain "outputs" in the path
    assert "outputs" in str(op.outputs_path)


def test_complex_display_id_workflow():
    """Test complex workflow with display ID updates."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())
        display_id = "progress_display"

        # Initial output with display_id
        initial = display_data_text("Progress: 0%")
        op.write(file_id, cell_id, initial, display_id=display_id)

        # Update same display_id multiple times
        updates = [
            display_data_text("Progress: 25%"),
            display_data_text("Progress: 50%"),
            display_data_text("Progress: 100%")
        ]

        for update in updates:
            op.write(file_id, cell_id, update, display_id=display_id)

        # Should only have one output (the final update)
        outputs = op.get_outputs(file_id, cell_id)
        assert len(outputs) == 1

        retrieved = json.loads(outputs[0])
        assert retrieved == display_data_text("Progress: 100%")

        # Display ID should still map to index 0
        assert op.get_output_index(display_id) == 0


def test_mixed_display_id_and_regular_outputs():
    """Test mixing display ID outputs with regular outputs."""
    with TemporaryDirectory() as td:
        op = OutputsManager()
        op.outputs_path = Path(td) / "outputs"
        file_id = str(uuid4())
        cell_id = str(uuid4())

        # Regular output (index 0)
        op.write(file_id, cell_id, stream("Starting..."))

        # Display ID output (index 1)
        display_id = "status"
        op.write(file_id, cell_id, display_data_text("Status: running"), display_id=display_id)

        # Another regular output (index 2)
        op.write(file_id, cell_id, stream("Continuing..."))

        # Update display ID (should still be index 1)
        op.write(file_id, cell_id, display_data_text("Status: completed"), display_id=display_id)

        # Another regular output (index 3)
        op.write(file_id, cell_id, stream("Finished."))

        # Verify all outputs
        outputs = op.get_outputs(file_id, cell_id)
        assert len(outputs) == 4

        parsed = [json.loads(output) for output in outputs]
        assert parsed[0] == stream("Starting...")
        assert parsed[1] == display_data_text("Status: completed")  # Updated
        assert parsed[2] == stream("Continuing...")
        assert parsed[3] == stream("Finished.")

        # Verify display ID mapping
        assert op.get_output_index(display_id) == 1


def test_clear_with_display_ids():
    """Test clear properly handles display ID cleanup."""
    op = OutputsManager()
    cell_id = str(uuid4())
    file_id = str(uuid4())

    # Set up some display IDs
    display_id1 = "display1"
    display_id2 = "display2"

    op._compute_output_index(cell_id, display_id1)
    op._compute_output_index(cell_id, display_id2)

    # Verify they're tracked
    assert op.get_output_index(display_id1) == 0
    assert op.get_output_index(display_id2) == 1
    assert cell_id in op._display_ids_by_cell_id

    # Clear the cell
    op.clear(file_id, cell_id)

    # Verify display IDs are cleaned up
    assert op.get_output_index(display_id1) is None
    assert op.get_output_index(display_id2) is None
    assert cell_id not in op._last_output_index
