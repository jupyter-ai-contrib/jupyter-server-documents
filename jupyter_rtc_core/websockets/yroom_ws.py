from __future__ import annotations
from tornado.httpclient import HTTPError
from tornado.websocket import WebSocketHandler
from typing import TYPE_CHECKING
import asyncio
from ..rooms import YRoomManager
import logging

if TYPE_CHECKING:
    from jupyter_server_fileid.manager import BaseFileIdManager
    from jupyter_server.services.contents.manager import AsyncContentsManager, ContentsManager
    from ..rooms import YRoom

class YRoomWebsocket(WebSocketHandler):
    yroom: YRoom
    room_id: str
    client_id: str

    @property
    def yroom_manager(self) -> YRoomManager:
        if "yroom_manager" not in self.settings:
            self.settings["yroom_manager"] = YRoomManager(
                fileid_manager=self.fileid_manager,
                contents_manager=self.contents_manager,
                loop=asyncio.get_event_loop_policy().get_event_loop(),
                # TODO: change this. we should pass `self.log` from our
                # `ExtensionApp` to log messages w/ "RtcCoreExtension" prefix
                log=logging.Logger("TEMP")

            )
        return self.settings["yroom_manager"]

    @property
    def fileid_manager(self) -> BaseFileIdManager:
        return self.settings["file_id_manager"]
    

    @property
    def contents_manager(self) -> AsyncContentsManager | ContentsManager:
        return self.settings["contents_manager"]


    def prepare(self):
        # Bind `room_id` attribute
        request_path: str = self.request.path
        self.room_id = request_path.strip("/").split("/")[-1]

        # TODO: remove this once globalawareness is implemented
        if self.room_id == "JupyterLab:globalAwareness":
            raise HTTPError(404)

        # Verify the file ID contained in the room ID points to a valid file.
        fileid = self.room_id.split(":")[-1]
        path = self.fileid_manager.get_path(fileid)
        if not path:
            raise HTTPError(404, f"No file with ID '{fileid}'.")
    

    def open(self, *_, **__):
        # Create the YRoom
        yroom = self.yroom_manager.get_room(self.room_id)
        if not yroom:
            raise HTTPError(500, f"Unable to initialize YRoom '{self.room_id}'.")
        self.yroom = yroom

        # Add self as a client to the YRoom
        self.client_id = self.yroom.clients.add(self)


    def on_message(self, message: bytes):
        # Route all messages to the YRoom for processing
        print(message)
        self.yroom.add_message(self.client_id, message)


    def on_close(self):
        self.yroom.clients.remove(self.client_id)
