from tornado.websocket import WebSocketClosedError
from jupyter_server.services.kernels.connection.base import (
    BaseKernelWebsocketConnection,
)
from .states import LifecycleStates
from jupyter_server.services.kernels.connection.base import deserialize_msg_from_ws_v1, serialize_msg_to_ws_v1

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
        await self.kernel_manager.broadcast_state()
        self.log.info("Kernel websocket is now listening to kernel.")

    def disconnect(self):
        self.kernel_manager.main_client.remove_listener(self.handle_outgoing_message)

    def handle_incoming_message(self, incoming_msg):
        """Handle the incoming WS message"""
        channel_name, msg_list = deserialize_msg_from_ws_v1(incoming_msg)
        if self.kernel_manager.main_client:
            self.kernel_manager.main_client.handle_incoming_message(channel_name, msg_list)

    def handle_outgoing_message(self, channel_name, msg):
        """Handle the ZMQ message."""
        try:
            # Remove signature from message to be compatible with Jupyter Server.
            # See here: https://github.com/jupyter-server/jupyter_server/blob/4ee6e1ddc058f87b2c5699cd6b9caf780a013044/jupyter_server/services/kernels/connection/channels.py#L504
            msg = msg[1:]
            msg = serialize_msg_to_ws_v1(msg, channel_name)
            self.websocket_handler.write_message(msg, binary=True)
        except WebSocketClosedError:
            self.log.warning("A ZMQ message arrived on a closed websocket channel.")
        except Exception as err:
            self.log.error(err)