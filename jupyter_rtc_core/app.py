from jupyter_server.extension.application import ExtensionApp

from .handlers import RouteHandler
from .websockets import YAwarenessWebsocket, YDocWebsocket

class RtcExtensionApp(ExtensionApp):
    name = "jupyter_rtc_core"
    handlers = [
        # dummy handler that verifies the server extension is installed;
        # this can be deleted prior to initial release.
        (r"jupyter-rtc-core/get-example/?", RouteHandler),
        # global awareness websocket
        (r"api/collaboration/room/JupyterLab:globalAwareness/?", YAwarenessWebsocket),
        # ydoc websocket
        (r"api/collaboration/room/(.*)", YDocWebsocket)
    ]
