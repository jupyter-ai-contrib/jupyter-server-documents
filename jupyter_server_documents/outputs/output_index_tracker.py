import sys
from typing import Dict, Set, Optional

class OutputIndexTracker:
    __slots__ = [
        '_last_output_index', 
        '_display_id_to_output_index', 
        '_cell_display_ids'
    ]
    
    def __init__(self):
        # Dictionaries to track indices and display IDs
        self._last_output_index: Dict[str, int] = {}
        self._display_id_to_output_index: Dict[str, int] = {}
        self._cell_display_ids: Dict[str, Set[str]] = {}
    
    def _intern_key(self, key: str) -> str:
        """
        Intern string keys to reduce memory usage.
        Only use for keys that are likely to be repeated.
        """
        return sys.intern(key) if key else key
    
    def allocate_output_index(
        self, 
        cell_id: str, 
        display_id: Optional[str] = None
    ) -> int:
        # Intern keys to reduce memory
        cell_id = self._intern_key(cell_id)
        display_id = self._intern_key(display_id) if display_id else None
        
        # Retrieve the last index for this cell, defaulting to -1 if not found
        last_index = self._last_output_index.get(cell_id, -1)
        
        # If a display_id is provided, check for existing index
        if display_id:
            # If display_id already has an index, return that
            if display_id in self._display_id_to_output_index:
                return self._display_id_to_output_index[display_id]
            
            # Allocate a new index for this display_id
            new_index = last_index + 1
            self._display_id_to_output_index[display_id] = new_index
            
            # Track display_id for this cell
            if cell_id not in self._cell_display_ids:
                self._cell_display_ids[cell_id] = set()
            self._cell_display_ids[cell_id].add(display_id)
        else:
            # For non-display specific outputs, simply increment the last index
            new_index = last_index + 1
        
        # Update the last output index for the cell
        self._last_output_index[cell_id] = new_index
        
        return new_index
    
    def get_output_index(self, display_id: str) -> Optional[int]:
        """
        Retrieve the output index for a given display ID.
        
        Args:
            display_id (str): The display identifier.
        
        Returns:
            Optional[int]: The output index if found, None otherwise.
        """
        return self._display_id_to_output_index.get(display_id)
    
    def clear_cell_indices(self, cell_id: str) -> None:
        """
        Clear indices associated with a specific cell.
        
        Args:
            cell_id (str): The identifier of the cell to clear.
        """
        # Remove the last output index for this cell
        self._last_output_index.pop(cell_id, None)
        
        # Remove and clean up associated display IDs
        if cell_id in self._cell_display_ids:
            # Remove all display IDs associated with this cell from the output index mapping
            for display_id in self._cell_display_ids[cell_id]:
                self._display_id_to_output_index.pop(display_id, None)
            
            # Remove the cell's display ID tracking
            del self._cell_display_ids[cell_id]
