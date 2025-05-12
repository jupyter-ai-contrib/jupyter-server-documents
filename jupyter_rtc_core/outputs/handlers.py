# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.

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
            output = self.outputs.get(file_id, cell_id, output_index)
        except (FileNotFoundError, KeyError):
            self.set_status(404)
            self.finish({"error": "Output not found."})
        else:
            self.set_status(200)
            self.set_header("Content-Type", "application/json")
            self.write(output)


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

handlers = [
    (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/{_output_index_regex}.output", OutputsAPIHandler),
    (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/stream", StreamAPIHandler),
]

# def setup_handlers(web_app):
#     """Setup the handlers for the outputs service."""

#     handlers = [
#         (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/{_output_index_regex}.output", OutputsAPIHandler),
#         (rf"/api/outputs/{_file_id_regex}/{_cell_id_regex}/stream", StreamAPIHandler),
#     ]

#     base_url = web_app.settings["base_url"]
#     new_handlers = []
#     for handler in handlers:
#         pattern = url_path_join(base_url, handler[0])
#         new_handler = (pattern, *handler[1:])
#         new_handlers.append(new_handler)

#     # Add the handler for all hosts
#     web_app.add_handlers(".*$", new_handlers)
