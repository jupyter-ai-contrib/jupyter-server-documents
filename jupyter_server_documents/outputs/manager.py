import json
import os
from pathlib import Path, PurePath
import shutil
import uuid

from pycrdt import Map
import nbformat

from traitlets.config import LoggingConfigurable
from traitlets import Dict, Instance, default

from jupyter_core.paths import jupyter_runtime_dir


# Private functions

def _create_output_url(file_id: str, cell_id: str, output_index: int = None) -> str:
    """Create the URL for an output or stream.

    Generates a standardized API URL path for accessing notebook cell outputs
    that have been stored separately from the notebook document.

    Args:
        file_id: The unique identifier of the notebook file.
        cell_id: The unique identifier of the cell within the notebook.
        output_index: The index of the output within the cell's output array.

    Returns:
        A URL path string in the format '/api/outputs/{file_id}/{cell_id}/{output_index}.output'.
    """
    return f"/api/outputs/{file_id}/{cell_id}/{output_index}.output"


def _create_output_placeholder(output_type: str, url: str) -> dict:
    """Build a placeholder output dict for the given output_type and url.

    Creates a minimal nbformat-compatible output placeholder that references the
    actual output data via a URL. These placeholders keep the YDoc lightweight
    while maintaining the structure needed for notebook rendering.

    Note:
        These placeholders intentionally use minimal structure (metadata-only in
        some cases) to reduce YDoc size. This deviates slightly from full nbformat
        spec but remains compatible.

    Args:
        output_type: The type of output ('stream', 'display_data', 'execute_result', or 'error').
        url: The URL where the actual output data can be retrieved.

    Returns:
        A dictionary containing the minimal output structure with metadata containing the URL.

    Raises:
        ValueError: If the output_type is not one of the recognized types.
    """
    metadata = dict(url=url)
    # These placeholders lack the full proper structure of the nbformat spec, but they are
    # allowed. We do this to keep the ydoc as small as possible. We should follow up
    # and make changes to nbformat to clarify what the minimal output is (basically metadata
    # only)
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


# Main OutputsManager class


