"""
Unit tests for nudge_kernel().

All tests use a mock AsyncKernelClient — no real kernel required.
The mock's socket recv_multipart() is controlled via asyncio.Queue so
tests can deterministically deliver (or withhold) replies.
"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock

from jupyter_server_documents.nudge import nudge_kernel


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_msg(msg_type: str) -> list[bytes]:
    """Build a minimal two-frame message list: [identity, header_json]."""
    header = json.dumps({"msg_type": msg_type}).encode()
    return [b"<identity>", header]


class _MockSocket:
    """Async socket whose recv_multipart() is driven by a Queue."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()

    def put(self, msg_list):
        self._queue.put_nowait(msg_list)

    async def recv_multipart(self):
        return await self._queue.get()


def _make_client(shell_socket, control_socket, iopub_socket):
    session = MagicMock()
    session.feed_identities.side_effect = lambda msg_list: ([], msg_list)
    session.msg.return_value = {}
    session.send.return_value = None

    shell_channel = MagicMock()
    shell_channel.socket = shell_socket
    control_channel = MagicMock()
    control_channel.socket = control_socket
    iopub_channel = MagicMock()
    iopub_channel.socket = iopub_socket

    client = MagicMock()
    client.session = session
    client.shell_channel = shell_channel
    client.control_channel = control_channel
    client.iopub_channel = iopub_channel
    return client


# ── tests ─────────────────────────────────────────────────────────────────────

class TestNudgeKernel:

    @pytest.mark.asyncio
    async def test_idle_when_both_channels_reply(self):
        """Both shell and control reply → idle."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        shell.put(_make_msg("kernel_info_reply"))
        control.put(_make_msg("kernel_info_reply"))

        result = await nudge_kernel(client, kernel_info_timeout=1.0, kernel_info_reply_window=0.2)
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_busy_when_only_control_replies(self):
        """Control replies but shell stays silent → busy."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        control.put(_make_msg("kernel_info_reply"))
        # shell never replies

        result = await nudge_kernel(client, kernel_info_timeout=1.0, kernel_info_reply_window=0.05)
        assert result == "busy"

    @pytest.mark.asyncio
    async def test_unknown_when_nothing_replies(self):
        """No replies within timeout → unknown."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        # nothing put on any socket

        result = await nudge_kernel(client, kernel_info_timeout=0.05, kernel_info_reply_window=0.02)
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_iopub_welcome_logged_but_does_not_change_result(self):
        """iopub_welcome alone (no control reply) still returns unknown."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        iopub.put(_make_msg("iopub_welcome"))
        # no control or shell reply

        result = await nudge_kernel(client, kernel_info_timeout=0.1, kernel_info_reply_window=0.05)
        assert result == "unknown"

    @pytest.mark.asyncio
    async def test_idle_with_iopub_welcome_and_both_replies(self):
        """iopub_welcome + both channel replies → idle."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        iopub.put(_make_msg("iopub_welcome"))
        control.put(_make_msg("kernel_info_reply"))
        shell.put(_make_msg("kernel_info_reply"))

        result = await nudge_kernel(client, kernel_info_timeout=1.0, kernel_info_reply_window=0.2)
        assert result == "idle"

    @pytest.mark.asyncio
    async def test_pending_tasks_cleared_after_completion(self):
        """pending_tasks set is empty after nudge_kernel returns."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        control.put(_make_msg("kernel_info_reply"))
        shell.put(_make_msg("kernel_info_reply"))

        pending: set = set()
        await nudge_kernel(client, kernel_info_timeout=1.0, kernel_info_reply_window=0.2, pending_tasks=pending)
        assert len(pending) == 0

    @pytest.mark.asyncio
    async def test_pending_tasks_cancelled_on_external_cancel(self):
        """Tasks registered in pending_tasks can be cancelled externally."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        # nothing on sockets — nudge would block for the full timeout
        pending: set = set()

        nudge_task = asyncio.create_task(
            nudge_kernel(client, kernel_info_timeout=9999.0, kernel_info_reply_window=0.2, pending_tasks=pending)
        )
        await asyncio.sleep(0)  # let nudge start and register tasks

        assert len(pending) > 0
        for t in list(pending):
            t.cancel()

        # nudge_task itself will get CancelledError propagated via gather
        nudge_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await nudge_task

    @pytest.mark.asyncio
    async def test_wrong_msg_type_not_counted_as_reply(self):
        """Messages with unexpected msg_type are ignored."""
        shell = _MockSocket()
        control = _MockSocket()
        iopub = _MockSocket()
        client = _make_client(shell, control, iopub)

        # deliver a wrong message type on control, then nothing on shell
        control.put(_make_msg("execute_reply"))

        result = await nudge_kernel(client, kernel_info_timeout=0.1, kernel_info_reply_window=0.05)
        assert result == "unknown"
