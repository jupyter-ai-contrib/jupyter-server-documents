"""
WIP.

This file just contains an interface to be filled out later.
"""

from tornado.websocket import WebSocketHandler

class YRoomWebsocket(WebSocketHandler):
    def open(self):
        print("WebSocket opened")

    def on_message(self, message):
        self.write_message(u"You said: " + message)

    def on_close(self):
        print("WebSocket closed")
