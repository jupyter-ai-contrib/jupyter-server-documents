"""
WIP.

This file just contains an interface to be filled out later.
"""

from tornado.httpclient import HTTPError
from tornado.websocket import WebSocketHandler
from ..rooms import YRoom, YRoomManager

class YRoomWebsocket(WebSocketHandler):
    yroom: YRoom
    client_id: str

    @property
    def yroom_manager(self) -> YRoomManager:
        return self.settings["yroom_manager"]

    def open(self):
        request_path: str = self.request.path
        room_id = request_path.strip("/").split("/")[-1]
        yroom = self.yroom_manager.get_room(room_id)

        if not yroom:
            raise HTTPError(404, f"No room with ID '{room_id}'.")

        self.yroom = yroom
        self.client_id = self.yroom.clients.add(self)

    def on_message(self, message: bytes):
        self.yroom.add_message(message)

    def on_close(self):
        self.yroom.clients.remove(self.client_id)
