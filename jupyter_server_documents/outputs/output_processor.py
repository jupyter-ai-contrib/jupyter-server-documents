import hashlib

from pycrdt import Map, Text

from traitlets import Bool, Dict, Set
from traitlets.config import LoggingConfigurable


class OutputProcessor(LoggingConfigurable):
    """
    Writes kernel output messages into a live pycrdt YDoc cell.

    All methods take a direct `ycell` reference (pycrdt.Map) and write
    synchronously.  There is no async work — the old async lookup chain
    (session → file_id → room → find_cell) is gone because the caller
    already has ycell, file_id, and cell_id.

    Writing synchronously also eliminates the race condition where a
    create_task from a previous execution could run after the cell was
    cleared for re-execution, appending stale outputs.
    """

    _pending_clear_output_cells: Set = Set(default_value=set())

    _stream_cursors: Dict = Dict(default_value={})
    """
    Per-cell `(text_length, cursor, hasher)` state for the stream output
    currently being coalesced into the cell's YDoc, keyed by cell ID.
    `hasher` is a running `blake2b` over the text this processor produced,
    used to detect that another writer has modified the output between
    fragments. Discarded when a cell's outputs are cleared or when a
    non-stream output arrives for the cell. See `_append_stream_output()`
    for more info.
    """

    use_outputs_service = Bool(
        default_value=True,
        help="Route outputs through the outputs service to minimise in-memory YDoc size.",
    ).tag(config=True)

    @property
    def outputs_manager(self):
        return self.parent.parent.parent.parent.web_app.settings["outputs_manager"]

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_output(
        self,
        msg_type: str,
        ycell,
        file_id: str | None,
        cell_id: str,
        content: dict,
    ) -> None:
        """
        Write an output message into the YDoc cell synchronously.

        Synchronous execution prevents the race where a stale task from a
        previous execution appends outputs after the cell has been cleared.
        """
        if msg_type == "clear_output":
            self._handle_clear_output(ycell, file_id, cell_id, content)
        else:
            self._write_output(msg_type, ycell, file_id, cell_id, content)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _handle_clear_output(self, ycell, file_id: str | None, cell_id: str, content: dict):
        wait = content.get("wait", False)
        if wait:
            self._pending_clear_output_cells.add(cell_id)
        else:
            self._clear_ycell_outputs(ycell, file_id, cell_id)

    def _write_output(
        self,
        msg_type: str,
        ycell,
        file_id: str | None,
        cell_id: str,
        content: dict,
    ):
        # Flush any pending clear before appending new output
        if cell_id in self._pending_clear_output_cells:
            self._clear_ycell_outputs(ycell, file_id, cell_id)
            self._pending_clear_output_cells.discard(cell_id)

        use_outputs_service = bool(self.use_outputs_service and file_id)

        if msg_type == "stream" and not use_outputs_service:
            # When writing directly into the YDoc, consecutive stream messages
            # with the same name must be coalesced into a single stream output
            # whose `text` is a Y.Text. JupyterLab's output area appends
            # incoming stream text to the *existing* last output; appending one
            # new output per kernel message makes JupyterLab merge the entries
            # locally and echo the merged text back into the shared document,
            # duplicating the fragments for any client that replays the YDoc.
            self._append_stream_output(ycell, cell_id, content)
            return

        # Any non-stream output ends the stream run currently being coalesced
        # (if any), so the next stream message starts a fresh output.
        self._stream_cursors.pop(cell_id, None)

        display_id = content.get("transient", {}).get("display_id")

        if use_outputs_service:
            output = self.transform_output(msg_type, content, ydoc=False)
            output = self.outputs_manager.write(
                file_id=file_id,
                cell_id=cell_id,
                output=output,
                display_id=display_id,
            )
        else:
            # The cell's `outputs` entry is a pycrdt Array; every entry must be
            # a pycrdt Map. Appending a plain dict breaks JupyterLab's next
            # update to the output (e.g. `output.get()` on a non-Map).
            output = self.transform_output(msg_type, content, ydoc=True)

        if output is None:
            return

        output_index = (
            self.outputs_manager.get_output_index(display_id)
            if display_id and self.use_outputs_service else None
        )
        outputs = ycell["outputs"]
        if output_index is not None and output_index < len(outputs):
            outputs[output_index] = output
        else:
            if output_index is not None:
                self.log.warning(
                    f"Stale output index {output_index} for display_id {display_id!r} "
                    f"(outputs length: {len(outputs)}), appending instead."
                )
            outputs.append(output)

    def _append_stream_output(self, ycell, cell_id: str, content: dict):
        """
        Write a stream message directly into the YDoc cell, coalescing
        consecutive messages with the same stream name into one output.

        The last output's `text` is a Y.Text that is updated in place with a
        minimal (common-prefix) delta, mirroring how JupyterLab's output area
        model appends stream text (`Private.addText` in
        `@jupyterlab/outputarea`). Control characters (`\\b`, `\\r`, `\\n`) are
        applied with the same cursor rules as JupyterLab's
        `Private.processText`, so a `\\r`-based progress bar collapses to one
        line on the server exactly as it does in the frontend.

        While the cursor is at the end of the text, fragments free of `\\r`
        and `\\b` (ordinary newline-terminated output) are appended directly
        to the Y.Text without materializing the accumulated text.
        """
        outputs = ycell["outputs"]
        name = content["name"]
        new_text = content["text"]

        last = outputs[-1] if len(outputs) else None
        if (
            last is not None
            and last.get("output_type") == "stream"
            and last.get("name") == name
            and isinstance(last.get("text"), Text)
        ):
            ytext = last["text"]
            state = self._stream_cursors.get(cell_id)

            if (
                "\r" not in new_text
                and "\b" not in new_text
                and (state is None or state[0] == state[1])
            ):
                # Fast path: only `\r` and `\b` can rewind the cursor. The
                # cursor is at the end of the text (a missing or stale state
                # also falls back to the end), and the `\n` rule appends at
                # the end and keeps the cursor there, so this fragment --
                # newlines included -- is a pure append. Appending directly
                # avoids materializing and prefix-diffing the accumulated
                # text on every message, which would be quadratic over an
                # ordinary line-based stream run. It appends at the *actual*
                # end of the text and reads nothing back, so it needs no
                # validation against the live text.
                ytext += new_text
                if state is not None:
                    length = state[0] + len(new_text)
                    hasher = state[2]
                    hasher.update(new_text.encode("utf-8"))
                    self._stream_cursors[cell_id] = (length, length, hasher)
                return

            current = str(ytext)
            # Restore the cursor for this cell's ongoing stream run. The
            # stored state is only trusted if both the length and the running
            # hash still match the current text; otherwise another writer has
            # modified the output between fragments (an equal-length
            # replacement would fool a length-only check into overwriting
            # foreign content mid-text), and the cursor conservatively falls
            # back to the end of the text.
            if (
                state is not None
                and state[0] == len(current)
                and state[2].digest() == self._text_hasher(current).digest()
            ):
                cursor = state[1]
            else:
                cursor = len(current)
            updated, cursor = self._process_stream_text(cursor, new_text, current)

            # Apply the change to the Y.Text as a minimal delta: keep the
            # common prefix, delete the differing tail, insert the new tail.
            # `prefix` is computed in code points, but pycrdt Text indices
            # are UTF-8 byte offsets, so convert before editing; a code-point
            # index would edit at the wrong position (or mid-character) as
            # soon as the text contains multi-byte characters.
            prefix = 0
            limit = min(len(current), len(updated))
            while prefix < limit and current[prefix] == updated[prefix]:
                prefix += 1
            byte_prefix = len(current[:prefix].encode("utf-8"))
            if prefix < len(current):
                del ytext[byte_prefix:]
            if prefix < len(updated):
                ytext.insert(byte_prefix, updated[prefix:])
        else:
            updated, cursor = self._process_stream_text(0, new_text)
            outputs.append(Map({
                "output_type": "stream",
                "text": Text(updated),
                "name": name,
            }))

        self._stream_cursors[cell_id] = (
            len(updated), cursor, self._text_hasher(updated)
        )

    @staticmethod
    def _text_hasher(text: str = ""):
        """
        Returns a running `blake2b` hash over `text`, used to validate the
        per-cell stream cursor state in `_stream_cursors`. The append fast
        path updates it incrementally, so validating a rewind costs no more
        than the rewind itself (which already materializes the text).
        """
        hasher = hashlib.blake2b(digest_size=16)
        if text:
            hasher.update(text.encode("utf-8"))
        return hasher

    @staticmethod
    def _process_stream_text(cursor: int, new_text: str, text: str = ""):
        """
        Apply stream text to `text` at `cursor`, honoring `\\b`, `\\r`, and
        `\\n` with the same rules as JupyterLab's `Private.processText` in
        `@jupyterlab/outputarea`. Returns the resulting `(text, cursor)`.

        DELIBERATE DIVERGENCE: this port counts Unicode code points, while
        JupyterLab's JavaScript counts UTF-16 code units, so overwriting
        across an astral-plane character (an emoji is 2 UTF-16 units but 1
        code point) covers a different width than a locally executed
        notebook: `("ABCDE", "\\r\U0001f642")` yields `("\U0001f642BCDE", 1)`
        here, where JupyterLab v4.6 yields `("\U0001f642CDE", 2)`. Exact
        parity is unattainable: UTF-16 unit arithmetic can split a surrogate
        pair (e.g. `\\b` after an emoji deletes one unit), producing a lone
        surrogate that pycrdt/yrs cannot represent at all (Rust strings are
        valid UTF-8). Code-point arithmetic is the closest well-defined
        behavior that never yields invalid text, so it is used knowingly.
        """
        # Fast path: without control characters, overwrite at the cursor.
        if not any(char in new_text for char in "\b\r\n"):
            text = text[:cursor] + new_text + text[cursor + len(new_text):]
            return text, cursor + len(new_text)

        offset = 0
        while offset < len(new_text):
            # Find the next control character at or after `offset`.
            control_positions = [
                position
                for char in "\n\b\r"
                if (position := new_text.find(char, offset)) >= 0
            ]
            control = min(control_positions) if control_positions else len(new_text)

            # Overwrite the text before the control character at the cursor.
            prefix = new_text[offset:control]
            text = text[:cursor] + prefix + text[cursor + len(prefix):]
            cursor += len(prefix)
            if control == len(new_text):
                break

            char = new_text[control]
            offset = control + 1
            if char == "\b":
                # Backspace deletes the previous character, unless it is a
                # newline or the cursor is at the start of the text. NOTE:
                # when the cursor is mid-text, the character *at* the cursor
                # is dropped along with the one before it -- this matches
                # JupyterLab's `Private.processText`, which applies
                # `text.slice(0, idx0 - 1) + text.slice(idx0 + 1)`
                # (packages/outputarea/src/model.ts), e.g. '\b' at cursor 2
                # in 'abcd' yields 'ad' with cursor 1. Do not "fix" this
                # here without changing JupyterLab in lockstep, or the
                # server-side text diverges from what the frontend renders.
                if cursor > 0 and text[cursor - 1] != "\n":
                    text = text[:cursor - 1] + text[cursor + 1:]
                    cursor -= 1
            elif char == "\r":
                # Carriage return moves the cursor to the start of the
                # current line.
                cursor = text.rfind("\n", 0, cursor) + 1
            else:
                # Newline appends at the end of the text and moves the cursor
                # there.
                text += "\n"
                cursor = len(text)
        return text, cursor

    def _clear_ycell_outputs(self, ycell, file_id: str | None, cell_id: str):
        self._stream_cursors.pop(cell_id, None)
        del ycell["outputs"][:]
        if self.use_outputs_service and file_id:
            self.outputs_manager.clear(file_id=file_id, cell_id=cell_id)

    # ── Output transformation ──────────────────────────────────────────────────

    def transform_output(self, msg_type: str, content: dict, ydoc: bool = False):
        """Convert an iopub message content dict to nbformat output structure."""
        factory = Map if ydoc else (lambda x: x)
        if msg_type == "stream":
            # A stream output's `text` must be a Y.Text inside the YDoc:
            # JupyterLab appends later stream fragments to it via
            # `Text.insert()`, which a plain string does not provide.
            text = Text(content["text"]) if ydoc else content["text"]
            return factory({
                "output_type": "stream",
                "text": text,
                "name": content["name"],
            })
        if msg_type in ("display_data", "update_display_data"):
            return factory({
                "output_type": "display_data",
                "data": content["data"],
                "metadata": content["metadata"],
            })
        if msg_type == "execute_result":
            return factory({
                "output_type": "execute_result",
                "data": content["data"],
                "metadata": content["metadata"],
                "execution_count": content["execution_count"],
            })
        if msg_type == "error":
            return factory({
                "output_type": "error",
                "traceback": content["traceback"],
                "ename": content["ename"],
                "evalue": content["evalue"],
            })
        return None
