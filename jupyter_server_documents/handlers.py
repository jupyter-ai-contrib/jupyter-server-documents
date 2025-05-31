import json

from jupyter_server.base.handlers import APIHandler
import tornado

from jupyter_server.auth.decorator import authorized
from tornado import web
from tornado.escape import json_encode

from jupyter_server_fileid.manager import BaseFileIdManager

# TODO: This handler belongs in Jupyter Server FileID. 
# Putting it here for now so we don't have to wait for upstream releases.
class FileIDIndexHandler(APIHandler): 
    auth_resource = "contents"

    @property
    def file_id_manager(self) -> BaseFileIdManager:
        return self.settings.get("file_id_manager")
    
    @web.authenticated
    @authorized
    def post(self):
        try:
            path = self.get_argument("path")
            id = self.file_id_manager.index(path)
            self.write(json_encode({"id": id, "path": path}))
        except web.MissingArgumentError:
            raise web.HTTPError(
                400, log_message="'path' parameter was not provided in the request."
            )


class RouteHandler(APIHandler):
    # The following decorator should be present on all verb methods (head, get, post,
    # patch, put, delete, options) to ensure only authorized user can request the
    # Jupyter server
    @tornado.web.authenticated
    def get(self):
        self.finish(json.dumps({
            "data": "This is /jupyter-server-documents/get-example endpoint!"
        }))