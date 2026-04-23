"""Tests for DocumentAwareMixin kernel_info_reply handling."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

from jupyter_server_documents.document_aware_mixin import DocumentAwareMixin


PYTHON_LANGUAGE_INFO = {
    "name": "python",
    "version": "3.10.0",
    "mimetype": "text/x-python",
    "codemirror_mode": {"name": "ipython", "version": 3},
    "pygments_lexer": "ipython3",
    "nbconvert_exporter": "python",
    "file_extension": ".py",
}

R_LANGUAGE_INFO = {
    "name": "R",
    "version": "4.3.0",
    "mimetype": "text/x-r-source",
    "file_extension": ".r",
}


def _make_kernel_info_msg(session, language_info):
    """Build a fake kernel_info_reply message dict."""
    content = {"language_info": language_info}
    return {"content": session.pack(content)}


class _StubClient(DocumentAwareMixin):
    """Minimal concrete class that uses DocumentAwareMixin for testing."""

    def __init__(self):
        self.session = Mock()
        self.session.unpack = lambda x: x
        self.session.pack = lambda x: x
        self.log = Mock()
        self._yrooms = set()
        self._pending_tasks = set()


def _make_mock_yroom(ymeta_data=None):
    """Create a mock YRoom with a notebook whose ymeta is a real dict.

    Using a plain dict to simulate pycrdt.Map behavior — .get() on a
    pycrdt Map returns Python types, so dict equality works the same way.
    """
    if ymeta_data is None:
        ymeta_data = {"metadata": {}}

    notebook = Mock()
    notebook.ymeta = ymeta_data

    yroom = Mock()
    yroom.get_jupyter_ydoc = AsyncMock(return_value=notebook)
    return yroom, notebook


class TestHandleKernelInfoReply:
    """Tests for _handle_kernel_info_reply guard logic."""

    def test_sets_language_info_when_absent(self):
        """language_info should be written when the notebook has none."""
        client = _StubClient()
        yroom, notebook = _make_mock_yroom()
        client._yrooms = {yroom}

        msg = _make_kernel_info_msg(client.session, PYTHON_LANGUAGE_INFO)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert notebook.ymeta["metadata"]["language_info"] == PYTHON_LANGUAGE_INFO

    def test_updates_language_info_when_changed(self):
        """language_info should be updated when the kernel changes."""
        client = _StubClient()
        yroom, notebook = _make_mock_yroom(
            {"metadata": {"language_info": PYTHON_LANGUAGE_INFO}}
        )
        client._yrooms = {yroom}

        msg = _make_kernel_info_msg(client.session, R_LANGUAGE_INFO)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert notebook.ymeta["metadata"]["language_info"] == R_LANGUAGE_INFO

    def test_skips_update_when_language_info_unchanged(self):
        """No write should occur when language_info is identical."""
        client = _StubClient()
        initial_metadata = {"language_info": PYTHON_LANGUAGE_INFO.copy()}
        yroom, notebook = _make_mock_yroom({"metadata": initial_metadata})
        client._yrooms = {yroom}

        writes = []

        class TrackedDict(dict):
            def __setitem__(self, key, value):
                writes.append(key)
                super().__setitem__(key, value)

        tracked = TrackedDict(initial_metadata)
        notebook.ymeta["metadata"] = tracked

        msg = _make_kernel_info_msg(client.session, PYTHON_LANGUAGE_INFO)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert "language_info" not in writes

    def test_no_update_when_language_info_is_none(self):
        """No update should happen when kernel_info_reply has no language_info."""
        client = _StubClient()
        yroom, notebook = _make_mock_yroom()
        client._yrooms = {yroom}

        msg = _make_kernel_info_msg(client.session, None)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert "language_info" not in notebook.ymeta["metadata"]

    def test_handles_multiple_yrooms(self):
        """language_info should be set on all connected yrooms."""
        client = _StubClient()
        yroom1, nb1 = _make_mock_yroom()
        yroom2, nb2 = _make_mock_yroom()
        client._yrooms = {yroom1, yroom2}

        msg = _make_kernel_info_msg(client.session, PYTHON_LANGUAGE_INFO)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert nb1.ymeta["metadata"]["language_info"] == PYTHON_LANGUAGE_INFO
        assert nb2.ymeta["metadata"]["language_info"] == PYTHON_LANGUAGE_INFO

    def test_continues_on_yroom_error(self):
        """A failing yroom should not prevent updates to other yrooms."""
        client = _StubClient()

        bad_yroom = Mock()
        bad_yroom.get_jupyter_ydoc = AsyncMock(side_effect=RuntimeError("boom"))

        good_yroom, notebook = _make_mock_yroom()
        client._yrooms = {bad_yroom, good_yroom}

        msg = _make_kernel_info_msg(client.session, PYTHON_LANGUAGE_INFO)
        asyncio.run(client._handle_kernel_info_reply(msg))

        assert notebook.ymeta["metadata"]["language_info"] == PYTHON_LANGUAGE_INFO
