# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.

import json

from tornado import web

from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join


class OutputsAPIHandler(APIHandler):
    """An outputs service API handler."""

    AUTH_RESOURCE = "outputs"

    @property
    def outputs(self):
        return self.settings["outputs_manager"]

    @web.authenticated
    @authorized
    async def get(self, file_id, cell_id, output_index):
        try:
            output = self.outputs.get(file_id, cell_id, output_index)
        except FileNotFoundError:
            self.set_status(404)
            self.finish()
        else:
            self.set_status(200)
            self.finish(output)



# -----------------------------------------------------------------------------
# URL to handler mappings
# -----------------------------------------------------------------------------

_file_id_regex = r"(?P<file_id>\w+-\w+-\w+-\w+-\w+)"
_cell_id_regex = r"(?P<cell_id>\w+-\w+-\w+-\w+-\w+)"
_output_index_regex = r"(?P<output_index>0|[1-9]\d*)"

def setup_handlers(web_app):
    """Setup the handlers for the outputs service."""

    handlers = [
        (r"/api/outputs/%s/%s/%s" % (_file_id_regex, _cell_id_regex, _output_index_regex), OutputsAPIHandler),
    ]

    # add the baseurl to our paths
    base_url = web_app.settings["base_url"]
    new_handlers = []
    for handler in handlers:
        pattern = url_path_join(base_url, handler[0])
        new_handler = (pattern, *list(handler[1:]))
        new_handlers.append(new_handler)

    web_app.add_handlers(".*$", new_handlers)