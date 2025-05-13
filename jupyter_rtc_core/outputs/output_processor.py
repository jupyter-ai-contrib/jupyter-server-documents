import asyncio
import json

from pycrdt import Map

from traitlets import Dict, Unicode
from traitlets.config import LoggingConfigurable


class OutputProcessor(LoggingConfigurable):

    _cell_ids = Dict(default_value={}) # a map from msg_id -> cell_id
    _cell_indices = Dict(default_value={}) # a map from cell_id -> cell index in notebook
    _file_id = Unicode(default_value=None, allow_none=True)

    @property
    def settings(self):
        """A shortcut for the Tornado web app settings."""
        return self.parent.parent.webapp.settings

    @property
    def kernel_client(self):
        """A shortcut to the kernel client this output processor is attached to."""
        return self.parent

    @property
    def outputs_manager(self):
        """A shortcut for the OutputsManager instance."""
        return self.settings["outputs_manager"]
    
    @property
    def session_manager(self):
        """A shortcut for the kernel session manager."""
        return self.settings["session_manager"]

    @property
    def file_id_manager(self):
        """A shortcut for the file id manager."""
        return self.settings["file_id_manager"]
    
    @property
    def jupyter_server_ydoc(self):
        """A shortcut for the jupyter server ydoc manager."""
        return self.settings["jupyter_server_ydoc"]

    def clear(self, cell_id=None):
        """Clear the state of the output processor.
        
        This clears the state (saved msg_ids, cell_ids, cell indices) for the output
        processor. If cell_id is provided, only the state for that cell is cleared.
        """
        if cell_id is None:
            self._cell_ids = {}
            self._cell_indices = {}
        else:
            msg_id = self.get_msg_id(cell_id)
            if (msg_id is not None) and (msg_id in self._cell_ids): del self._cell_ids[msg_id]
            if cell_id in self._cell_indices: del self._cell_indices[cell_id]

    def set_cell_id(self, msg_id, cell_id):
        """Set the cell_id for a msg_id."""
        self._cell_ids[msg_id] = cell_id

    def get_cell_id(self, msg_id):
        """Retrieve a cell_id from a parent msg_id."""
        return self._cell_ids.get(msg_id)

    def get_msg_id(self, cell_id):
        """Retrieve a msg_id from a cell_id."""
        return {v: k for k, v in self._cell_ids.items()}.get(cell_id)

    # Incoming messages

    def process_incoming_message(self, channel: str, msg: list[bytes]):
        """Process incoming messages from the frontend.
        
        Save the cell_id <-> msg_id mapping

        msg = [p_header,p_parent,p_metadata,p_content,buffer1,buffer2,...]

        This method is used to create a map between cell_id and msg_id.
        Incoming execute_request messages have both a cell_id and msg_id.
        When output messages are send back to the frontend, this map is used
        to find the cell_id for a given parent msg_id.
        """
        if channel != "shell":
            return
        header = json.loads(msg[0]) # TODO use session unpack
        msg_type = header.get("msg_type")
        if msg_type != "execute_request":
            return
        msg_id = header.get("msg_id")
        metadata = json.loads(msg[2]) # TODO use session unpack
        cell_id = metadata.get("cellId")
        if cell_id is None:
            return

        existing_msg_id = self.get_msg_id(cell_id)
        if existing_msg_id != msg_id:  # cell is being re-run, clear output state
            self.clear(cell_id)
            if self._file_id is not None:
                self.outputs_manager.clear(file_id=self._file_id, cell_id=cell_id)
        self.log.info(f"Saving (msg_id, cell_id): ({msg_id} {cell_id})")
        self.set_cell_id(msg_id, cell_id)

    # Outgoing messages

    def process_outgoing_message(self, channel: str, msg: list[bytes]):
        """Process outgoing messagers from the kernel."""
        dmsg = self.kernel_client.session.deserialize(msg)
        msg_type = dmsg["header"]["msg_type"]
        msg_id = dmsg["parent_header"]["msg_id"]
        content = dmsg["content"]
        cell_id = self.get_cell_id(msg_id)
        if cell_id is None:
            return
        asyncio.create_task(self.output_task(msg_type, cell_id, content))
        return None # Don't allow the original message to propagate to the frontend

    async def output_task(self, msg_type, cell_id, content):
        """A coroutine to handle output messages."""
        try:
            kernel_session = await self.session_manager.get_session(kernel_id=self.kernel_id)
        except: # what exception to catch?
            return
        else:
            path = kernel_session["path"]

        file_id = self.file_id_manager.get_id(path)
        if file_id is None:
            return
        self._file_id = file_id
        try:
            notebook = await self.jupyter_server_ydoc.get_document(
                path=path,
                copy=False,
                file_format='json',
                content_type='notebook'
            )
        except: # what exception to catch?
            return
        cells = notebook.ycells

        cell_index, target_cell = self.find_cell(cell_id, cells)
        if target_cell is None:
            return

        # Convert from the message spec to the nbformat output structure
        output = self.transform_output(msg_type, content, ydoc=False)
        output_url = self.outputs_manager.write(file_id, cell_id, output)
        nb_output = Map({
                "output_type": "display_data",
                "data": {
                    'text/html': f'<a href="{output_url}">Output</a>'
                },
                "metadata": {
                    "outputs_service": True
                }
            })
        target_cell["outputs"].append(nb_output)

    def find_cell(self, cell_id, cells):
        """Find a cell with a given cell_id in the list of cells.
        
        This uses caching if we have seen the cell previously.
        """
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
            cell_index, target_cell = self.scan_cells(cell_id, cells)
        else:
            # Verify that the cached value still matches
            if target_cell["id"] != cell_id:
                self.log.info(f"Invalid cache hit: {cell_id}")
                cell_index, target_cell = self.scan_cells(cell_id, cells)
            else:
                self.log.info(f"Validated cache hit: {cell_id}")
        return cell_index, target_cell

    def scan_cells(self, cell_id, cells):
        """Find the cell with a given cell_id in the list of cells.
        
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
    
    def transform_output(self, msg_type, content, ydoc=False):
        """Transform output from IOPub messages to the nbformat specification."""
        if ydoc:
            factory = Map
        else:
            factory = lambda x: x
        if msg_type == "stream":
            output = factory({
                "output_type": "stream",
                "text": content["text"],
                "name": content["name"]
            })
        elif msg_type == "display_data":
            output = factory({
                "output_type": "display_data",
                "data": content["data"],
                "metadata": content["metadata"]
            })
        elif msg_type == "execute_result":
            output = factory({
                "output_type": "execute_result",
                "data": content["data"],
                "metadata": content["metadata"],
                "execution_count": content["execution_count"]
            })
        elif msg_type == "error":
            output = factory({
                "output_type": "error",
                "traceback": content["traceback"],
                "ename": content["ename"],
                "evalue": content["evalue"]
            })
        return output
