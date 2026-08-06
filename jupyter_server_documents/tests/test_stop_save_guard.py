"""Tests for the save-on-close guard in `YRoom.stop()`.

A graceful stop should only perform the final save when the document has
unsaved changes. The autosave loop already persists edits as they happen, so an
unconditional final save is usually redundant -- and each save is an
interruptible truncate+write. Skipping the redundant save avoids a needless
write window without dropping real changes.
"""
import pytest


@pytest.mark.asyncio
async def test_stop_skips_save_when_no_unsaved_changes(make_yroom):
    """A clean room (everything already persisted) schedules no final save."""
    room = await make_yroom(file_type="file")

    # After loading, the autosave loop has nothing pending.
    assert room.file_api.has_unsaved_changes is False

    room.stop(immediately=False)

    # No redundant save-on-close was scheduled.
    assert room._save_task is None
    await room.until_saved  # resolves immediately; must not hang


@pytest.mark.asyncio
async def test_stop_saves_when_unsaved_changes(make_yroom):
    """A room with pending changes performs the final save-on-close."""
    room = await make_yroom(file_type="file")

    # Simulate an edit that scheduled a save the autosave loop has not yet run.
    room.file_api.schedule_save()
    assert room.file_api.has_unsaved_changes is True

    room.stop(immediately=False)

    assert room._save_task is not None
    await room.until_saved
