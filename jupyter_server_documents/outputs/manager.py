import json
import os
from pathlib import Path, PurePath
import shutil

from pycrdt import Map

from traitlets.config import LoggingConfigurable
from traitlets import Dict, Instance, Int, default

from jupyter_core.paths import jupyter_runtime_dir


class OutputsManager(LoggingConfigurable):
    _last_output_index = Dict(default_value={})
    _stream_count = Dict(default_value={})

    outputs_path = Instance(PurePath, help="The local runtime dir")
    stream_limit = Int(default_value=10, config=True, allow_none=True)

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

    def _create_outputs_placeholder(self, file_id: str, cell_id: str):
        url = f"/api/outputs/{file_id}/{cell_id}/stream"
        return {
            "output_type": "display_data",
            "data": {
                "text/html": f'<a href="{url}">Click this link to see the full stream output</a>'
            },
        }

    def get_output(self, file_id, cell_id, output_index):
        """Get an output by file_id, cell_id, and output_index."""
        path = self._build_path(file_id, cell_id, output_index)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = json.loads(f.read())
        return output

    def get_outputs(self, file_id, cell_id):
        """Get all outputs by file_id, cell_id."""
        path = self._build_path(file_id, cell_id)
        if not os.path.isdir(path):
            raise FileNotFoundError(f"The output dir doesn't exist: {path}")

        outputs = []

        output_files = [(f, int(f.stem)) for f in path.glob("*.output")]
        output_files.sort(key=lambda x: x[1])
        output_files = output_files[: self.stream_limit]
        has_more_files = len(output_files) >= self.stream_limit

        outputs = []
        for file_path, _ in output_files:
            with open(file_path, "r", encoding="utf-8") as f:
                output = f.read()
                outputs.append(output)

        if has_more_files:
            placeholder = self._create_outputs_placeholder(file_id, cell_id)
            outputs.append(json.dumps(placeholder))

        return outputs

    def get_stream(self, file_id, cell_id):
        "Get the stream output for a cell by file_id and cell_id."
        path = self._build_path(file_id, cell_id) / "stream"
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = f.read()
        return output

    def write(self, file_id, cell_id, output):
        """Write a new output for file_id and cell_id.

        Returns a placeholder output (pycrdt.Map) or None if no placeholder
        output should be written to the ydoc.
        """
        placeholder = self.write_output(file_id, cell_id, output)
        if output["output_type"] == "stream" and self.stream_limit is not None:
            placeholder = self.write_stream(file_id, cell_id, output, placeholder)
        return placeholder

    def write_output(self, file_id, cell_id, output):
        self._ensure_path(file_id, cell_id)
        last_index = self._last_output_index.get(cell_id, -1)
        index = last_index + 1
        self._last_output_index[cell_id] = index
        path = self._build_path(file_id, cell_id, index)
        data = json.dumps(output, ensure_ascii=False)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        url = f"/api/outputs/{file_id}/{cell_id}/{index}.output"
        self.log.info(f"Wrote output: {url}")
        return create_placeholder_output(output["output_type"], url)

    def write_stream(self, file_id, cell_id, output, placeholder) -> Map:
        # How many stream outputs have been written for this cell previously
        count = self._stream_count.get(cell_id, 0)

        # Go ahead and write the incoming stream
        self._ensure_path(file_id, cell_id)
        path = self._build_path(file_id, cell_id) / "stream"
        text = output["text"]
        mode = "a" if os.path.isfile(path) else "w"
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
        url = f"/api/outputs/{file_id}/{cell_id}/stream"
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
            placeholder = Map(self._create_outputs_placeholder(file_id, cell_id))
        elif count > self.stream_limit:
            # Return None to indicate that no placeholder should be written to the ydoc
            placeholder = None
        return placeholder

    def clear(self, file_id, cell_id=None):
        """Clear the state of the manager."""
        if cell_id is None:
            self._stream_count = {}
            path = self._build_path(file_id)
        else:
            try:
                del self._stream_count[cell_id]
            except KeyError:
                pass
            path = self._build_path(file_id, cell_id)
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            pass


def create_placeholder_output(output_type: str, url: str):
    metadata = dict(url=url)
    if output_type == "stream":
        output = Map({"output_type": "stream", "text": "", "metadata": metadata})
    elif output_type == "display_data":
        output = Map({"output_type": "display_data", "metadata": metadata})
    elif output_type == "execute_result":
        output = Map({"output_type": "execute_result", "metadata": metadata})
    elif output_type == "error":
        output = Map({"output_type": "error", "metadata": metadata})
    return output
