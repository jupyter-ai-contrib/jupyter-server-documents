"""
Tests for data loss scenarios (issue #252).

Verifies that file content on disk is not lost when the server shuts down
during a divergent client sync handshake.
"""

from __future__ import annotations

import asyncio
import pycrdt
from pycrdt import Doc, Text
import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom

# Reuse FakeWebSocket from test_yroom_sync
from .test_yroom_sync import FakeWebSocket


class TestDataLossOnShutdown:
    """Tests that server shutdown during divergent sync does not cause data loss."""

    @pytest.mark.asyncio
    async def test_stop_during_divergent_handshake_does_not_save_empty(
        self, make_yroom: MakeYRoom, tmp_path
    ):
        """
        Scenario: YRoom has content "hello world!", a divergent client sends
        SS1 (clearing the YDoc source), then the server shuts down gracefully
        before SS2 arrives.

        Expected: The file on disk should NOT be empty.
        """
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world!"

        # Save initial content to disk
        await yroom.file_api.save(jupyter_ydoc)

        # Get the file path to check disk state later
        import os
        rel_path = yroom.file_api.get_path()
        file_path = os.path.join(yroom.file_api.contents_manager.root_dir, rel_path)

        # Create a divergent client (same content, different CRDT history)
        ws = FakeWebSocket()
        ws.doc["source"] += "hello world!"
        client_id = yroom.clients.add(ws)

        # Send SS1 — this triggers the divergent handshake which clears the source
        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        # At this point, the source should be cleared (divergent handshake in progress)
        # and file_api._reloading_content should be True
        assert yroom.file_api._reloading_content is True

        # Now simulate a graceful server shutdown (stop without immediately=True)
        yroom.stop(immediately=False)
        await yroom.until_saved

        # Check the file on disk — it should NOT be empty
        with open(file_path, "r") as f:
            disk_content = f.read()

        assert disk_content != "", "File on disk is empty — data loss occurred!"
        assert "hello world!" in disk_content, (
            f"Expected 'hello world!' on disk, got: {disk_content!r}"
        )

    @pytest.mark.asyncio
    async def test_watch_file_does_not_save_empty_during_divergent_handshake(
        self, make_yroom: MakeYRoom, tmp_path
    ):
        """
        Scenario: A save is already scheduled (from a normal edit), then a
        divergent client connects and clears the source. The _watch_file loop
        fires and calls save() while the source is empty.

        This reproduces a race condition: edit → schedule_save() → divergent
        client arrives → source cleared → poll fires → save() writes empty.

        Expected: The file on disk should NOT be empty.
        """
        yroom = await make_yroom()
        jupyter_ydoc = await yroom.get_jupyter_ydoc()
        jupyter_ydoc.source = "hello world!"

        # Save initial content to disk
        await yroom.file_api.save(jupyter_ydoc)

        # Get the file path
        import os
        rel_path = yroom.file_api.get_path()
        file_path = os.path.join(yroom.file_api.contents_manager.root_dir, rel_path)

        # Simulate a pending scheduled save (as if a normal edit just happened)
        yroom.file_api._save_scheduled = True

        # Create a divergent client
        ws = FakeWebSocket()
        ws.doc["source"] += "hello world!"
        client_id = yroom.clients.add(ws)

        # Send SS1 — triggers divergent handshake, clears source
        ss1 = ws.build_ss1()
        yroom.add_message(client_id, ss1)
        await asyncio.sleep(0.1)

        assert yroom.file_api._reloading_content is True

        # Simulate _watch_file firing: it sees _save_scheduled=True and calls save()
        await yroom.file_api.save(jupyter_ydoc)

        # Check the file on disk — it should NOT be empty
        with open(file_path, "r") as f:
            disk_content = f.read()

        assert disk_content != "", (
            "File on disk is empty — save() wrote empty content during divergent "
            "handshake because it does not check _reloading_content!"
        )
        assert "hello world!" in disk_content, (
            f"Expected 'hello world!' on disk, got: {disk_content!r}"
        )
