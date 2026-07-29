from __future__ import annotations
from tornado.httpclient import HTTPError
from tornado.websocket import WebSocketHandler
from tornado import web
from typing import TYPE_CHECKING
import asyncio
from ..rooms import YRoomManager
import logging
from jupyter_server.base.handlers import JupyterHandler

if TYPE_CHECKING:
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from ..rooms import YRoom

class YRoomWebsocket(WebSocketHandler, JupyterHandler):
    yroom: YRoom
    room_id: str
    client_id: str | None
    # TODO: change this. we should pass `self.log` from our
    # `ExtensionApp` to log messages w/ "ServerDocsApp" prefix
    log = logging.Logger("TEMP")

    @property
    def ping_interval(self) -> float:
        return self.settings.get("ws_ping_interval", 25000) / 1000

    @property
    def ping_timeout(self) -> float:
        return self.settings.get("ws_ping_timeout", 25000) / 1000

    @property
    def yroom_manager(self) -> YRoomManager:
        return self.settings["yroom_manager"]


    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self.settings["file_id_manager"]
    

    @property
    def contents_manager(self) -> AsyncContentsManager | ContentsManager:
        return self.settings["contents_manager"]


    def check_origin(self, origin):
        # Mirroring jupyter_server_ydoc.YDocWebSocketHandler.
        return True

    async def get(self, *args, **kwargs):
        if self.current_user is None:
            self.log.warning("Couldn't authenticate WebSocket connection")
            raise web.HTTPError(403)
        return await super().get(*args, **kwargs)

    async def prepare(self):
        await super().prepare()

        # Bind `room_id` attribute
        request_path: str = self.request.path
        self.room_id = request_path.strip("/").split("/")[-1]

        # Verify the file ID contained in the room ID points to a valid file.
        if self.room_id != "JupyterLab:globalAwareness":
            fileid = self.room_id.split(":")[-1]
            try:
                path = self.fileid_manager.get_path(fileid)
            except Exception as e:
                self.log.error("WS prepare: fileid_manager.get_path failed for fileid=%r: %s", fileid, e)
                raise HTTPError(500, f"file_id_manager error: {e}")
            self.log.debug("WS prepare: room_id=%r fileid=%r path=%r", self.room_id, fileid, path)
            if not path:
                raise HTTPError(404, f"No file with ID '{fileid}'.")
    

    def open(self, *_, **__):
        # Create the YRoom
        yroom = self.yroom_manager.get_room(self.room_id)
        if not yroom:
            raise HTTPError(500, f"Unable to initialize YRoom '{self.room_id}'.")
        self.yroom = yroom

        # Add self as a client to the YRoom.
        # If `client_id is None`, then the YRoom is being stopped, and this WS
        # should be closed immediately w/ close code 1001.
        self.client_id = self.yroom.clients.add(self)
        if not self.client_id:
            self.close(code=1001)
            return


    def on_message(self, message: bytes):
        if not self.client_id:
            self.close(code=1001)
            return

        # Route all messages to the YRoom for processing
        self.yroom.add_message(self.client_id, message)


    def on_close(self):
        if self.client_id:
            self.log.info(f"Closed Websocket to client '{self.client_id}'.")
            self.yroom.clients.remove(self.client_id)
