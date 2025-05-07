import asyncio
import json
import typing as t

from pycrdt import Map

from traitlets import Dict

from jupyter_server.services.kernels.connection.channels import ZMQChannelsWebsocketConnection
from jupyter_server.services.kernels.connection.base import (
    deserialize_binary_message,
    deserialize_msg_from_ws_v1
)

class RTCWebsocketConnection(ZMQChannelsWebsocketConnection):

    _cell_ids = Dict(default_value={})

    def get_part(self, field, value, msg_list):
        """Get a part of a message."""
        if value is None:
            field2idx = {
                "header": 0,
                "parent_header": 1,
                "metadata": 2,
                "content": 3,
            }
            value = self.session.unpack(msg_list[field2idx[field]])
        return value

    def save_cell_id(self, channel, msg, msg_list):
        """Save the cell_id <-> msg_id map.
        
        This method is used to create a map between cell_id and msg_id.
        Incoming execute_request messages have both a cell_id and msg_id.
        When output messages are send back to the frontend, this map is used
        to find the cell_id for a given parent msg_id.
        """
        if channel != "shell":
            return
        header = self.get_part("header", msg.get("header"), msg_list)
        if header is None:
            return
        if header["msg_type"] != "execute_request":
            return
        msg_id = header["msg_id"]
        md = self.get_part("metadata", msg.get("metadata"), msg_list)
        if md is None:
            return
        cell_id = md.get('cellId')
        self.log.info(f"Saving (msg_id, cell_id): ({msg_id} {cell_id})")
        self._cell_ids[msg_id] = cell_id
    
    def get_cell_id(self, msg_id):
        """Retrieve a cell_id from a parent msg_id."""
        return self._cell_ids[msg_id]

    def disconnect(self):
        """Handle a disconnect."""
        self.log.debug("Websocket closed %s", self.session_key)
        # unregister myself as an open session (only if it's really me)
        if self._open_sessions.get(self.session_key) is self.websocket_handler:
            self._open_sessions.pop(self.session_key)

        if self.kernel_id in self.multi_kernel_manager:
            self.multi_kernel_manager.notify_disconnect(self.kernel_id)
            self.multi_kernel_manager.remove_restart_callback(
                self.kernel_id,
                self.on_kernel_restarted,
            )
            self.multi_kernel_manager.remove_restart_callback(
                self.kernel_id,
                self.on_restart_failed,
                "dead",
            )

            # start buffering instead of closing if this was the last connection
            if (
                self.kernel_id in self.multi_kernel_manager._kernel_connections
                and self.multi_kernel_manager._kernel_connections[self.kernel_id] == 0
            ):
                # We need to comment this out because the start_buffering method
                # closes the ZMQ streams for the different channels. But we need
                # to keep those alive while the kernel is running. Need to think
                # carefully about how this works.
                # self.multi_kernel_manager.start_buffering(
                #     self.kernel_id, self.session_key, self.channels
                # )
                ZMQChannelsWebsocketConnection._open_sockets.remove(self)
                self._close_future.set_result(None)
                return

        # This method can be called twice, once by self.kernel_died and once
        # from the WebSocket close event. If the WebSocket connection is
        # closed before the ZMQ streams are setup, they could be None.
        for stream in self.channels.values():
            if stream is not None and not stream.closed():
                stream.on_recv(None)
                stream.close()

        self.channels = {}
        try:
            ZMQChannelsWebsocketConnection._open_sockets.remove(self)
            self._close_future.set_result(None)
        except Exception:
            pass

    def handle_incoming_message(self, incoming_msg: str) -> None:
        """Handle incoming messages from Websocket to ZMQ Sockets."""
        ws_msg = incoming_msg
        if not self.channels:
            # already closed, ignore the message
            self.log.debug("Received message on closed websocket %r", ws_msg)
            return

        if self.subprotocol == "v1.kernel.websocket.jupyter.org":
            channel, msg_list = deserialize_msg_from_ws_v1(ws_msg)
            msg = {
                "header": None,
            }
        else:
            if isinstance(ws_msg, bytes):  # type:ignore[unreachable]
                msg = deserialize_binary_message(ws_msg)  # type:ignore[unreachable]
            else:
                msg = json.loads(ws_msg)
            msg_list = []
            channel = msg.pop("channel", None)

        if channel is None:
            self.log.warning("No channel specified, assuming shell: %s", msg)
            channel = "shell"
        if channel not in self.channels:
            self.log.warning("No such channel: %r", channel)
            return
        am = self.multi_kernel_manager.allowed_message_types
        ignore_msg = False
        if am:
            msg["header"] = self.get_part("header", msg["header"], msg_list)
            assert msg["header"] is not None
            if msg["header"]["msg_type"] not in am:  # type:ignore[unreachable]
                self.log.warning(
                    'Received message of type "%s", which is not allowed. Ignoring.'
                    % msg["header"]["msg_type"]
                )
                ignore_msg = True

        # Persist the map between cell_id and msg_id
        self.save_cell_id(channel, msg, msg_list)

        if not ignore_msg:
            stream = self.channels[channel]
            if self.subprotocol == "v1.kernel.websocket.jupyter.org":
                self.session.send_raw(stream, msg_list)
            else:
                self.session.send(stream, msg)


    async def handle_outgoing_message(self, stream: str, outgoing_msg: list[t.Any]) -> None:
        """Handle the outgoing messages from ZMQ sockets to Websocket."""
        msg_list = outgoing_msg
        _, fed_msg_list = self.session.feed_identities(msg_list)

        if self.subprotocol == "v1.kernel.websocket.jupyter.org":
            msg = {"header": None, "parent_header": None, "content": None}
        else:
            msg = self.session.deserialize(fed_msg_list)

        if isinstance(stream, str):
            stream = self.channels[stream]

        channel = getattr(stream, "channel", None)
        parts = fed_msg_list[1:]

        self._on_error(channel, msg, parts)

        # Handle output messages
        header = self.get_part("header", msg.get("header"), parts)
        msg_type = header["msg_type"]
        if msg_type in ("stream", "display_data", "execute_result", "error"):
            self.handle_output(msg_type, msg, parts)
            return

        # We can probably get rid of the rate limiting
        if self._limit_rate(channel, msg, parts):
            return

        if self.subprotocol == "v1.kernel.websocket.jupyter.org":
            self._on_zmq_reply(stream, parts)
        else:
            self._on_zmq_reply(stream, msg)
    
    def handle_output(self, msg_type, msg, parts):
        """Handle output messages by writing them to the server side Ydoc."""
        parent_header = self.get_part("parent_header", msg.get("parent_header"), parts)
        msg_id = parent_header["msg_id"]
        cell_id = self.get_cell_id(msg_id)
        self.log.info(f"Retreiving (msg_id, cell_id): ({msg_id} {cell_id})")
        content = self.get_part("content", msg.get("content"), parts)
        self.log.info(f"{cell_id} {msg_type} {content}")
        asyncio.create_task(self.output_task(msg_type, cell_id, content))

    async def output_task(self, msg_type, cell_id, content):
        """A coroutine to handle output messages."""
        settings = self.websocket_handler.settings
        kernel_session_manager = settings["session_manager"]
        try:
            kernel_session = await kernel_session_manager.get_session(kernel_id=self.kernel_id)
        except:
            pass
        path = kernel_session["path"]
        try:
            jupyter_server_ydoc = settings["jupyter_server_ydoc"]
            notebook = await jupyter_server_ydoc.get_document(path=path, copy=False, file_format='json', content_type='notebook')
        except:
            pass
        cells = notebook.ycells
        target = None
        for cell in cells:
            if cell["id"] == cell_id:
                target = cell
        if target is None:
            return
        output = self.transform_output(msg_type, content)
        target["outputs"].append(output)
    
    def transform_output(self, msg_type, content):
        """Transform output from IOPub messages to the nbformat specification."""
        if msg_type == "stream":
            output = Map({
                "output_type": "stream",
                "text": content["text"],
                "name": content["name"]
            })
        elif msg_type == "display_data":
            output = Map({
                "output_type": "display_data",
                "data": content["data"],
                "metadata": content["metadata"]
            })
        elif msg_type == "execute_result":
            output = Map({
                "output_type": "execute_result",
                "data": content["data"],
                "metadata": content["metadata"],
                "execution_count": content["execution_count"]
            })
        elif msg_type == "error":
            output = Map({
                "output_type": "error",
                "traceback": content["traceback"],
                "ename": content["ename"],
                "evalue": content["evalue"]
            })
        return output
