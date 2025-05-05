from jupyter_server.extension.application import ExtensionApp

from .handlers import RouteHandler

class RtcExtensionApp(ExtensionApp):
    name = "jupyter_rtc_core"
    handlers = [
        (r"jupyter-rtc-core/get-example/?", RouteHandler)
    ]
