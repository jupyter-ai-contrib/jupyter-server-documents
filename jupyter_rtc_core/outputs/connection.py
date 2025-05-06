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

    def _save_cell_id(self, channel, msg, msg_list):
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
        self.log.info(f'execute_reply: {msg_id} {cell_id}')
        self._cell_ids[msg_id] = cell_id

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
        self._save_cell_id(channel, msg, msg_list)
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

        header = self.get_part("header", msg.get("header"), parts)
        msg_type = header["msg_type"]
        if msg_type == "stream" or msg_type == "display_data":
            parent_header = self.get_part("parent_header", msg.get("parent_header"), parts)
            self.log.info(header)
            self.log.info(parent_header)
            msg_id = parent_header["msg_id"]
            cell_id = self._cell_ids.get(msg_id)
            self.log.info(cell_id)
            content = self.get_part("content", msg.get("content"), parts)
            asyncio.create_task(self._handle_output(msg_type, cell_id, content))
            return

        if self._limit_rate(channel, msg, parts):
            return

        if self.subprotocol == "v1.kernel.websocket.jupyter.org":
            self._on_zmq_reply(stream, parts)
        else:
            self._on_zmq_reply(stream, msg)
    
    async def _handle_output(self, msg_type, cell_id, content):
        self.log.info(content)
        settings = self.websocket_handler.settings
        kernel_session_manager = settings["session_manager"]
        kernel_session = await kernel_session_manager.get_session(kernel_id=self.kernel_id)
        path = kernel_session["path"]
        self.log.info(path)
        jupyter_server_ydoc = settings["jupyter_server_ydoc"]
        notebook = await jupyter_server_ydoc.get_document(path=path, copy=False, file_format='json', content_type='notebook')
        cells = notebook.ycells
        target = None
        for cell in cells:
            if cell["id"] == cell_id:
                target = cell
        if target is None:
            return
        o = None
        if msg_type == "stream":
            o = Map({"output_type": "stream", "text": content["text"], "name": content["name"]})
        if o is not None:
            target["outputs"].append(o)
