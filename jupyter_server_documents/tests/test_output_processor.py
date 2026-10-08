"""
Tests for OutputProcessor.

The new API takes ycell (a live pycrdt.Map reference) and file_id directly,
eliminating all async session/file/cell lookups that the previous version
performed.
"""
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from uuid import uuid4

from pycrdt import Array, Doc, Map, Text

from ..outputs import OutputProcessor, OutputsManager
from ..ydocs import YNotebook


class OutputProcessorForTest(OutputProcessor):
    _test_settings = {}

    @property
    def settings(self):
        return self._test_settings

    @property
    def outputs_manager(self):
        return self._test_settings.get("outputs_manager")


def _make_processor(*, file_id="file-1", use_outputs_service=True):
    """Create an OutputProcessor with a mocked OutputsManager."""
    mock_outputs_mgr = MagicMock()
    mock_outputs_mgr.write.side_effect = lambda **kw: kw["output"]
    mock_outputs_mgr.get_output_index.return_value = None

    op = OutputProcessorForTest()
    op._test_settings = {"outputs_manager": mock_outputs_mgr}
    op.use_outputs_service = use_outputs_service
    return op, mock_outputs_mgr


def _make_ycell(outputs=None):
    """Make a plain-dict ycell mock whose outputs slot is a Python list."""
    outs = outputs if outputs is not None else []
    cell = {"outputs": outs, "cell_type": "code"}
    return cell


def _make_ydoc_cell():
    """Make a real ycell integrated into a pycrdt Doc, and return both."""
    doc = Doc()
    cells = doc.get("cells", type=Array)
    ycell = Map({
        "id": str(uuid4()),
        "cell_type": "code",
        "source": "",
        "outputs": Array([]),
    })
    cells.append(ycell)
    return doc, ycell


def test_instantiation():
    op = OutputProcessorForTest()
    assert isinstance(op, OutputProcessor)



