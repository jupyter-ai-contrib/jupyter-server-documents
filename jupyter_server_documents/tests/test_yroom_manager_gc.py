from __future__ import annotations
import asyncio
import gc
import uuid
import pytest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from ...conftest import MakeYRoomManager


class TestYRoomManagerGC:
    """Tests that YRoomManager frees inactive rooms from memory."""

    @pytest.mark.asyncio
    async def test_inactive_room_is_freed(self, make_yroom_manager: MakeYRoomManager, tmp_path: Path):
        """Asserts that an inactive room is eventually freed by _auto_free_rooms."""
        manager = make_yroom_manager(auto_free_interval=1)

        # Create a file and register it with the file ID manager
        path = tmp_path / f"{uuid.uuid4()}.txt"
        path.touch()
        file_id = manager.fileid_manager.index(str(path))
        room_id = f"text:file:{file_id}"

        # Create a room with a 1s inactivity timeout, wait for its content to be
        # loaded, then delete local reference to allow garbage collection
        room = manager.create_room(room_id, inactivity_timeout=1)
        await room.file_api.until_content_loaded
        del room

        # Wait for inactivity timeout + auto_free_interval + margin
        await asyncio.sleep(3)

        assert manager.was_room_freed(room_id)


# Sample objgraph code for debugging memory leaks
# Requires `pip install objgraph && brew install graphviz`
#
# def dump_bound_method_refs(room, output_path: str) -> None:
#     """Find the _on_jupyter_ydoc_update bound method held by referrers of
#     `room` and produce an objgraph backrefs image for it."""
#     import objgraph

#     gc.collect()
#     for ref in gc.get_referrers(room):
#         if callable(ref) and getattr(ref, '__qualname__', '').endswith('_on_jupyter_ydoc_update'):
#             print(f"Found bound method: {ref.__qualname__} @ {id(ref):#x}")
#             objgraph.show_backrefs(ref, max_depth=10, filename=output_path)
#             print(f"Wrote backrefs graph to {output_path}")
#             return
#     print("_on_jupyter_ydoc_update bound method not found among referrers")
