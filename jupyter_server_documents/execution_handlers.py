from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler
from tornado import web


AUTH_RESOURCE = "executions"


class ExecutionsAPIHandler(APIHandler):
    auth_resource = AUTH_RESOURCE


class KernelExecuteHandler(ExecutionsAPIHandler):
    """
    POST /api/kernels/{kernel_id}/execute

    Jupyverse-compatible server-side execution endpoint.
    Accepts { cell_id, document_id } or { cell_id, path } and delegates
    directly to the appropriate YRoom.

    Returns null (fire-and-forget) to match the jupyverse response shape so
    the existing NotebookCellServerExecutor in jupyter-collaboration works
    without modification.
    """

    @web.authenticated
    @authorized
    async def post(self, kernel_id: str):
        body = self.get_json_body() or {}
        cell_id = body.get("cell_id")
        document_id = body.get("document_id")
        path = body.get("path")

        if not cell_id:
            raise web.HTTPError(400, "cell_id is required")
        if not document_id and not path:
            raise web.HTTPError(400, "document_id or path is required")

        timeout = body.get("timeout", None)

        if path:
            file_id = self.settings["file_id_manager"].index(path)
            document_id = f"json:notebook:{file_id}"

        yroom = self.settings["yroom_manager"].get_room(document_id)
        if yroom is None:
            raise web.HTTPError(400, f"No YRoom available for document: {document_id!r}")

        try:
            await yroom.execute_cell(cell_id, clear_outputs=True, timeout=timeout)
        except (LookupError, ValueError, RuntimeError) as e:
            raise web.HTTPError(400, str(e))

        self.finish("null")


executions_handlers = [
    (r"api/kernels/([\w-]+)/execute", KernelExecuteHandler),
]
