from jupyter_server.auth.decorator import authorized
from jupyter_server.base.handlers import APIHandler
from tornado import web
from tornado.escape import json_encode

from .rooms.ynotebook_room import (
    YNotebookRoom,
    SourceMismatchError,
    SequenceOutOfRangeError,
    SessionResetError,
)


AUTH_RESOURCE = "executions"


class ExecutionsAPIHandler(APIHandler):
    auth_resource = AUTH_RESOURCE


class KernelExecuteHandler(ExecutionsAPIHandler):
    """
    POST /api/kernels/{kernel_id}/execute

    Server-side cell execution endpoint.

    ## Request body

    ```json
    {
      "document_id": "string",   // required — room name
      "cells": [                 // required — cells to execute atomically and in order
        {
          "cell_id":     "string",  // required — cell ID
          "source_hash": "string"   // required — MurmurHash2 (seed=0) of cell source, as decimal string
        }
      ],

      // Execution ordering (optional)
      "client_id": "string",  // identifies the browser tab; scopes `sequence`
      "sequence":  0,         // monotonic counter per client_id, starts at 0
      "request_id":"string"   // opaque UUID for logging / tracing
    }
    ```

    All cells in ``cells`` are verified (hash check) and enqueued atomically
    before the response is sent, so no other request can interleave with the
    batch.  This makes "Run All" and "Restart and Run All" safe regardless of
    network timing.

    The ``source_hash`` per cell is a MurmurHash2 (seed=0) decimal string of
    the cell source at the time the user pressed Run.  The server returns 409
    if the YDoc source has diverged (another user edited the cell after the
    request was sent).

    ## Responses
    - ``200 null``  — accepted (fire-and-forget)
    - ``400``       — bad request
    - ``409 {"error": "source_mismatch", "cell_id": "..."}`` — source diverged
    - ``409``       — session reset (client should clear its counter and retry with sequence=0)
    """

    @web.authenticated
    @authorized
    async def post(self, kernel_id: str):
        body = self.get_json_body() or {}
        document_id = body.get("document_id")

        if not document_id:
            raise web.HTTPError(400, "document_id is required")

        cells_payload = body.get("cells")
        if not cells_payload or not isinstance(cells_payload, list):
            raise web.HTTPError(400, "cells must be a non-empty list of {cell_id, source_hash}")

        client_id = body.get("client_id")
        request_id = body.get("request_id")
        sequence = body.get("sequence")

        if sequence is not None:
            if not isinstance(sequence, int) or sequence < 0:
                raise web.HTTPError(400, "sequence must be a non-negative integer")
            if not client_id:
                raise web.HTTPError(400, "client_id is required when sequence is present")

        yroom = self.settings["yroom_manager"].get_room(document_id)
        if yroom is None:
            raise web.HTTPError(400, f"No YRoom available for document: {document_id!r}")
        if not isinstance(yroom, YNotebookRoom):
            raise web.HTTPError(400, f"Room {document_id!r} is not a notebook room")

        try:
            await yroom.execute_cells(
                cells_payload,
                clear_outputs=True,
                request_id=request_id,
                client_id=client_id,
                sequence=sequence,
            )
        except SourceMismatchError as e:
            self.set_status(409)
            self.finish(json_encode({"error": "source_mismatch", "cell_id": e.cell_id}))
            return
        except SessionResetError:
            self.set_status(409)
            self.finish(json_encode({"error": "session_reset"}))
            return
        except SequenceOutOfRangeError as e:
            raise web.HTTPError(400, str(e))
        except (LookupError, ValueError, RuntimeError) as e:
            raise web.HTTPError(400, str(e))

        self.finish("null")


executions_handlers = [
    (r"api/kernels/([\w-]+)/execute", KernelExecuteHandler),
]
