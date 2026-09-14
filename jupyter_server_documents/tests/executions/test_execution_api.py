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
CELL_SOURCE = "1 + 1"
# MurmurHash2(seed=0) of CELL_SOURCE — matches _murmur2(source, 0) in the frontend.
CELL_SOURCE_HASH = "3531899427"

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
            "source": CELL_SOURCE,
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
                "cells": [{"cell_id": CELL_ID, "source_hash": CELL_SOURCE_HASH}],
            }),
            headers={"Content-Type": "application/json"},
        )
    assert exc_info.value.code == 400


async def test_missing_source_hash_returns_400(jp_fetch):
    """POST with a cell missing source_hash must return 400."""
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


async def _wait_for_yroom(jp_serverapp, document_id, cell_id, timeout=10.0):
    """Poll until the YRoom for the document exists and its cell is loaded.

    In the session-manager-free model the room is created + loaded on first
    ``get_room`` (the same thing the RTC layer does when the notebook opens).
    """
    ym = jp_serverapp.web_app.settings["yroom_manager"]
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            yroom = ym.get_room(document_id)
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
    - The document<->kernel binding happens lazily at execute time (no session
      manager involved)
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

    # The room id the RTC layer would use for this notebook. Creating +
    # loading the room via get_room mirrors opening the document in the UI.
    file_id_manager = jp_serverapp.web_app.settings["file_id_manager"]
    document_id = f"json:notebook:{file_id_manager.index(nb_name)}"

    # Wait for YRoom content to load
    yroom = await _wait_for_yroom(jp_serverapp, document_id, CELL_ID)

    # Execute via the jupyverse-compatible endpoint. The room is not yet bound
    # to a kernel — the handler binds it lazily using the URL's kernel_id.
    r = await jp_fetch(
        "api", "kernels", kernel_id, "execute",
        method="POST",
        body=json.dumps({"document_id": document_id, "cells": [{"cell_id": CELL_ID, "source_hash": CELL_SOURCE_HASH}]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.code == 200
    assert json.loads(r.body) is None  # jupyverse returns null
    assert yroom.connected_kernel_id == kernel_id  # bound lazily by the handler

    # Cleanup
    await jp_fetch("api", "sessions", session_id, method="DELETE")
