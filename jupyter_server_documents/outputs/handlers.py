import json

from tornado import web

from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join


class OutputsAPIHandler(APIHandler):
    """An outputs service API handler."""

    auth_resource = "outputs"

    @property
    def outputs(self):
        return self.settings["outputs_manager"]

    @web.authenticated
    @authorized
    async def get(self, file_id=None, cell_id=None, output_index=None):
        try:
            if output_index:
                output = self.outputs.get_output(file_id, cell_id, output_index)
                content_type = "application/json"
            else:
                outputs = self.outputs.get_outputs(file_id, cell_id)
                output = "\n".join(outputs)
                content_type = "application/x-ndjson"
        except (FileNotFoundError, KeyError):
            self.set_status(404)
            self.finish({"error": "Output not found."})
        else:
            self.set_status(200)
            self.write(output)
            self.finish(set_content_type=content_type)


class StreamAPIHandler(APIHandler):
    """An outputs service API handler."""

    auth_resource = "outputs"

    @property
    def outputs(self):
        return self.settings["outputs_manager"]

    @web.authenticated
    @authorized
    async def get(self, file_id=None, cell_id=None):
        try:
            output = self.outputs.get_stream(file_id, cell_id)
        except (FileNotFoundError, KeyError):
            self.set_status(404)
            self.finish({"error": "Stream output not found."})
        else:
            # self.set_header("Content-Type", "text/plain; charset=uft-8")
            self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.set_header("Pragma", "no-cache")
            self.set_header("Expires", "0")
            self.set_status(200)
            self.write(output)
            self.finish(set_content_type="text/plain; charset=utf-8")


# -----------------------------------------------------------------------------
# URL to handler mappings
# -----------------------------------------------------------------------------

# Strict UUID regex (matches standard 8-4-4-4-12 UUIDs)
_uuid_regex = r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"

_file_id_regex = rf"(?P<file_id>{_uuid_regex})"
_cell_id_regex = rf"(?P<cell_id>{_uuid_regex})"

# non-negative integers
_output_index_regex = r"(?P<output_index>0|[1-9]\d*)"

outputs_handlers = [
    (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}(?:/{_output_index_regex}.output)?", OutputsAPIHandler),
    (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/stream", StreamAPIHandler),
]

