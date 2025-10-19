from tornado import web

from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler


class OutputsAPIHandler(APIHandler):
    """An outputs service API handler."""

    auth_resource = "outputs"

    @property
    def outputs(self):
        return self.settings["outputs_manager"]

    @web.authenticated
    @authorized
    async def get(self, file_id, cell_id=None, output_index=None):
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

    @web.authenticated
    @authorized
    async def delete(self, file_id, cell_id=None, output_index=None):
        # output_index is accepted but ignored as we clear all cell outputs regardless
        try:
            self.outputs.clear(file_id, cell_id)
        except (FileNotFoundError):
            self.set_status(404)
            self.finish({"error": "Output not found."})
        else:
            self.set_status(200)
            self.finish()


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

_file_id_regex = r"(?P<file_id>[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"
# In nbformat, cell_ids follow this format, compatible with uuid4
_cell_id_regex = r"(?P<cell_id>[a-zA-Z0-9_-]+)"

# non-negative integers
_output_index_regex = r"(?P<output_index>0|[1-9]\d*)"

outputs_handlers = [
    (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}(?:/{_output_index_regex}.output)?", OutputsAPIHandler),
    # We have disabled this for now as OptimizedOutputsManager is experimental.
    # Uncomment this to use OptimizedOutputsManager.
    # (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/stream", StreamAPIHandler),
]
