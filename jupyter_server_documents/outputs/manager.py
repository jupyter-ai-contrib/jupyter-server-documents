import json
import os
from pathlib import Path, PurePath
import shutil
import uuid

from pycrdt import Map
import nbformat

from traitlets.config import LoggingConfigurable
from traitlets import Dict, Instance, Int, default

from jupyter_core.paths import jupyter_runtime_dir


def _is_stream_output(output: dict) -> bool:
    """Check if an output is a stream output.

    Args:
        output (dict): The output dictionary

    Returns:
        bool: True if the output is a stream output, False otherwise
    """
    return output.get("output_type") == "stream"


class OutputsManager(LoggingConfigurable):
    _last_output_index = Dict(default_value={})
    _output_index_by_display_id = Dict(default_value={})
    _display_ids_by_cell_id = Dict(default_value={})
    _stream_count = Dict(default_value={})

    outputs_path = Instance(PurePath, help="The local runtime dir")
    stream_limit = Int(default_value=500, config=True, allow_none=True)

    @default("outputs_path")
    def _default_outputs_path(self):
        return Path(jupyter_runtime_dir()) / "outputs"

    def _ensure_path(self, file_id, cell_id):
        nested_dir = self.outputs_path / file_id / cell_id
        nested_dir.mkdir(parents=True, exist_ok=True)

    def _build_path(self, file_id, cell_id=None, output_index=None):
        path = self.outputs_path / file_id
        if cell_id is not None:
            path = path / cell_id
        if output_index is not None:
            path = path / f"{output_index}.output"
        return path
    
    def _compute_output_index(self, cell_id, display_id=None):
        """
        Computes next output index for a cell.
        
        Args:
            cell_id (str): The cell identifier
            display_id (str, optional): A display identifier. Defaults to None.
        
        Returns:
            int: The output index
        """
        last_index = self._last_output_index.get(cell_id, -1)
        if display_id:
            if cell_id not in self._display_ids_by_cell_id:
                self._display_ids_by_cell_id[cell_id] = {display_id}
            else:
                self._display_ids_by_cell_id[cell_id].add(display_id)
            index = self._output_index_by_display_id.get(display_id)
            if index is None:
                index = last_index + 1
                self._last_output_index[cell_id] = index
                self._output_index_by_display_id[display_id] = index
        else:
            index = last_index + 1
            self._last_output_index[cell_id] = index
        
        return index

    def get_output_index(self, display_id: str):
        """Returns output index for a cell by display_id"""
        return self._output_index_by_display_id.get(display_id)

    def get_output(self, file_id, cell_id, output_index):
        """Get an output by file_id, cell_id, and output_index."""
        path = self._build_path(file_id, cell_id, output_index)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = json.loads(f.read())
        return output

    def get_outputs(self, file_id, cell_id):
        """Get all outputs by file_id, cell_id.

        Returns all output files from disk in index order. The stream_limit logic
        is handled during write operations, so this method simply returns what's on disk.

        Returns:
            list[str]: List of JSON-serialized output dictionaries in index order.
        """
        path = self._build_path(file_id, cell_id)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"The output dir doesn't exist: {path}")

        output_files = [(f, int(f.stem)) for f in path.glob("*.output")]
        output_files.sort(key=lambda x: x[1])

        outputs = []
        for file_path, _ in output_files:
            with open(file_path, "r", encoding="utf-8") as f:
                output = f.read()
                outputs.append(output)

        return outputs

    def get_stream(self, file_id, cell_id):
        "Get the stream output for a cell by file_id and cell_id."
        path = self._build_path(file_id, cell_id) / "stream"
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = f.read()
        return output

    def _append_to_stream_file(self, file_id, cell_id, output):
        """Append stream text to the /stream file.

        Args:
            file_id (str): The file identifier
            cell_id (str): The cell identifier
            output (dict): The stream output dictionary
        """
        self._ensure_path(file_id, cell_id)
        path = self._build_path(file_id, cell_id) / "stream"
        text = output["text"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    def write(self, file_id, cell_id, output, display_id=None, asdict: bool = False) -> Map | dict:
        """Write a new output for file_id and cell_id.

        Returns a placeholder output (pycrdt.Map) or None if no placeholder
        output should be written to the ydoc.
        """
        placeholder = self.write_output(file_id, cell_id, output, display_id, asdict=asdict)
        if output["output_type"] == "stream" and self.stream_limit is not None:
            placeholder = self.write_stream(file_id, cell_id, output, placeholder, asdict=asdict)
        return placeholder

    def write_output(self, file_id, cell_id, output, display_id=None, asdict: bool = False) -> Map | dict:
        self._ensure_path(file_id, cell_id)
        index = self._compute_output_index(cell_id, display_id)
        path = self._build_path(file_id, cell_id, index)
        data = json.dumps(output, ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        url = create_output_url(file_id, cell_id, index)
        self.log.info(f"Wrote output: {url}")
        placeholder = create_placeholder_dict(output["output_type"], url)
        if not asdict:
            placeholder = Map(placeholder)
        return placeholder
    
    def write_stream(self, file_id, cell_id, output, placeholder, asdict : bool = False) -> Map | dict:
        # How many stream outputs have been written for this cell previously
        count = self._stream_count.get(cell_id, 0)

        # Go ahead and write the incoming stream
        self._ensure_path(file_id, cell_id)
        path = self._build_path(file_id, cell_id) / "stream"
        text = output["text"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
        url = create_output_url(file_id, cell_id)
        self.log.info(f"Wrote stream: {url}")
        # Increment the count
        count = count + 1
        self._stream_count[cell_id] = count

        # Now create the placeholder output
        if count < self.stream_limit:
            # Return the original placeholder if we haven't reached the limit
            placeholder = placeholder
        elif count == self.stream_limit:
            # Return a link to the full stream output
            placeholder = create_placeholder_dict("display_data", url, full=True)
            if not asdict:
                placeholder = Map(placeholder)
        elif count > self.stream_limit:
            # Return None to indicate that no placeholder should be written to the ydoc
            placeholder = None
        return placeholder

    def clear(self, file_id, cell_id=None):
        """Clear the state of the manager."""
        if cell_id is None:
            self._stream_count = {}
        else:
            self._stream_count.pop(cell_id, None)
            self._last_output_index.pop(cell_id, None)
            
            display_ids = self._display_ids_by_cell_id.get(cell_id, [])
            for display_id in display_ids:
                self._output_index_by_display_id.pop(display_id, None)

        path = self._build_path(file_id, cell_id)    
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass

    def process_loaded_notebook(self, file_id: str, file_data: dict) -> dict:
        """Process a loaded notebook and handle outputs through the outputs manager.

        This method processes a notebook that has been loaded from disk.
        If the notebook metadata has exclude_outputs set to True, 
        outputs are loaded from this OutputsManager and set as the cell outputs
        (as placeholders).
        
        Args:
            file_id (str): The file identifier
            file_data (dict): The file data containing the notebook content
                from calling ContentsManager.get()
            
        Returns:
            dict: The modified file data with processed outputs
        """
        self.log.info(f"Processing loaded notebook: {file_id}")

        # Notebook content is a tree of nbformat.NotebookNode objects,
        # which are a subclass of dict.
        nb = file_data['content']
        # We need cell ids which are only in nbformat >4.5. We use this to
        # upgrade all notebooks to 4.5 or later
        nb = nbformat.v4.upgrade(nb, from_version=nb.nbformat, from_minor=nb.nbformat_minor)
        
        # Check if the notebook metadata has exclude_outputs set to True
        if nb.get('metadata', {}).get('exclude_outputs') is True:
            nb = self._process_loaded_excluded_outputs(file_id=file_id, nb=nb)
        else:
            nb = self._process_loaded_included_outputs(file_id=file_id, nb=nb)           

        file_data['content'] = nb
        return file_data

    def _process_loaded_excluded_outputs(self, file_id: str, nb: dict) -> dict:
        """Process a notebook with excluded_outputs metadata set to True.
        
        This method processes notebooks that have been saved with no outputs on disk.
        In this case, the OutputsManager store the outputs by cell_id and this method
        attempts to load actual outputs from OutputsManager and creates placeholder outputs
        for each code cell. If no outputs exist on disk for a cell, the cell's
        outputs are set to an empty list.
        
        Args:
            file_id (str): The file identifier
            nb (dict): The notebook dictionary
            
        Returns:
            dict: The notebook with placeholder outputs inserted from OutputsManager
        """
        for cell in nb.get('cells', []):
            # Ensure all cells have IDs regardless of type
            if not cell.get('id'):
                cell['id'] = str(uuid.uuid4())
            
            if cell.get('cell_type') == 'code':
                cell_id = cell['id']
                try:
                    # Try to get outputs from disk
                    output_strings = self.get_outputs(file_id=file_id, cell_id=cell_id)
                    outputs = []
                    for output_string in output_strings:
                        output_dict = json.loads(output_string)
                        placeholder = create_placeholder_dict(
                            output_dict["output_type"],
                            url=create_output_url(file_id, cell_id)
                        )
                        outputs.append(placeholder)
                    cell['outputs'] = outputs
                except FileNotFoundError:
                    # No outputs on disk for this cell, set empty outputs
                    cell['outputs'] = []
        return nb

    def _process_loaded_included_outputs(self, file_id: str, nb: dict) -> dict:
        """Process a notebook that has outputs on disk.
        
        This method processes notebooks with actual output data in the cells.
        It saves existing outputs to OutputsManager and replaces them with placeholder
        outputs that reference the saved files. Outputs that already have
        a URL in their metadata are left as-is.
        
        Args:
            file_id (str): The file identifier
            nb (dict): The notebook dictionary
            
        Returns:
            dict: The notebook with outputs saved to OutputsManager and replaced with placeholders
        """
        for cell in nb.get('cells', []):
            # Ensure all cells have IDs regardless of type
            if not cell.get('id'):
                cell['id'] = str(uuid.uuid4())
                
            if cell.get('cell_type') != 'code' or 'outputs' not in cell:
                continue

            cell_id = cell['id']
            processed_outputs = []
            for output in cell.get('outputs', []):
                display_id = output.get('metadata', {}).get('display_id')
                url = output.get('metadata', {}).get('url')
                if url is None:
                    # Save output to disk and replace with placeholder
                    try:
                        placeholder = self.write(
                            file_id,
                            cell_id,
                            output,
                            display_id,
                            asdict=True,
                        )
                    except Exception as e:
                        self.log.error(f"Error writing output: {e}")
                        # If we can't write the output to disk, keep the original
                        placeholder = output
                else:
                    # In this case, there is a placeholder already so keep it
                    placeholder = output
                
                if placeholder is not None:
                    # A placeholder of None means to not add to the YDoc
                    processed_outputs.append(nbformat.from_dict(placeholder))
            
            # Replace the outputs with processed ones
            cell['outputs'] = processed_outputs
        return nb

    def process_saving_notebook(self, nb: dict, file_id: str) -> dict:
        """Process a notebook before saving to disk.

        This method is called when the yroom_file_api saves notebooks.

        The exclude_outputs metadata flag controls whether actual outputs are
        included in the saved notebook file. To track the default behavior of
        Jupyter we assume that it is not set at all. In this case, outputs are
        saved in the notebook on disk (or if exclude_outputs is set to false)
        and removed from the OutputsManager to ensure the saved file is the
        source of truth for outputs.

        If the user or frontend has set exclude_outputs to true, outputs are
        removed from the file saved to disk and retained in OutputsManager.

        Args:
            nb (dict): The notebook dict
            file_id (str): The file identifier

        Returns:
            dict: The modified notebook dict with outputs handled according to
                  the exclude_outputs flag
        """
        # Ensure metadata exists
        if 'metadata' not in nb:
            nb['metadata'] = {}

        # Check if we should exclude outputs from the saved file
        exclude_outputs = nb.get('metadata', {}).get('exclude_outputs', False)

        if exclude_outputs:
            # Exclude outputs: clear outputs for all code cells
            for cell in nb.get('cells', []):
                if cell.get('cell_type') == 'code':
                    # If outputs is already an empty list, call clear for this cell
                    if cell.get('outputs') == []:
                        cell_id = cell.get('id')
                        if cell_id:
                            self.clear(file_id, cell_id)

                    cell['outputs'] = []
        else:
            # Include outputs: restore actual outputs from disk for all code cells
            for cell in nb.get('cells', []):
                if cell.get('cell_type') == 'code':
                    cell_id = cell.get('id')
                    if cell_id:
                        try:
                            # Get outputs from disk
                            output_strings = self.get_outputs(file_id=file_id, cell_id=cell_id)
                            # Parse JSON strings into dictionaries
                            outputs = [json.loads(output_string) for output_string in output_strings]
                            # Set the cell's outputs to the actual outputs
                            cell['outputs'] = outputs
                            # Delete the outputs in OutputsManager, notebook on disk is the source of truth
                            self.clear(file_id=file_id, cell_id=cell_id)
                        except FileNotFoundError:
                            # No outputs on disk for this cell, set empty outputs to remove placeholders
                            cell['outputs'] = []
                    else:
                        # To be safe, create cell ID if one doesn't exist and clear outputs to remove placeholders
                        cell['id'] = str(uuid.uuid4())
                        cell['outputs'] = []

        return nb


def create_output_url(file_id: str, cell_id: str, output_index: int = None) -> str:
        """Create the URL for an output or stream.

        Parameters:
        - file_id (str): The ID of the file.
        - cell_id (str): The ID of the cell.
        - output_index (int, optional): The index of the output. If None, returns the stream URL.

        Returns:
        - str: The URL string for the output or stream.
        """
        if output_index is None:
            return f"/api/outputs/{file_id}/{cell_id}/stream"
        else:
            return f"/api/outputs/{file_id}/{cell_id}/{output_index}.output"

def create_placeholder_dict(output_type: str, url: str, full: bool = False) -> dict:
    """Build a placeholder output dict for the given output_type and url.
    
    If full is True and output_type is "display_data", returns a display_data output
    with an HTML link to the full stream output.

    Parameters:
    - output_type (str): The type of the output.
    - url (str): The URL associated with the output.
    - full (bool): Whether to create a full output placeholder with a link.

    Returns:
    - dict: The placeholder output dictionary.

    Raises:
    - ValueError: If the output_type is unknown.
    """
    metadata = dict(url=url)
    if full and output_type == "display_data":
        return {
            "output_type": "display_data",
            "data": {
                "text/html": f'<a href="{url}">Click this link to see the full stream output</a>'
            },
        }
    if output_type == "stream":
        return {"output_type": "stream", "text": "", "metadata": metadata}
    elif output_type == "display_data":
        return {"output_type": "display_data", "metadata": metadata}
    elif output_type == "execute_result":
        return {"output_type": "execute_result", "metadata": metadata}
    elif output_type == "error":
        return {"output_type": "error", "metadata": metadata}
    else:
        raise ValueError(f"Unknown output_type: {output_type}")