def test_output_task_update_display_data():
    """update_display_data replaces an existing output by index."""
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "test-display-1"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        # Build a real YNotebook cell so pycrdt Array semantics apply
        notebook = YNotebook()
        ycell = Map({
            "id": cell_id,
            "cell_type": "code",
            "source": "",
            "outputs": Array([]),
        })
        notebook.ycells.append(ycell)

        op = OutputProcessorForTest()
        op._test_settings = {"outputs_manager": om}
        op.use_outputs_service = True

        content1 = {
            "data": {"text/plain": "v1"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("display_data", ycell, file_id, cell_id, content1)
        assert len(ycell["outputs"]) == 1

        content2 = {
            "data": {"text/plain": "v2"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("update_display_data", ycell, file_id, cell_id, content2)
        assert len(ycell["outputs"]) == 1



def test_output_task_update_display_after_clear_no_index_error():
    """Stale display_id index after clear_output must not raise IndexError."""
    cell_id = str(uuid4())
    file_id = str(uuid4())
    display_id = "racy-display"

    with TemporaryDirectory() as td:
        om = OutputsManager()
        om.outputs_path = Path(td) / "outputs"

        notebook = YNotebook()
        ycell = Map({
            "id": cell_id,
            "cell_type": "code",
            "source": "",
            "outputs": Array([]),
        })
        notebook.ycells.append(ycell)

        op = OutputProcessorForTest()
        op._test_settings = {"outputs_manager": om}
        op.use_outputs_service = True

        content_initial = {
            "data": {"text/plain": "initial"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        op._write_output("display_data", ycell, file_id, cell_id, content_initial)
        assert len(ycell["outputs"]) == 1

        # Simulate a clear_output race
        del ycell["outputs"][:]
        assert len(ycell["outputs"]) == 0
        assert om.get_output_index(display_id) == 0  # stale index

        content_update = {
            "data": {"text/plain": "updated"},
            "metadata": {},
            "transient": {"display_id": display_id},
        }
        # Must not raise IndexError — falls back to append
        op._write_output("update_display_data", ycell, file_id, cell_id, content_update)
        assert len(ycell["outputs"]) == 1



def test_clear_output_task_clears_ycell():
    ycell = _make_ycell([{"output_type": "stream", "text": "hello"}])
    op, mock_om = _make_processor()
    op._handle_clear_output(ycell, "file-1", "cell-1", {"wait": False})
    assert len(ycell["outputs"]) == 0
    # The outputs service must also be cleared to stay in sync with the YDoc.
    mock_om.clear.assert_called_once_with(file_id="file-1", cell_id="cell-1")



def test_clear_output_wait_defers_to_next_output():
    """clear_output(wait=True) defers clearing until the next output."""
    ycell = _make_ycell([{"output_type": "stream", "text": "old"}])
    op, _ = _make_processor()

    op._handle_clear_output(ycell, "file-1", "cell-1", {"wait": True})
    assert len(ycell["outputs"]) == 1
    assert "cell-1" in op._pending_clear_output_cells

    op._write_output("stream", ycell, "file-1", "cell-1", {
        "text": "new", "name": "stdout",
    })
    assert len(ycell["outputs"]) == 1
    assert ycell["outputs"][0]["text"] == "new"
    assert "cell-1" not in op._pending_clear_output_cells



def test_output_appended_to_ycell_directly():
    """With use_outputs_service=False outputs are written as CRDT types."""
    _, ycell = _make_ydoc_cell()
    op, _ = _make_processor(use_outputs_service=False)

    op._write_output("stream", ycell, None, "cell-1", {
        "text": "hello\n", "name": "stdout",
    })
    op._write_output("execute_result", ycell, None, "cell-1", {
        "data": {"text/plain": "42"}, "metadata": {}, "execution_count": 1,
    })
    outputs = ycell["outputs"]
    assert len(outputs) == 2
    # Every entry must be a pycrdt Map, and stream text must be a pycrdt Text:
    # JupyterLab updates outputs in place via `Map.get()`/`Text.insert()`,
    # which plain dicts and strings do not provide.
    assert isinstance(outputs[0], Map)
    assert outputs[0]["output_type"] == "stream"
    assert isinstance(outputs[0]["text"], Text)
    assert str(outputs[0]["text"]) == "hello\n"
    assert isinstance(outputs[1], Map)
    assert outputs[1]["output_type"] == "execute_result"


class TestStreamCoalescing:
    """
    Tests for direct-to-YDoc stream output writes (use_outputs_service=False).

    Consecutive stream messages with the same name must update one output's
    Y.Text, applying `\\r`/`\\b`/`\\n` with the same rules as JupyterLab's
    output area (`Private.processText`), so that a client replaying the shared
    document sees exactly what the frontend rendered.
    """

    def _write_stream(self, op, ycell, text, name="stdout", cell_id="cell-1"):
        op._write_output("stream", ycell, None, cell_id, {
            "text": text, "name": name,
        })

    def test_fragmented_carriage_return_stream(self):
        """A `\\r`-progress stream collapses into one output, one line."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        for i in range(1, 4):
            self._write_stream(op, ycell, f"\rprogress {i}/3")
        self._write_stream(op, ycell, "\rdone        \n")

        outputs = ycell["outputs"]
        assert len(outputs) == 1
        assert str(outputs[0]["text"]) == "done        \n"

    def test_fragmented_stream_appends(self):
        """Control-free fragments append to one output's Y.Text."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        for fragment in ("hel", "lo ", "world\n", "second line\n"):
            self._write_stream(op, ycell, fragment)

        outputs = ycell["outputs"]
        assert len(outputs) == 1
        assert str(outputs[0]["text"]) == "hello world\nsecond line\n"

    def test_newline_terminated_fragments_coalesce(self):
        """Ordinary print()-style fragments coalesce into one output."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        for i in range(100):
            self._write_stream(op, ycell, f"line {i}\n")

        outputs = ycell["outputs"]
        assert len(outputs) == 1
        expected = "".join(f"line {i}\n" for i in range(100))
        assert str(outputs[0]["text"]) == expected

    def test_newline_terminated_fragments_take_append_fast_path(self):
        """
        With the cursor at the end of the text, fragments free of `\\r` and
        `\\b` — newlines included — must be appended directly to the Y.Text
        without rebuilding the accumulated text. Rebuilding on every message
        is quadratic over a long line-based stream run.
        """
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        # The first fragment creates the output (and may process text).
        self._write_stream(op, ycell, "line 0\n")

        # Any later call to `_process_stream_text` implies the accumulated
        # text was materialized and rebuilt; the pure-append path must not.
        slow_path_calls = []

        def _spy(cursor, new_text, text=""):
            slow_path_calls.append(new_text)
            return OutputProcessor._process_stream_text(cursor, new_text, text)

        op._process_stream_text = _spy

        for i in range(1, 100):
            self._write_stream(op, ycell, f"line {i}\n")

        assert slow_path_calls == []
        outputs = ycell["outputs"]
        assert len(outputs) == 1
        expected = "".join(f"line {i}\n" for i in range(100))
        assert str(outputs[0]["text"]) == expected

        # A `\r` fragment must leave the fast path (and stay correct). The
        # text ends with '\n', so the "current line" is empty and the write
        # lands after it; a subsequent '\r' fragment then overwrites it.
        self._write_stream(op, ycell, "\rprogress")
        self._write_stream(op, ycell, "\rdone    ")
        assert slow_path_calls == ["\rprogress", "\rdone    "]
        assert str(ycell["outputs"][0]["text"]) == expected + "done    "

    def test_backspace_handling(self):
        """`\\b` deletes the previous character unless it is a newline."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        self._write_stream(op, ycell, "abc")
        self._write_stream(op, ycell, "\b\bXY")
        assert str(ycell["outputs"][0]["text"]) == "aXY"

        # A backspace must not delete across a newline.
        self._write_stream(op, ycell, "\n")
        self._write_stream(op, ycell, "\bz")
        assert str(ycell["outputs"][0]["text"]) == "aXY\nz"

    def test_mid_text_backspace_parity_vector(self):
        """
        Pin JupyterLab's mid-text backspace semantics: `\\b` at cursor 2 in
        'abcd' yields 'ad' with cursor 1 — the character *at* the cursor is
        dropped along with the one before it. JupyterLab's
        `Private.processText` applies
        `text.slice(0, idx0 - 1) + text.slice(idx0 + 1)`
        (packages/outputarea/src/model.ts); the server must match it
        character-for-character or replaying clients diverge from what the
        executing frontend rendered.
        """
        assert OutputProcessor._process_stream_text(2, "\b", "abcd") == ("ad", 1)

    def test_astral_overwrite_uses_code_point_widths(self):
        """
        Pin the deliberate divergence from JupyterLab for astral-plane
        characters: this port counts Unicode code points, so overwriting
        "ABCDE" with "\\r\\U0001f642" replaces one character — ("\\U0001f642BCDE",
        cursor 1). JupyterLab v4.6 counts UTF-16 code units and would
        produce ("\\U0001f642CDE", cursor 2) (an emoji is 2 units there). Exact
        parity is unattainable: UTF-16 unit arithmetic can split a surrogate
        pair into a lone surrogate, which pycrdt/yrs (valid-UTF-8 Rust
        strings) cannot represent at all. Code-point arithmetic is the
        closest well-defined behavior that never yields invalid text; see
        the `_process_stream_text` docstring.
        """
        assert OutputProcessor._process_stream_text(
            5, "\r\U0001f642", "ABCDE"
        ) == ("\U0001f642BCDE", 1)

    def test_interleaved_stdout_stderr(self):
        """A change of stream name starts a new output."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        self._write_stream(op, ycell, "out 1\n", name="stdout")
        self._write_stream(op, ycell, "err 1\n", name="stderr")
        self._write_stream(op, ycell, "err 2\n", name="stderr")
        self._write_stream(op, ycell, "out 2\n", name="stdout")

        outputs = ycell["outputs"]
        assert len(outputs) == 3
        assert [o["name"] for o in outputs] == ["stdout", "stderr", "stdout"]
        assert str(outputs[0]["text"]) == "out 1\n"
        assert str(outputs[1]["text"]) == "err 1\nerr 2\n"
        assert str(outputs[2]["text"]) == "out 2\n"

    def test_non_stream_output_ends_stream_run(self):
        """A non-stream output splits stream runs and resets cursor state."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        self._write_stream(op, ycell, "before")
        op._write_output("display_data", ycell, None, "cell-1", {
            "data": {"text/plain": "shown"}, "metadata": {},
        })
        self._write_stream(op, ycell, "\rafter")

        outputs = ycell["outputs"]
        assert len(outputs) == 3
        assert str(outputs[0]["text"]) == "before"
        assert outputs[1]["output_type"] == "display_data"
        assert str(outputs[2]["text"]) == "after"

    def test_equal_length_replacement_invalidates_cursor(self):
        """
        A stored mid-text cursor must not be trusted after another writer
        replaces the output text with different content of the same length.
        A length-only state check would reuse the stale cursor and overwrite
        the foreign content mid-text; the running-hash check detects the
        replacement and conservatively appends at the end instead.
        """
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        self._write_stream(op, ycell, "abcd")
        self._write_stream(op, ycell, "\rX")
        ytext = ycell["outputs"][0]["text"]
        assert str(ytext) == "Xbcd"  # stored state: length 4, cursor 1

        # Another writer replaces the text with equal-length content.
        del ytext[:]
        ytext += "wxyz"

        self._write_stream(op, ycell, "Q")
        # Not "wQyz" (stale cursor 1 reused); the replacement is detected
        # and the fragment lands at the end.
        assert str(ytext) == "wxyzQ"

    def test_multibyte_text_carriage_return_rewrite(self):
        """
        CRDT edits must use UTF-8 byte offsets. pycrdt Text indices count
        bytes, so a code-point prefix index would edit mid-character as soon
        as the common prefix ends after a multi-byte character.
        """
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        # Common prefix "a\U0001f642" is 2 code points but 5 UTF-8 bytes.
        self._write_stream(op, ycell, "a\U0001f642bc")
        self._write_stream(op, ycell, "\ra\U0001f642XY")
        outputs = ycell["outputs"]
        assert len(outputs) == 1
        assert str(outputs[0]["text"]) == "a\U0001f642XY"

        # The append fast path and its running hash must also survive
        # multi-byte text: the next rewind still trusts the cursor.
        self._write_stream(op, ycell, "é\n")
        self._write_stream(op, ycell, "\rZ")
        assert str(outputs[0]["text"]) == "a\U0001f642XYé\nZ"

    def test_replay_into_second_doc(self):
        """Replaying the YDoc yields identical, still-coalesced outputs."""
        doc, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        for i in range(1, 4):
            self._write_stream(op, ycell, f"\rstep {i}/3")
        self._write_stream(op, ycell, "\nfinished\n")

        replayed_doc = Doc()
        replayed_doc.apply_update(doc.get_update())
        replayed_cells = replayed_doc.get("cells", type=Array)
        replayed_outputs = replayed_cells[0]["outputs"]

        assert len(replayed_outputs) == 1
        assert str(replayed_outputs[0]["text"]) == "step 3/3\nfinished\n"
        assert replayed_cells.to_py() == doc.get("cells", type=Array).to_py()

    def test_clear_then_rewrite(self):
        """clear_output discards the coalescing state along with the outputs."""
        _, ycell = _make_ydoc_cell()
        op, _ = _make_processor(use_outputs_service=False)

        self._write_stream(op, ycell, "\rold text")
        op.process_output("clear_output", ycell, None, "cell-1", {"wait": False})
        assert len(ycell["outputs"]) == 0

        self._write_stream(op, ycell, "\rnew")
        outputs = ycell["outputs"]
        assert len(outputs) == 1
        assert str(outputs[0]["text"]) == "new"


def test_process_output_dispatches_stream():
    """process_output writes synchronously — no task needed."""
    ycell = _make_ycell()
    op, _ = _make_processor(use_outputs_service=False)
    op.process_output("stream", ycell, None, "cell-1", {"text": "hi", "name": "stdout"})
    assert len(ycell["outputs"]) == 1


def test_process_output_dispatches_clear():
    """process_output clears synchronously — no task needed."""
    ycell = _make_ycell([{"output_type": "stream", "text": "old"}])
    op, _ = _make_processor()
    op.process_output("clear_output", ycell, None, "cell-1", {"wait": False})
    assert len(ycell["outputs"]) == 0
