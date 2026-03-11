from __future__ import annotations
import asyncio
import pytest
from unittest.mock import Mock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom


class TestDefaultYRoom():
    """
    Tests that assert against a default `YRoom` created via `make_yroom()`.
    """

    @pytest.mark.asyncio
    async def test_on_reset_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that the `on_reset()` callback passed to
        `YRoom.get_{awareness,jupyter_ydoc,ydoc}()` methods are each called with
        the expected object when the YDoc is reset.
        """
        yroom = await make_yroom()
        
        # Create mock callbacks
        awareness_reset_mock = Mock()
        jupyter_ydoc_reset_mock = Mock()
        ydoc_reset_mock = Mock()
        
        # Call get methods while passing `on_reset` callbacks
        yroom.get_awareness(on_reset=awareness_reset_mock)
        await yroom.get_jupyter_ydoc(on_reset=jupyter_ydoc_reset_mock)
        await yroom.get_ydoc(on_reset=ydoc_reset_mock)
        
        # Assert that each callback has not been called yet
        awareness_reset_mock.assert_not_called()
        jupyter_ydoc_reset_mock.assert_not_called()
        ydoc_reset_mock.assert_not_called()
        
        # Reset the ydoc and get the new expected objects
        yroom._reset_ydoc()
        new_awareness = yroom.get_awareness()
        new_jupyter_ydoc = await yroom.get_jupyter_ydoc()
        new_ydoc = await yroom.get_ydoc()
        
        # Assert that each callback was called exactly once with the expected
        # object
        awareness_reset_mock.assert_called_once_with(new_awareness)
        jupyter_ydoc_reset_mock.assert_called_once_with(new_jupyter_ydoc)
        ydoc_reset_mock.assert_called_once_with(new_ydoc)


class TestYRoomTimeout():
    """
    Tests for `YRoom` inactivity timeout behavior.
    """

    @pytest.mark.asyncio
    async def test_custom_inactivity_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that `inactivity_timeout` can be set via the constructor.
        """
        room = await make_yroom(inactivity_timeout=10)
        assert room.inactivity_timeout == 10

    @pytest.mark.asyncio
    async def test_basic_timeout(self, make_yroom: MakeYRoom):
        """
        Asserts that a room becomes inactive only after `inactivity_timeout`
        elapses.
        """
        room = await make_yroom(inactivity_timeout=1)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is False
        await asyncio.sleep(0.6)
        assert room.inactive is True

    @pytest.mark.asyncio
    async def test_get_awareness_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.get_awareness()
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_get_ydoc_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        await room.get_ydoc()
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_get_jupyter_ydoc_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        await room.get_jupyter_ydoc()
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_set_cell_execution_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_execution_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_set_cell_awareness_state_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.set_cell_awareness_state("cell-1", "busy")
        await asyncio.sleep(0.6)
        assert room.inactive is False

    @pytest.mark.asyncio
    async def test_restart_resets_activity(self, make_yroom: MakeYRoom):
        room = await make_yroom(inactivity_timeout=1)
        await asyncio.sleep(0.6)
        room.restart()
        await asyncio.sleep(0.6)
        assert room.inactive is False
