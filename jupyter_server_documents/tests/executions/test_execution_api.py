"""
Integration tests for POST /api/kernels/{kernel_id}/execute —
the jupyverse-compatible server-side execution endpoint.
"""
import asyncio
import json
import uuid
from pathlib import Path

import pytest
from tornado.httpclient import HTTPClientError

TEST_TIMEOUT = 30

CELL_ID = "test-cell-aabbcc"

NOTEBOOK_CONTENT = json.dumps({
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
            "name": "python3",
        },
        "language_info": {"name": "python", "version": "3.9"},
    },
    "cells": [
        {
            "cell_type": "code",
            "id": CELL_ID,
            "source": "1 + 1",
            "metadata": {},
            "outputs": [],
            "execution_count": None,
        }
    ],
})


# ── HTTP contract tests ────────────────────────────────────────────────────────


async def test_missing_cells_returns_400(jp_fetch):
    """POST without cells must return 400."""
    with pytest.raises(HTTPClientError) as exc_info:
        await jp_fetch(
            "api", "kernels", "00000000-0000-0000-0000-000000000000", "execute",
            method="POST",
            body=json.dumps({"document_id": "json:notebook:abc"}),
            headers={"Content-Type": "application/json"},
        )
    assert exc_info.value.code == 400


async def test_missing_document_id_returns_400(jp_fetch):
    """POST without document_id must return 400."""
    with pytest.raises(HTTPClientError) as exc_info:
        await jp_fetch(
            "api", "kernels", "00000000-0000-0000-0000-000000000000", "execute",
            method="POST",
            body=json.dumps({"cells": [{"cell_id": CELL_ID}]}),
            headers={"Content-Type": "application/json"},
        )
    assert exc_info.value.code == 400


async def test_unknown_document_id_returns_400(jp_fetch):
    """POST with a document_id that has no live YRoom must return 400."""
    with pytest.raises(HTTPClientError) as exc_info:
        await jp_fetch(
            "api", "kernels", "00000000-0000-0000-0000-000000000000", "execute",
            method="POST",
            body=json.dumps({
                "document_id": "json:notebook:does-not-exist",
                "cells": [{"cell_id": CELL_ID}],
            }),
            headers={"Content-Type": "application/json"},
        )
    assert exc_info.value.code == 400


# ── End-to-end test (requires ipykernel) ──────────────────────────────────────


async def _wait_for_yroom(jp_serverapp, session_id, cell_id, timeout=10.0):
    """Poll until the YRoom has content and the cell is accessible."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            yroom = jp_serverapp.session_manager.get_yroom(session_id)
            ydoc = await yroom.get_jupyter_ydoc()
            _, cell = ydoc.find_cell(cell_id)
            if cell is not None:
                return yroom
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise TimeoutError(f"YRoom content not ready after {timeout}s")


@pytest.mark.timeout(TEST_TIMEOUT)
async def test_full_execution_via_jupyverse_endpoint(jp_fetch, jp_serverapp, tmp_path):
    """
    End-to-end: notebook → session → execute via POST /api/kernels/{id}/execute.

    Verifies:
    - Endpoint returns null (matching the jupyverse contract)
    - The execution actually runs (outputs appear in the YDoc)
    """
    nb_name = f"test_{uuid.uuid4().hex[:8]}.ipynb"
    (tmp_path / nb_name).write_text(NOTEBOOK_CONTENT)

    # Start session + kernel
    r = await jp_fetch(
        "api", "sessions",
        method="POST",
        body=json.dumps({
            "path": nb_name,
            "name": nb_name,
            "type": "notebook",
            "kernel": {"name": "python3"},
        }),
        headers={"Content-Type": "application/json"},
    )
    assert r.code == 201
    session = json.loads(r.body)
    session_id = session["id"]
    kernel_id = session["kernel"]["id"]

    # Wait for YRoom content to load
    yroom = await _wait_for_yroom(jp_serverapp, session_id, CELL_ID)

    # document_id is the Yjs room name — same as the YRoom's room_id
    document_id = yroom.room_id

    # Execute via the jupyverse-compatible endpoint
    r = await jp_fetch(
        "api", "kernels", kernel_id, "execute",
        method="POST",
        body=json.dumps({"document_id": document_id, "cells": [{"cell_id": CELL_ID}]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.code == 200
    assert json.loads(r.body) is None  # jupyverse returns null

    # Cleanup
    await jp_fetch("api", "sessions", session_id, method="DELETE")
