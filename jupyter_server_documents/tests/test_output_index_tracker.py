import pytest
import sys
from jupyter_server_documents.outputs.output_index_tracker import OutputIndexTracker

def test_basic_output_index_allocation():
    """
    Test basic output index allocation for a cell without display ID
    """
    tracker = OutputIndexTracker()
    
    # First output for a cell should be 0
    assert tracker.allocate_output_index('cell1') == 0
    assert tracker.allocate_output_index('cell1') == 1
    assert tracker.allocate_output_index('cell1') == 2

def test_output_index_with_display_id():
    """
    Test output index allocation with display IDs
    """
    tracker = OutputIndexTracker()
    
    # First output for a cell with display ID
    assert tracker.allocate_output_index('cell1', 'display1') == 0
    
    # Subsequent calls with same display ID should return the same index
    assert tracker.allocate_output_index('cell1', 'display1') == 0
    
    # Different display ID should get a new index
    assert tracker.allocate_output_index('cell1', 'display2') == 1

def test_multiple_cells_output_indices():
    """
    Test output index allocation across multiple cells
    """
    tracker = OutputIndexTracker()
    
    assert tracker.allocate_output_index('cell1') == 0
    assert tracker.allocate_output_index('cell1') == 1
    assert tracker.allocate_output_index('cell2') == 0
    assert tracker.allocate_output_index('cell2') == 1

def test_display_id_index_retrieval():
    """
    Test retrieving output index for a display ID
    """
    tracker = OutputIndexTracker()
    
    tracker.allocate_output_index('cell1', 'display1')
    
    assert tracker.get_output_index('display1') == 0
    assert tracker.get_output_index('non_existent_display') is None

def test_clear_cell_indices():
    """
    Test clearing indices for a specific cell
    """
    tracker = OutputIndexTracker()
    
    # Allocate some indices
    tracker.allocate_output_index('cell1', 'display1')
    tracker.allocate_output_index('cell1', 'display2')
    tracker.allocate_output_index('cell2')
    
    # Clear cell1 indices
    tracker.clear_cell_indices('cell1')
    
    # Verify cell1 indices are cleared
    assert 'cell1' not in tracker._last_output_index
    assert 'display1' not in tracker._display_id_to_output_index
    assert 'display2' not in tracker._display_id_to_output_index
    
    # Verify cell2 indices remain
    assert 'cell2' in tracker._last_output_index

def test_cell_display_ids_tracking():
    """
    Test tracking of display IDs for a cell
    """
    tracker = OutputIndexTracker()
    
    # Allocate multiple display IDs for a cell
    tracker.allocate_output_index('cell1', 'display1')
    tracker.allocate_output_index('cell1', 'display2')
    
    # Verify display IDs are tracked
    assert 'cell1' in tracker._cell_display_ids
    assert set(tracker._cell_display_ids['cell1']) == {'display1', 'display2'}
    
    # Clear cell indices
    tracker.clear_cell_indices('cell1')
    
    # Verify display IDs are cleared
    assert 'cell1' not in tracker._cell_display_ids