class OutputsManager(LoggingConfigurable):
    """Base outputs manager with traditional Jupyter behavior.

    This manager:
    - Always saves outputs to notebook files
    - Keeps outputs out of YDoc using placeholders
    - Stores outputs in runtime directory for HTTP access
    """
    _last_output_index = Dict(default_value={})
    _output_index_by_display_id = Dict(default_value={})
    _display_ids_by_cell_id = Dict(default_value={})

    outputs_path = Instance(PurePath, help="The local runtime dir")

    @default("outputs_path")
    def _default_outputs_path(self):
        """Provide default path for outputs storage.

        Returns:
            Path: The default outputs directory within Jupyter's runtime directory.
        """
        return Path(jupyter_runtime_dir()) / "outputs"

    def _ensure_path(self, file_id, cell_id):
        """Ensure the directory structure exists for storing outputs.

        Creates nested directories for file_id/cell_id if they don't exist.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell within the notebook.
        """
        nested_dir = self.outputs_path / file_id / cell_id
        nested_dir.mkdir(parents=True, exist_ok=True)

    def _build_path(self, file_id, cell_id=None, output_index=None):
        """Build a filesystem path for output storage.

        Constructs a hierarchical path: outputs_path/file_id/cell_id/output_index.output

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell (optional).
            output_index: The index of the specific output (optional).

        Returns:
            Path: The constructed filesystem path.
        """
        path = self.outputs_path / file_id
        if cell_id is not None:
            path = path / cell_id
        if output_index is not None:
            path = path / f"{output_index}.output"
        return path

    def _compute_output_index(self, cell_id, display_id=None):
        """Compute the next output index for a cell.

        Maintains sequential output indexing per cell. If a display_id is provided,
        it ensures the same index is reused for updates to the same display output.
        This supports IPython's display update mechanism where outputs can be
        modified after initial creation.

        Args:
            cell_id: The unique identifier of the cell.
            display_id: Optional display identifier for updatable outputs.

        Returns:
            The next available output index for this cell, or the existing index
            if display_id was already assigned an index.
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

    def _upgrade_notebook_format(self, nb: dict) -> dict:
        """Upgrade notebook to nbformat >= 4.5 to ensure cell IDs exist.

        Cell IDs were introduced in nbformat 4.5 and are required for tracking
        outputs separately from the notebook document. This method upgrades
        older notebooks to ensure compatibility.

        Args:
            nb: The notebook dictionary (NotebookNode).

        Returns:
            The upgraded notebook with cell IDs and updated format version.
        """
        return nbformat.v4.upgrade(nb, from_version=nb.nbformat, from_minor=nb.nbformat_minor)

    def _ensure_cell_id(self, cell: dict) -> None:
        """Ensure a cell has an ID, creating one if missing.

        Mutates the cell dictionary in-place by adding a UUID-based ID if one
        doesn't already exist. This is necessary for cells that predate nbformat 4.5.

        Args:
            cell: The cell dictionary (NotebookNode) to check and potentially modify.
        """
        if not cell.get('id'):
            cell['id'] = str(uuid.uuid4())

    def _process_outputs_from_cell(self, file_id: str, cell_id: str, outputs: list) -> list:
        """Process outputs from a cell, writing to disk and creating placeholders.

        Iterates through all outputs in a cell, writes each to disk, and returns
        a list of placeholder outputs to be stored in the YDoc. If writing fails,
        the original output is preserved as a fallback.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.
            outputs: List of output dictionaries from the notebook cell.

        Returns:
            List of placeholder output objects (NotebookNode) to be stored in the YDoc.
        """
        placeholder_outputs = []
        for output in outputs:
            display_id = output.get('metadata', {}).get('display_id')

            # Save output to disk and replace with placeholder
            placeholder = None
            try:
                placeholder = self.write(
                    file_id,
                    cell_id,
                    output,
                    display_id,
                    asdict=True,
                )
            except Exception as e:
                # If we can't write the output to disk, keep the original
                placeholder = output

            if placeholder is not None:
                placeholder_outputs.append(nbformat.from_dict(placeholder))

        return placeholder_outputs

    def clear(self, file_id, cell_id=None):
        """Clear the output state and files for a specific cell.

        Removes all tracking data (indices, display_id mappings) and deletes
        output files from disk for the specified cell. This is typically called
        when a notebook is reloaded to ensure stale outputs are removed.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell to clear (optional).
        """
        self._last_output_index.pop(cell_id, None)
        display_ids = self._display_ids_by_cell_id.get(cell_id, [])
        for display_id in display_ids:
            self._output_index_by_display_id.pop(display_id, None)

        path = self._build_path(file_id, cell_id)
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass

    def get_output_index(self, display_id: str):
        """Retrieve the output index associated with a display ID.

        Args:
            display_id: The display identifier to lookup.

        Returns:
            The output index for the given display_id, or None if not found.
        """
        return self._output_index_by_display_id.get(display_id)

    def get_output(self, file_id, cell_id, output_index):
        """Retrieve a specific output from disk.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.
            output_index: The index of the output within the cell.

        Returns:
            The output dictionary parsed from the stored JSON file.

        Raises:
            FileNotFoundError: If the output file doesn't exist at the expected path.
        """
        path = self._build_path(file_id, cell_id, output_index)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = json.loads(f.read())
        return output

    def get_outputs(self, file_id, cell_id):
        """Retrieve all outputs for a cell from disk.

        Reads all output files for a given cell, sorted by their index numbers,
        and returns them as JSON strings. This is typically called when saving
        a notebook to restore full outputs from placeholders.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.

        Returns:
            List of JSON-serialized output dictionaries in index order. Returns
            an empty list if no outputs exist for the cell.
        """
        path = self._build_path(file_id, cell_id)
        if not os.path.isdir(path):
            return []

        output_files = [(f, int(f.stem)) for f in path.glob("*.output")]
        output_files.sort(key=lambda x: x[1])

        outputs = []
        for file_path, _ in output_files:
            with open(file_path, "r", encoding="utf-8") as f:
                output = f.read()
                outputs.append(output)

        return outputs

    def write(self, file_id, cell_id, output, display_id=None, asdict: bool = False) -> Map | dict:
        """Write an output to disk and return a placeholder for the YDoc.

        Stores the full output data as a JSON file on disk and creates a minimal
        placeholder that references the output via URL. The placeholder keeps the
        YDoc lightweight while maintaining access to the full output data.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.
            output: The output dictionary to write (must have 'output_type' key).
            display_id: Optional display identifier for updatable outputs.
            asdict: If True, return placeholder as dict; if False, return as pycrdt.Map.

        Returns:
            A placeholder output containing the URL reference, either as a pycrdt.Map
            (default) or as a plain dict (if asdict=True).
        """
        self._ensure_path(file_id, cell_id)
        index = self._compute_output_index(cell_id, display_id)
        path = self._build_path(file_id, cell_id, index)
        data = json.dumps(output, ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        url = _create_output_url(file_id, cell_id, index)
        placeholder = _create_output_placeholder(output["output_type"], url)
        if not asdict:
            placeholder = Map(placeholder)
        return placeholder

    def process_loaded_notebook(self, file_id: str, file_data: dict) -> dict:
        """Process a loaded notebook and handle outputs through the outputs manager.

        This method processes a notebook that has been loaded from disk.
        In base mode, outputs are always processed from the file.

        Args:
            file_id (str): The file identifier
            file_data (dict): The file data containing the notebook content
                from calling ContentsManager.get()

        Returns:
            dict: The modified file data with processed outputs
        """
        # Notebook content is a tree of nbformat.NotebookNode objects,
        # which are a subclass of dict.
        nb = file_data['content']
        # We need cell ids which are only in nbformat >4.5. We use this to
        # upgrade all notebooks to 4.5 or later
        nb = self._upgrade_notebook_format(nb)

        for cell in nb.get('cells', []):
            # Ensure all cells have IDs regardless of type
            self._ensure_cell_id(cell)

            if cell.get('cell_type') != 'code' or 'outputs' not in cell:
                continue

            cell_id = cell['id']

            # Clear existing outputs for this cell to avoid stale data
            self.clear(file_id, cell_id)

            cell['outputs'] = self._process_outputs_from_cell(
                file_id, cell_id, cell.get('outputs', [])
            )

        file_data['content'] = nb
        return file_data


    def process_saving_notebook(self, nb: dict, file_id: str) -> dict:
        """Process a notebook before saving to disk.

        This method is called when the yroom_file_api saves notebooks.
        The default implementation write the outputs to the notebook.

        Args:
            nb (dict): The notebook dict
            file_id (str): The file identifier

        Returns:
            dict: The modified notebook dict with outputs included
        """
        for cell in nb.get('cells', []):
            if cell.get('cell_type') == 'code':
                cell_id = cell.get('id')
                if cell_id:
                    # Get outputs from disk
                    output_strings = self.get_outputs(file_id=file_id, cell_id=cell_id)
                    # Parse JSON strings into dictionaries
                    outputs = [json.loads(output_string) for output_string in output_strings]
                    # Set the cell's outputs to the actual outputs
                    cell['outputs'] = outputs
                else:
                    # To be safe, create cell ID if one doesn't exist and clear outputs to remove placeholders
                    cell['id'] = str(uuid.uuid4())
                    cell['outputs'] = []

        return nb
