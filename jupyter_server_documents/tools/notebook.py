from typing import Literal, List, Dict, Any, Set
import nbformat

from jupyter_server.base.call_context import CallContext

from jupyter_server_documents.rooms.yroom import YRoom


def add_cell(
        file_path: str,
        content: str | None = None,
        cell_index: int | None = None,
        add_above: bool = False,
        cell_type: Literal["code", "markdown", "raw"] = "code"
    ):
    """Adds a new cell to the Jupyter notebook above or below a specified cell index.
    
    This function adds a new cell to a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        content: The content of the new cell. If None, an empty cell is created.
        cell_index: The zero-based index where the cell should be added. If None,
                   the cell is added at the end of the notebook.
        add_above: If True, the cell is added above the specified index. If False,
                  it's added below the specified index.
        cell_type: The type of cell to add ("code", "markdown").
    
    Returns:
        None
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    
    if ydoc:
        cells_count = ydoc.cell_number()
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

def delete_cell(file_path: str, cell_index: int):
    """Removes a notebook cell at the specified cell index.
    
    This function deletes a cell from a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly using nbformat.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        cell_index: The zero-based index of the cell to delete.
    
    Returns:
        None
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    if ydoc:
        if 0 <= cell_index < len(ydoc.cells):
            del ydoc.cells[cell_index]
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
        if 0 <= cell_index < len(notebook.cells):
            notebook.cells.pop(cell_index)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                nbformat.write(notebook, f)

def edit_cell(
        file_path: str,
        cell_index: int,
        content: str | None = None
    ) -> None:
    """Edits the content of a notebook cell at the specified index
    
    This function modifies the content of a cell in a Jupyter notebook. It first attempts to use
    the in-memory YDoc representation if the notebook is currently active. If the
    notebook is not active, it falls back to using the filesystem to read, modify,
    and write the notebook file directly using nbformat.
    
    Args:
        file_path: The absolute path to the notebook file on the filesystem.
        cell_index: The zero-based index of the cell to edit.
        content: The new content for the cell. If None, the cell content remains unchanged.
    
    Returns:
        None
        
    Raises:
        IndexError: If the cell_index is out of range for the notebook.
    """
    
    file_id = _get_file_id(file_path)
    ydoc = _get_jupyter_ydoc(file_id)
    
    if ydoc:
        cells_count = len(ydoc.cells)
        if 0 <= cell_index < cells_count:
            if content is not None:
                ydoc.cells[cell_index]["source"] = content
        else:
            raise IndexError(
                f"{cell_index=} is out of range for notebook at {file_path=} with {cells_count=}"
            )
    else:
        with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
        cell_count = len(notebook.cells)
        if 0 <= cell_index < cell_count:
            if content is not None:
                notebook.cells[cell_index].source = content
            
            with open(file_path, 'w', encoding='utf-8') as f:
                nbformat.write(notebook, f)
        else:
            raise IndexError(
                f"{cell_index=} is out of range for notebook at {file_path=} with {cell_count=}"
            )

def read_cell(file_path: str, cell_index: int) -> Dict[str, Any]:
    """Returns the content and metadata of a cell at the specified index"""
    
    with open(file_path, 'r', encoding='utf-8') as f:
            notebook = nbformat.read(f, as_version=nbformat.NO_CONVERT)
        
    cell_count = len(notebook.cells)
    if 0 <= cell_index < cell_count:
        cell = notebook.cells[cell_index]
        return cell
    else:
        raise IndexError(
            f"{cell_index=} is out of range for notebook at {file_path=} with {cell_count=}"
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

def _determine_insert_index(cells_count: int, cell_index: int, add_above: bool) -> int:
    if cell_index is None:
        insert_index = cells_count
    else:
        if not (0 <= cell_index < cells_count):
            cell_index = max(0, min(cell_index, cells_count))
        insert_index = cell_index if add_above else cell_index + 1
    return insert_index
