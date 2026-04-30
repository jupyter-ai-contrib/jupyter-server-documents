import asyncio
import time

from pycrdt import Map

from traitlets import Unicode, Bool, Set
from traitlets.config import LoggingConfigurable
from jupyter_server.serverapp import ServerApp

class OutputProcessor(LoggingConfigurable):
    
    _file_id = Unicode(default_value=None, allow_none=True)
    _pending_clear_output_cells = Set(default_value=set())

    use_outputs_service = Bool(
        default_value=True,
        help="Should outputs be routed to the outputs service to minimize the in memory ydoc size."
    ).tag(config=True)

    @property
    def settings(self):
        return ServerApp.instance().web_app.settings
    
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
    def yroom_manager(self):
        """A shortcut for the jupyter server ydoc manager."""
        return self.settings["yroom_manager"]

    async def _get_file_info(self):
        """Get file_id and path, using cached value when available.

        The file_id is looked up from the kernel session on first call
        and cached for subsequent calls. The cache is invalidated on
        execute_request (see clear_cell_outputs with trigger='execute_request').
        """
        if self._file_id:
            return self._file_id, None

        try:
            kernel_session = await self.session_manager.get_session(
                kernel_id=self.parent.parent.kernel_id
            )
            path = kernel_session["path"]
            file_id = self.file_id_manager.get_id(path)
            if file_id is None:
                self.log.error(f"Could not find file_id for path: {path}")
                return None, None
            self._file_id = file_id
            return file_id, path
        except Exception as e:
            self.log.warning(f"Failed to look up file_id: {e}")
            return None, None

    async def get_jupyter_ydoc(self, file_id):
        room_id = f"json:notebook:{file_id}"
        room = self.yroom_manager.get_room(room_id)
        if room is None:
            self.log.error(f"YRoom not found: {room_id}")
            return
        ydoc = await room.get_jupyter_ydoc()

        return ydoc

    async def _clear_ydoc_outputs(self, cell_id):
        """Clears the outputs of a cell in ydoc"""

        if not self._file_id:
            return

        notebook = await self.get_jupyter_ydoc(self._file_id)
        cell_index, target_cell = notebook.find_cell(cell_id)
        if target_cell is not None:
            num_outputs = len(target_cell["outputs"])
            target_cell["outputs"].clear()
            self.log.info(
                "[CLEAR-YDOC] cell_id=%s cell_index=%s wiped=%d outputs",
                cell_id, cell_index, num_outputs,
            )

    async def clear_cell_outputs(self, cell_id, *, trigger="unknown"):
        """Clears all outputs for a cell in ydoc and optionally on disk.

        Disk clearing only happens on execute_request (cell re-execution).
        clear_output messages from the kernel only clear the YDoc array
        since the next output_task will overwrite on disk naturally.
        """
        t0 = time.monotonic()
        self.log.info(
            "[CLEAR-START] cell_id=%s trigger=%s",
            cell_id, trigger,
        )

        file_id, path = await self._get_file_info()

        elapsed_ms = (time.monotonic() - t0) * 1000
        self.log.info(
            "[CLEAR-FILE-INFO] cell_id=%s trigger=%s file_id=%s elapsed=%.0fms",
            cell_id, trigger, file_id, elapsed_ms,
        )

        if file_id is None:
            return

        await self._clear_ydoc_outputs(cell_id)
        self._pending_clear_output_cells.discard(cell_id)

        if trigger == "execute_request":
            self._file_id = None
            file_id, path = await self._get_file_info()
            if file_id and self.use_outputs_service:
                self.outputs_manager.clear(file_id=file_id, cell_id=cell_id)
                self.log.info(
                    "[CLEAR-DISK] cell_id=%s trigger=%s file_id=%s",
                    cell_id, trigger, file_id,
                )

        total_ms = (time.monotonic() - t0) * 1000
        self.log.info(
            "[CLEAR-DONE] cell_id=%s trigger=%s total=%.0fms",
            cell_id, trigger, total_ms,
        )
            

    def process_output(self, msg_type: str, cell_id: str, content: dict):
        """Process outgoing messages from the kernel."""

        def task_done_callback(task):
            try:
                task.result()
            except Exception as e:
                self.log.error(f"Error in output task: {e}", exc_info=True)

        if msg_type == "clear_output":
            self.log.info(
                "[PROCESS] msg_type=clear_output cell_id=%s wait=%s",
                cell_id, content.get("wait", False),
            )
            task = asyncio.create_task(self.clear_output_task(cell_id, content))
            task.add_done_callback(task_done_callback)
        else:
            self.log.info(
                "[PROCESS] msg_type=%s cell_id=%s — creating output_task",
                msg_type, cell_id,
            )
            task = asyncio.create_task(self.output_task(msg_type, cell_id, content))
            task.add_done_callback(task_done_callback)

        return None

    async def clear_output_task(self, cell_id, content):
        """A courotine to handle clear_output messages"""

        wait = content.get("wait", False)
        if wait:
            self.log.info(
                "[CLEAR-OUTPUT-WAIT] cell_id=%s — deferring clear to next output",
                cell_id,
            )
            self._pending_clear_output_cells.add(cell_id)
        else:
            await self.clear_cell_outputs(cell_id, trigger="clear_output")

    async def output_task(self, msg_type, cell_id, content):
        """A coroutine to handle output messages."""

        t0 = time.monotonic()

        # Check for pending clear_output before processing output
        if cell_id in self._pending_clear_output_cells:
            self.log.info(
                "[OUTPUT-PENDING-CLEAR] cell_id=%s — clearing before write",
                cell_id,
            )
            await self.clear_cell_outputs(cell_id, trigger="pending_clear_output")

        # Get file_id and path from kernel session (handles renames)
        file_id, path = await self._get_file_info()
        if file_id is None:
            self.log.warning(
                "[OUTPUT-NO-FILE-ID] cell_id=%s msg_type=%s — output DROPPED",
                cell_id, msg_type,
            )
            return

        display_id = content.get("transient", {}).get("display_id")
        # Convert from the message spec to the nbformat output structure
        if self.use_outputs_service:
            output = self.transform_output(msg_type, content, ydoc=False)
            output = self.outputs_manager.write(
                file_id=file_id,
                cell_id=cell_id,
                output=output,
                display_id=display_id
            )
        else:
            output = self.transform_output(msg_type, content, ydoc=True)

        notebook = await self.get_jupyter_ydoc(file_id)
        if not notebook:
            return

        # Write the outputs to the ydoc cell.
        _, target_cell = notebook.find_cell(cell_id)
        if target_cell is not None and output is not None:
            output_index = self.outputs_manager.get_output_index(display_id) if display_id else None
            if output_index is not None and output_index < len(target_cell["outputs"]):
                target_cell["outputs"][output_index] = output
            else:
                if output_index is not None:
                    self.log.warning(
                        f"Stale output index {output_index} for display_id '{display_id}' "
                        f"(outputs length: {len(target_cell['outputs'])}), appending instead."
                    )
                target_cell["outputs"].append(output)

            elapsed_ms = (time.monotonic() - t0) * 1000
            self.log.info(
                "[OUTPUT-WRITTEN] cell_id=%s msg_type=%s num_outputs=%d elapsed=%.0fms",
                cell_id, msg_type, len(target_cell["outputs"]), elapsed_ms,
            )

    
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
        elif msg_type == "display_data" or msg_type == "update_display_data":
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
