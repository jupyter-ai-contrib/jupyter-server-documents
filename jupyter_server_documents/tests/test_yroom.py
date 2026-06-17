from __future__ import annotations
import asyncio
import pytest
from unittest.mock import Mock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...conftest import MakeYRoom, MakeYRoomManager, MakeRoomFile


class TestYRoomCallbacks():
    """
    Tests for `YRoom` on_stop callback behavior.
    """

    @pytest.mark.asyncio
    async def test_on_stop_callbacks(self, make_yroom: MakeYRoom):
        """
        Asserts that `on_stop` callbacks registered via `add_stop_callback()`
        are called when the room is stopped.
        """
        yroom = await make_yroom()

        stop_mock_1 = Mock()
        stop_mock_2 = Mock()

        yroom.add_stop_callback(stop_mock_1)
        yroom.add_stop_callback(stop_mock_2)

        stop_mock_1.assert_not_called()
        stop_mock_2.assert_not_called()

        yroom.stop()

        stop_mock_1.assert_called_once()
        stop_mock_2.assert_called_once()


class TestYRoomInactivity():
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
