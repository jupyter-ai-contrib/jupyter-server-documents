"""
Extend the YNotebook class with some useful utilities for searching Notebooks.
"""
import sys
# See compatibility note on `group` keyword in
# https://docs.python.org/3/library/importlib.metadata.html#entry-points
if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points
    
from jupyter_ydoc.ynotebook import YNotebook as UpstreamYNotebook


class YNotebook(UpstreamYNotebook):
    __doc__ = """
    Extends upstream YNotebook to include extra methods.
    
    Upstream docstring:
    """ + UpstreamYNotebook.__doc__
    
    _cell_indices: dict # a map from cell_id -> cell index in notebook

    def __init__(self, *args, **kwargs): 
        super().__init__(*args, **kwargs)
        self._cell_indices = {}
    
    @property
    def ymeta(self):
        """
        Returns the Y-meta.

        :return: The Y-meta.
        :rtype: :class:`pycrdt.Map`
        """
        return self._ymeta

    def find_cell(self, cell_id):
        """Find a cell with a given cell_id in the list of cells.
        
        This uses caching if we have seen the cell previously.
        """
        # Find the target_cell and its cell_index and cache
        target_cell = None
        cell_index = None
        try:
            # See if we have a cached value for the cell_index
            cell_index = self._cell_indices[cell_id]
            target_cell = self.ycells[cell_index]
        except KeyError:
            # Do a linear scan to find the cell
            cell_index, target_cell = self.scan_cells(cell_id)
        else:
            # Verify that the cached value still matches
            if target_cell["id"] != cell_id:
                cell_index, target_cell = self.scan_cells(cell_id)
        return cell_index, target_cell

    def scan_cells(self, cell_id):
        """Find the cell with a given cell_id in the list of cells.
        
        This does a simple linear scan of the cells, but in reverse order because
        we believe that users are more often running cells towards the end of the
        notebook.
        """
        target_cell = None
        cell_index = None
        for i in reversed(range(0, len(self.ycells))):
            cell = self.ycells[i]
            if cell["id"] == cell_id:
                target_cell = cell
                cell_index = i
                self._cell_indices[cell_id] = cell_index
                break
        return cell_index, target_cell



ydocs = {ep.name: ep.load() for ep in entry_points(group="jupyter_ydoc")}

# Replace the YNotebook with our local version
ydocs["notebook"] = YNotebook
