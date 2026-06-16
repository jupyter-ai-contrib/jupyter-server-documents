"""Test-only Jupyter Server extension for E2E tests.

Exposes two endpoints used to deterministically reproduce the "divergent CRDT
history" condition (server recreates its YRoom from disk under a fresh
clientID while a browser keeps its existing Y.Doc):

- GET  /jsd-test/room-info?path=<path>
    Returns one entry per open document room for the file, with its server-side
    YDoc clientID and current text source. Used to (a) wait until the client's
    edit has synced to the server and (b) prove the clientID actually changed
    after recreation (i.e. divergence really occurred, not a no-op reconnect).

- POST /jsd-test/recreate-room?path=<path>
    Frees the room(s) for the file: this saves the current content to disk and
    disconnects clients (close code 1001). The next client message rebuilds the
    room fresh from disk under a new clientID -- exactly the divergence
    condition. Returns the old clientID(s) that were freed.

!! Test-only. Never load this in production: it lets any authenticated client
   destroy live document rooms.
"""
import json

import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join


def _rooms_for_path(settings, path):
    """Return the open document rooms backing the given file path.

    This is strictly read-only: it inspects the manager's existing rooms via
    ``list_document_rooms()`` and resolves the file id via ``get_id()`` (which
    returns ``None`` for an unindexed path). It never calls ``get_room()``, so
    it cannot create a room as a side effect.
    """
    fid_manager = settings["file_id_manager"]
    fid = fid_manager.get_id(path)
    if fid is None:
        return []
    manager = settings["yroom_manager"]
    return [
        room
        for room in manager.list_document_rooms()
        if room.room_id.endswith(f":{fid}")
    ]


class _RoomInfoHandler(APIHandler):
    @tornado.web.authenticated
    async def get(self):
        path = self.get_argument("path")
        # Assume at most one room per path. (A path can in principle back rooms
        # of different formats, but the tests only ever open one.) Return the
        # first existing room, or 404 if none exists. Never creates a room.
        rooms = _rooms_for_path(self.settings, path)
        if not rooms:
            raise tornado.web.HTTPError(404, f"No open room for path '{path}'.")
        room = rooms[0]
        source = None
        jupyter_ydoc = getattr(room, "_jupyter_ydoc", None)
        if jupyter_ydoc is not None:
            try:
                source = jupyter_ydoc.source
            except Exception:  # noqa: BLE001 - best-effort introspection
                source = None
        # clientID is returned as a string to avoid JS Number precision loss
        # for large (>2^53) client IDs.
        self.finish(
            json.dumps(
                {
                    "room_id": room.room_id,
                    "client_id": str(room._ydoc.client_id),
                    "source": source,
                }
            )
        )


class _RecreateRoomHandler(APIHandler):
    @tornado.web.authenticated
    async def post(self):
        path = self.get_argument("path")
        manager = self.settings["yroom_manager"]
        freed = []
        for room in _rooms_for_path(self.settings, path):
            old_client_id = str(room._ydoc.client_id)
            # delete_room() stops the room (close code 1001) and awaits the
            # final save before removing it, so the content is persisted to disk
            # and reloaded fresh on the client's next connection.
            await manager.delete_room(room.room_id)
            freed.append({"room_id": room.room_id, "old_client_id": old_client_id})
        self.finish(json.dumps({"freed": freed}))


def _jupyter_server_extension_points():
    return [{"module": "jsd_test_ext"}]


def _load_jupyter_server_extension(server_app):
    web_app = server_app.web_app
    base_url = web_app.settings["base_url"]
    web_app.add_handlers(
        ".*$",
        [
            (url_path_join(base_url, "jsd-test", "room-info"), _RoomInfoHandler),
            (
                url_path_join(base_url, "jsd-test", "recreate-room"),
                _RecreateRoomHandler,
            ),
        ],
    )
    server_app.log.info("jsd_test_ext (E2E test extension) loaded")
