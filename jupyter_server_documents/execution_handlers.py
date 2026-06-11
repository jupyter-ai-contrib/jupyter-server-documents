from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler
from tornado import web
from tornado.escape import json_encode

from .rooms.ynotebook_room import YNotebookRoom, SourceMismatchError, PredecessorTimeoutError


AUTH_RESOURCE = "executions"


class ExecutionsAPIHandler(APIHandler):
    auth_resource = AUTH_RESOURCE


class KernelExecuteHandler(ExecutionsAPIHandler):
    """
    POST /api/kernels/{kernel_id}/execute

    Jupyverse-compatible server-side execution endpoint.

    Request body:
      cell_id              string   required — Yjs cell ID
      document_id          string   required (or path)
      path                 string   required (or document_id)
      source_hash          string   optional — SHA-256 hex of source at
                                    request time; server returns 409 if
                                    the YDoc source has diverged
      request_id           string   optional — UUID for this request so
                                    the next call can chain off it
      previous_request_id  string   optional — UUID of the preceding
                                    request; server waits until that
                                    request has been enqueued before
                                    enqueuing this one (FIFO guarantee)

    Responses:
      200 null   — accepted (fire-and-forget)
      400        — bad request
      408        — predecessor timeout
      409        — source mismatch {"error": "source_mismatch", "cell_id": "..."}
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

        if path:
            file_id = self.settings["file_id_manager"].index(path)
            document_id = f"json:notebook:{file_id}"

        yroom = self.settings["yroom_manager"].get_room(document_id)
        if yroom is None:
            raise web.HTTPError(400, f"No YRoom available for document: {document_id!r}")
        if not isinstance(yroom, YNotebookRoom):
            raise web.HTTPError(400, f"Room {document_id!r} is not a notebook room")

        source_hash = body.get("source_hash")
        client_id = body.get("client_id")   # Yjs awareness clientID — used for attribution
        request_id = body.get("request_id")
        previous_request_id = body.get("previous_request_id")
        # NOTE: ordering is per-client (docKey = document:client_id on the frontend)
        # so two users' chains don't block each other.  A remaining gap is "Run All":
        # today it sends N chained single-cell requests, so another user's single
        # cell can slip between them.  A future `cells: []` batch payload would
        # make "Run All" truly atomic.  See davidbrochart's comment in PR #248.

        try:
            await yroom.execute_cell(
                cell_id,
                clear_outputs=True,
                source_hash=source_hash,
                request_id=request_id,
                previous_request_id=previous_request_id,
            )
        except SourceMismatchError as e:
            self.set_status(409)
            self.finish(json_encode({"error": "source_mismatch", "cell_id": e.cell_id}))
            return
        except PredecessorTimeoutError:
            raise web.HTTPError(408, "Timed out waiting for previous_request_id to be enqueued")
        except (LookupError, ValueError, RuntimeError) as e:
            raise web.HTTPError(400, str(e))

        self.finish("null")


executions_handlers = [
    (r"api/kernels/([\w-]+)/execute", KernelExecuteHandler),
]
