# THIS FILE IS EXPERIMENTAL AND MAY HAVE BUGS AND NEED UPDATING.
# TO use this, you will need to enable the /stream handler in handlers.py


import json
import os

import nbformat

from traitlets import Dict, Int

from .manager import (
    OutputsManager,
    _create_output_placeholder,
    _create_output_url,
)


# Private functions


def _is_stream_output(output: dict) -> bool:
    """Check if an output is a stream output.

    Args:
        output: The output dictionary to check.

    Returns:
        True if the output is a stream output, False otherwise.
    """
    return output.get("output_type") == "stream"


def _create_stream_url(file_id: str, cell_id: str) -> str:
    """Create the URL for a stream file.

    Generates a URL path for accessing aggregated stream outputs that have
    been written to a single stream file for a cell.

    Args:
        file_id: The unique identifier of the notebook file.
        cell_id: The unique identifier of the cell.

    Returns:
        A URL path string in the format '/api/outputs/{file_id}/{cell_id}/stream'.
    """
    return f"/api/outputs/{file_id}/{cell_id}/stream"


def _create_stream_placeholder(url: str) -> dict:
    """Build a stream placeholder output dict with a clickable link.

    Creates a display_data output containing an HTML link that users can click
    to view the full stream output. This placeholder is used when stream outputs
    exceed the configured stream_limit.

    Args:
        url: The URL where the full stream output can be accessed.

    Returns:
        A display_data output dictionary with an HTML link in the data field.
    """
    return {
        "output_type": "display_data",
        "data": {
            "text/html": f'<a href="{url}">Click this link to see the full stream output</a>'
        },
        "metadata": {},
    }


# OptimizedOutputsManager class


