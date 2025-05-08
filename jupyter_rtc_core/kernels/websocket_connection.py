import asyncio
import json

from traitlets import Bool
from traitlets import default
from traitlets import Instance

try:
    from jupyter_client.jsonutil import json_default
except ImportError:
    from jupyter_client.jsonutil import date_default as json_default

from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
)
from .states import LIFECYCLE_DEAD_STATES
from jupyter_server.services.kernels.connection.base import deserialize_msg_from_ws_v1, serialize_msg_to_ws_v1
from jupyter_client.session import Session

class NextGenKernelWebsocketConnection(BaseKernelWebsocketConnection):
    """A websocket client that connects to a kernel manager.
    
    NOTE: This connection only works with the (newer) v1 websocket protocol.
    https://jupyter-server.readthedocs.io/en/latest/developers/websocket-protocols.html
    """

    kernel_ws_protocol = "v1.kernel.websocket.jupyter.org"

    async def connect(self):
        """A synchronous method for connecting to the kernel via a kernel session.
        This connection might take a few minutes, so we turn this into an
        asyncio task happening in parallel.
        """
        self.kernel_manager.main_client.add_listener(self.handle_outgoing_message)
        self.kernel_manager.broadcast_state()
        self.log.info("Kernel websocket is now listening to kernel.")

    def disconnect(self):
        self.kernel_manager.main_client.remove_listener(self.handle_outgoing_message)

    def handle_incoming_message(self, ws_message):
        """Handle the incoming WS message"""
        channel_name, msg_list = deserialize_msg_from_ws_v1(ws_message)
        if self.kernel_manager.main_client:
            self.kernel_manager.main_client.send_message(channel_name, msg_list)

    def handle_outgoing_message(self, channel_name, msg):
        """Handle the ZMQ message."""
        try:
            # Taken from https://github.com/jupyter-server/jupyter_server/blob/e12feb99bb6171f2780610bbac6ba0f80aaec544/jupyter_server/services/kernels/connection/channels.py#L490
            # Websocket protocol is complicated.
            _, fed_msg_list = self.kernel_manager.main_client.session.feed_identities(msg)
            parts = fed_msg_list[1:]
            msg = serialize_msg_to_ws_v1(parts, channel_name)
            self.websocket_handler.write_message(msg, binary=True)
        except WebSocketClosedError:
            self.log.warning("A ZMQ message arrived on a closed websocket channel.")
        except Exception as err:
            self.log.error(err)