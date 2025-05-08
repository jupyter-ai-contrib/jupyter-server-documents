import json
import os
from pathlib import Path


from traitlets.config.configurable import LoggingConfigurable
from traitlets import (
    Any,
    Bool,
    Dict,
    Instance,
    List,
    TraitError,
    Type,
    Unicode,
    default,
    validate,
)

from jupyter_core.paths import get_runtime_dir

class OutputsManager(LoggingConfigurable):

    outputs_path = Unicode(help="The local runtime dir")

    @default("outputs_path")
    def _default_outputs_path(self):
        return os.path.join(get_runtime_dir(), "outputs")
    
    def _ensure_path(self, file_id, cell_id):
        nested_dir = self.outputs_path / file_id / cell_id
        nested_dir.mkdir(parents=True, exist_ok=True)

    def _build_path(self, file_id, cell_id, cell_index):
        return os.path.join(self.outputs_path, file_id, cell_id, f"{cell_index}.output")

    def get(self, file_id, cell_id, cell_index):
        path = self._build_path(file_id, cell_id, cell_index)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"The output file doesn't exist: {path}")
        with open(path, "r", encoding="utf-8") as f:
            output = json.load(f)
        return output

    def write(self, file_id, cell_id, cell_index, output):
        self._ensure_path(file_id, cell_id)
        path = self.build_path(file_id, cell_id, cell_index)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False)
