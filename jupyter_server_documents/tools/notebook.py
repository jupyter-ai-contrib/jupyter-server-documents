from typing import Literal, List, Dict, Any, Set
import nbformat

from jupyter_server.base.call_context import CallContext

from jupyter_server_documents.rooms.yroom import YRoom


def add_cell(
        file_path: str,
        content: str | None = None,
        cell_id: str | None = None,
        add_above: bool = False,
        cell_type: Literal["code", "markdown", "raw"] = "code"
    ):
    """Adds a new cell to the Jupyter notebook above or below a specified cell.
    
    This function adds a new cell to a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        content: The content of the new cell. If None, an empty cell is created.
        cell_id: The UUID of the cell to add relative to. If None,
                the cell is added at the end of the notebook.
        add_above: If True, the cell is added above the specified cell. If False,
                  it's added below the specified cell.
        cell_type: The type of cell to add ("code", "markdown", "raw").
    
    Returns:
        None
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    
    if ydoc:
        cells_count = ydoc.cell_number()
        cell_index = _get_cell_index_from_id(ydoc, cell_id) if cell_id else None
        insert_index = _determine_insert_index(cells_count, cell_index, add_above)
        ycell = ydoc.create_ycell({
            "cell_type": cell_type,
            "source": content or "",
        })
        ydoc.cells.insert(insert_index, ycell)
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
        cells_count = len(notebook.cells)
        cell_index = _get_cell_index_from_id_nbformat(notebook, cell_id) if cell_id else None
        insert_index = _determine_insert_index(cells_count, cell_index, add_above)
        
        if cell_type == "code":
            notebook.cells.insert(insert_index, nbformat.v4.new_code_cell(
                source=content or ""
            ))
        elif cell_type == "markdown":
            notebook.cells.insert(insert_index, nbformat.v4.new_markdown_cell(
                source=content or ""
            ))
        else:
            notebook.cells.insert(insert_index, nbformat.v4.new_raw_cell(
                source=content or ""
            ))
        
        with open(file_path, 'w', encoding='utf-8') as f:
            nbformat.write(notebook, f)

def delete_cell(file_path: str, cell_id: str):
    """Removes a notebook cell with the specified cell ID.
    
    This function deletes a cell from a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly using nbformat.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        cell_id: The UUID of the cell to delete.
    
    Returns:
        None
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    if ydoc:
        cell_index = _get_cell_index_from_id(ydoc, cell_id)
        if cell_index is not None and 0 <= cell_index < len(ydoc.cells):
            del ydoc.cells[cell_index]
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
        cell_index = _get_cell_index_from_id_nbformat(notebook, cell_id)
        if cell_index is not None and 0 <= cell_index < len(notebook.cells):
            notebook.cells.pop(cell_index)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                nbformat.write(notebook, f)

def edit_cell(
        file_path: str,
        cell_id: str,
        content: str | None = None
    ) -> None:
    """Edits the content of a notebook cell with the specified ID
    
    This function modifies the content of a cell in a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly using nbformat.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        cell_id: The UUID of the cell to edit.
        content: The new content for the cell. If None, the cell content remains unchanged.
    
    Returns:
        None
        
    Raises:
        ValueError: If the cell_id is not found in the notebook.
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    
    if ydoc:
        cell_index = _get_cell_index_from_id(ydoc, cell_id)
        if cell_index is not None:
            if content is not None:
                ydoc.cells[cell_index]["source"] = content
        else:
            raise ValueError(
                f"Cell with {cell_id=} not found in notebook at {file_path=}"
            )
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
        cell_index = _get_cell_index_from_id_nbformat(notebook, cell_id)
        if cell_index is not None:
            if content is not None:
                notebook.cells[cell_index].source = content
            
            with open(file_path, 'w', encoding='utf-8') as f:
                nbformat.write(notebook, f)
        else:
            raise ValueError(
                f"Cell with {cell_id=} not found in notebook at {file_path=}"
            )

def read_cell(file_path: str, cell_id: str) -> Dict[str, Any]:
    """Returns the content and metadata of a cell with the specified ID"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
        notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
    
    cell_index = _get_cell_index_from_id_nbformat(notebook, cell_id)
    if cell_index is not None:
        cell = notebook.cells[cell_index]
        return cell
    else:
        raise ValueError(
            f"Cell with {cell_id=} not found in notebook at {file_path=}"
        )

def read_notebook(file_id: str) -> str:
    """Returns the complete notebook content as markdown string"""
    pass

def read_notebook_source(file_id: str) -> Dict[str, Any]:
    """Returns the complete notebook content including metadata"""
    pass

def summarize_notebook(file_id: str, max_length: int = 500) -> str:
    """Generates a summary of the notebook content"""
    pass


def _get_serverapp():
    handler = CallContext.get(CallContext.JUPYTER_HANDLER)
    serverapp = handler.serverapp
    return serverapp

def _get_jupyter_ydoc(file_id: str) -> YRoom | None:
    serverapp = _get_serverapp()
    yroom_manager = serverapp.web_app.settings["yroom_manager"]
    room_id = f"json:notebook:{file_id}"
    if yroom_manager.has_room(room_id):
        yroom = yroom_manager.get_room(room_id)
        notebook = yroom.get_jupyter_ydoc()
        return notebook

def _get_file_id(file_path: str) -> str:
    serverapp = _get_serverapp()
    file_id_manager = serverapp.web_app.settings["file_id_manager"]
    file_id = file_id_manager.get_id(file_path)

    return file_id

def _get_cell_index_from_id(ydoc, cell_id: str) -> int | None:
    """Get cell index from cell_id using YDoc interface."""
    try:
        cell_index, _ = ydoc.find_cell(cell_id)
        return cell_index
    except (AttributeError, KeyError):
        return None

def _get_cell_index_from_id_nbformat(notebook, cell_id: str) -> int | None:
    """Get cell index from cell_id using nbformat interface."""
    for i, cell in enumerate(notebook.cells):
        if hasattr(cell, 'id') and cell.id == cell_id:
            return i
        elif hasattr(cell, 'metadata') and cell.metadata.get('id') == cell_id:
            return i
    return None

def _determine_insert_index(cells_count: int, cell_index: int, add_above: bool) -> int:
    if cell_index is None:
        insert_index = cells_count
    else:
        if not (0 <= cell_index < cells_count):
            cell_index = max(0, min(cell_index, cells_count))
        insert_index = cell_index if add_above else cell_index + 1
    return insert_index
