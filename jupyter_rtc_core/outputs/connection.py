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
    _cell_indices = Dict(default_value={})

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
        try:
            cell_id = self.get_cell_id(msg_id)
        except KeyError:
            return
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

        # Find the target_cell and its cell_index and cache
        target_cell = None
        cell_index = None
        try:
            # See if we have a cached value for the cell_index
            cell_index = self._cell_indices[cell_id]
            target_cell = cells[cell_index]
        except KeyError:
            # Do a linear scan to find the cell
            self.log.info(f"Linear scan: {cell_id}")
            cell_index, target_cell = self.find_cell(cell_id, cells)
        else:
            # Verify that the cached value still matches
            if target_cell["id"] != cell_id:
                self.log.info(f"Invalid cache hit: {cell_id}")
                cell_index, target_cell = self.find_cell(cell_id, cells)
            else:
                self.log.info(f"Validated cache hit: {cell_id}")
        if target_cell is None:
            return

        output = self.transform_output(msg_type, content)
        target_cell["outputs"].append(output)
    
    def find_cell(self, cell_id, cells):
        """Find the cell with a given cell_id.
        
        This does a simple linear scan of the cells, but in reverse order because
        we believe that users are more often running cells towards the end of the
        notebook.
        """
        target_cell = None
        cell_index = None
        for i in reversed(range(0, len(cells))):
            cell = cells[i]
            if cell["id"] == cell_id:
                target_cell = cell
                cell_index = i
                self._cell_indices[cell_id] = cell_index
                break
        return cell_index, target_cell
    
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