class OptimizedOutputsManager(OutputsManager):
    """Optimized outputs manager with exclude_outputs and stream_limit support.

    This manager extends BaseOutputsManager with optimizations for large notebooks
    and collaborative environments:
    - Defaults to exclude_outputs=True (outputs not saved to notebook file)
    - Respects stream_limit to aggregate large stream outputs into /stream files
    - Can fall back to base behavior when exclude_outputs=False for specific notebooks

    The stream_limit feature helps manage notebooks with verbose output by:
    1. Writing the first N stream outputs normally (where N = stream_limit)
    2. At the limit, replacing the output with a clickable link to the /stream file
    3. Appending all subsequent stream text only to the /stream file

    Attributes:
        stream_limit: Maximum number of stream outputs to write individually before
            aggregating into a /stream file. Set to None to disable this feature.
    """
    _stream_count = Dict(default_value={})
    _exclude_outputs_by_file = Dict(default_value={})

    stream_limit = Int(default_value=10, config=True, allow_none=True)

    def get_exclude_outputs(self, file_id: str) -> bool:
        """Get the current exclude_outputs setting for a file.

        Args:
            file_id: The file identifier.

        Returns:
            The exclude_outputs setting for this file. Returns True if never
            set (default behavior for optimized mode).
        """
        return self._exclude_outputs_by_file.get(file_id, True)

    def set_exclude_outputs(self, file_id: str, new_value: bool) -> None:
        """Set exclude_outputs for a file and handle transitions.

        This method is called during save operations to handle transitions between
        exclude_outputs modes:
        - True -> False: Delete stream files (no longer needed since outputs will be in file)
        - False -> True: No action needed (stream files will be created on next execution)

        Args:
            file_id: The file identifier.
            new_value: The new exclude_outputs value from notebook metadata.
        """
        old_value = self._exclude_outputs_by_file.get(file_id)

        if old_value == new_value:
            # No change needed
            return

        self.log.info(f"Setting exclude_outputs={new_value} for {file_id}")

        # Handle True->False transition: delete stream files
        if old_value and not new_value:
            self.log.info(f"Deleting stream files for {file_id}")
            self.delete_stream(file_id)

        # Update stored value
        self._exclude_outputs_by_file[file_id] = new_value

    def get_stream(self, file_id, cell_id):
        """Retrieve the aggregated stream output for a cell.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.

        Returns:
            The stream output text as a string.

        Raises:
            FileNotFoundError: If the stream file doesn't exist at the expected path.
        """
        path = self._build_path(file_id, cell_id) / "stream"
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The stream file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = f.read()
        return output

    def _append_to_stream_file(self, file_id, cell_id, output):
        """Append stream text to the /stream file.

        Creates or appends to a single stream file that aggregates all stream
        outputs for a cell. This is used when stream_limit is enabled.

        Args:
            file_id: The file identifier.
            cell_id: The cell identifier.
            output: The stream output dictionary containing 'text' field.
        """
        self._ensure_path(file_id, cell_id)
        path = self._build_path(file_id, cell_id) / "stream"
        text = output["text"]
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)

    def delete_stream(self, file_id: str, cell_id: str = None) -> None:
        """Delete /stream files for one or all cells.

        Args:
            file_id: The file identifier.
            cell_id: The cell identifier. If None, deletes all stream files
                for the file_id.
        """
        if cell_id is not None:
            # Delete stream file for a specific cell
            stream_file = self._build_path(file_id, cell_id) / "stream"
            if stream_file.exists():
                self.log.info(f"Deleting stream file: {stream_file}")
                stream_file.unlink()
        else:
            # Delete all stream files for this file_id
            file_path = self._build_path(file_id)
            if file_path.exists():
                for cell_dir in file_path.iterdir():
                    if cell_dir.is_dir():
                        stream_file = cell_dir / "stream"
                        if stream_file.exists():
                            self.log.info(f"Deleting stream file: {stream_file}")
                            stream_file.unlink()

    def write(self, file_id, cell_id, output, display_id=None, asdict: bool = False):
        """Write an output to disk and return a placeholder for the YDoc.

        Extends the base write() method with stream_limit optimization. For stream
        outputs when exclude_outputs=True AND stream_limit is enabled:
        - Streams below limit: written to *.output file and /stream file
        - Stream at limit: link placeholder written to *.output file, text to /stream file
        - Streams beyond limit: only written to /stream file (no *.output file)

        For non-stream outputs or when exclude_outputs=False, behaves like the base class.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell.
            output: The output dictionary to write (must have 'output_type' key).
            display_id: Optional display identifier for updatable outputs.
            asdict: If True, return placeholder as dict; if False, return as pycrdt.Map.

        Returns:
            A placeholder output containing the URL reference, either as a pycrdt.Map
            (default) or as a plain dict (if asdict=True). Returns None for stream
            outputs beyond the stream_limit.
        """
        # Check if we should apply stream_limit optimization
        exclude_outputs = self.get_exclude_outputs(file_id)

        # Handle stream outputs with stream_limit ONLY when exclude_outputs=True
        if _is_stream_output(output) and self.stream_limit is not None and exclude_outputs:
            # Determine what the count will be after this stream
            count = self._stream_count.get(cell_id, 0) + 1

            # Always append to the /stream file
            self._append_to_stream_file(file_id, cell_id, output)

            # Update the count
            self._stream_count[cell_id] = count

            if count < self.stream_limit:
                # Below limit: write stream output to *.output file normally
                placeholder = super().write(file_id, cell_id, output, display_id=display_id, asdict=asdict)
                return placeholder
            elif count == self.stream_limit:
                # At limit: write link placeholder to *.output file instead of stream
                url = _create_stream_url(file_id, cell_id)
                link_output = _create_stream_placeholder(url)
                placeholder = super().write(file_id, cell_id, link_output, asdict=asdict)
                return placeholder
            else:
                # Beyond limit: only append to /stream (already done), no *.output file
                return None
        else:
            # Non-stream output OR exclude_outputs=False: write normally without stream file
            return super().write(file_id, cell_id, output, display_id, asdict)

    def clear(self, file_id, cell_id=None):
        """Clear the output state and files for a specific cell.

        Extends base class clear() to also reset stream count tracking.

        Args:
            file_id: The unique identifier of the notebook file.
            cell_id: The unique identifier of the cell to clear (optional).
                If None, clears all stream counts.
        """
        # Clear stream_count
        if cell_id is None:
            self._stream_count = {}
        else:
            self._stream_count.pop(cell_id, None)

        # Call base class clear
        super().clear(file_id, cell_id)

    def process_loaded_notebook(self, file_id: str, file_data: dict) -> dict:
        """Process a loaded notebook and handle outputs through the outputs manager.

        This method processes a notebook that has been loaded from disk.
        In optimized mode, defaults to exclude_outputs=True but respects the
        notebook metadata setting.

        The behavior differs based on the exclude_outputs metadata:
        - If True (default): Loads outputs from OutputsManager disk storage
        - If False: Processes outputs from the notebook file (base class behavior)

        Args:
            file_id: The file identifier.
            file_data: The file data containing the notebook content from
                calling ContentsManager.get().

        Returns:
            The modified file data with processed outputs according to the
            exclude_outputs setting.
        """
        self.log.info(f"Processing loaded notebook: {file_id}")

        # Notebook content is a tree of nbformat.NotebookNode objects,
        # which are a subclass of dict.
        nb = file_data['content']
        # We need cell ids which are only in nbformat >4.5. We use this to
        # upgrade all notebooks to 4.5 or later
        nb = self._upgrade_notebook_format(nb)

        # Default to True for optimized mode
        exclude_outputs = nb.get('metadata', {}).get('exclude_outputs', True)

        # Update internal state (no transitions on load - disk is source of truth)
        old_value = self._exclude_outputs_by_file.get(file_id)
        if old_value is not None and old_value != exclude_outputs:
            self.log.info(
                f"Out-of-band change detected for {file_id}: "
                f"exclude_outputs changed from {old_value} to {exclude_outputs}"
            )
        self._exclude_outputs_by_file[file_id] = exclude_outputs

        # Process based on current exclude_outputs value
        if exclude_outputs:
            nb = self._process_loaded_excluded_outputs(file_id=file_id, nb=nb)
        else:
            # Fall back to base class behavior
            nb = self._process_loaded_included_outputs(file_id=file_id, nb=nb)

        file_data['content'] = nb
        return file_data

    def _process_loaded_included_outputs(self, file_id: str, nb: dict) -> dict:
        """Process a notebook with exclude_outputs=False (outputs in file).

        This is the base class behavior: process outputs from the notebook file,
        write them to disk, and replace with placeholders.

        Args:
            file_id: The file identifier.
            nb: The notebook dictionary.

        Returns:
            The notebook with outputs processed from the file.
        """
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

        return nb

    def _process_loaded_excluded_outputs(self, file_id: str, nb: dict) -> dict:
        """Process a notebook with exclude_outputs=True (no outputs in file).

        This method processes notebooks that have been saved with no outputs on disk.
        In this case, the OutputsManager stores the outputs by cell_id and this method
        attempts to load actual outputs from OutputsManager and creates placeholder outputs
        for each code cell. If no outputs exist on disk for a cell, the cell's
        outputs are set to an empty list.

        Special case: If the notebook file has outputs (e.g., from out-of-band edit),
        we process those outputs and save them to OutputsManager, respecting the
        exclude_outputs=True setting.

        Args:
            file_id: The file identifier.
            nb: The notebook dictionary.

        Returns:
            The notebook with placeholder outputs inserted from OutputsManager.
        """
        for cell in nb.get('cells', []):
            # Ensure all cells have IDs regardless of type
            self._ensure_cell_id(cell)

            if cell.get('cell_type') == 'code':
                cell_id = cell['id']

                # Check if the cell has outputs in the file (contradicting exclude_outputs=True)
                # This can happen from out-of-band edits
                if cell.get('outputs') and len(cell.get('outputs', [])) > 0:
                    self.log.info(
                        f"Cell {cell_id} has outputs in file despite exclude_outputs=True. "
                        f"Processing outputs from file (likely out-of-band edit)."
                    )
                    # Clear existing OutputsManager data for this cell
                    self.clear(file_id, cell_id)

                    # Process outputs from file using shared helper method
                    cell['outputs'] = self._process_outputs_from_cell(
                        file_id, cell_id, cell.get('outputs', [])
                    )
                else:
                    # Normal case: no outputs in file, load from OutputsManager
                    try:
                        # Try to get outputs from disk
                        output_strings = self.get_outputs(file_id=file_id, cell_id=cell_id)
                        outputs = []
                        for output_string in output_strings:
                            output_dict = json.loads(output_string)
                            url = _create_output_url(file_id, cell_id, len(outputs))
                            placeholder = _create_output_placeholder(
                                output_dict["output_type"],
                                url
                            )
                            outputs.append(nbformat.from_dict(placeholder))
                        cell['outputs'] = outputs
                    except FileNotFoundError:
                        # No outputs on disk for this cell, set empty outputs
                        cell['outputs'] = []
        return nb

    def process_saving_notebook(self, nb: dict, file_id: str) -> dict:
        """Process a notebook before saving to disk.

        This method is called when the yroom_file_api saves notebooks.
        In optimized mode, defaults to exclude_outputs=True but respects
        the notebook metadata setting.

        When exclude_outputs=True, all code cell outputs are cleared before saving
        (they remain in OutputsManager storage). When False, falls back to base
        class behavior (outputs included in file).

        Args:
            nb: The notebook dict.
            file_id: The file identifier.

        Returns:
            The modified notebook dict with outputs handled according to the
            exclude_outputs flag.
        """
        # Ensure metadata exists
        if 'metadata' not in nb:
            nb['metadata'] = {}

        # Default to True for optimized mode
        exclude_outputs = nb.get('metadata', {}).get('exclude_outputs', True)

        # Handle transition (if any) - this is the key integration point
        self.set_exclude_outputs(file_id, exclude_outputs)

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
            # Fall back to base class (include outputs in file)
            nb = super().process_saving_notebook(nb, file_id)

        return nb