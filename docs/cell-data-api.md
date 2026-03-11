# Cell Data API

Server extensions can write cell-level data to the notebook CRDT by registering a **cell data handler**. The handler receives kernel messages and writes data through a simple API on `YNotebook`.

Two storage layers are available:

- **Awareness** -- transient, real-time state broadcast to all clients (e.g. a live timer). Cleared when the server restarts.
- **Cell metadata** -- persistent state saved with the notebook file (e.g. timestamps).

## Registering a handler

At extension load time, grab `yroom_manager` and call `register_cell_data_handler`:

```python
def _load_jupyter_server_extension(server_app):
    # Defer so jupyter-server-documents has initialized first.
    server_app.io_loop.call_later(0, _register, server_app)

def _register(server_app):
    yroom_manager = server_app.web_app.settings.get("yroom_manager")
    if yroom_manager is None:
        return

    yroom_manager.register_cell_data_handler(
        msg_types=["execute_input", "execute_reply"],
        handler=my_handler,
        on_execute_request=my_pre_handler,   # optional
    )
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `msg_types` | `list[str]` | Kernel message types to listen for (e.g. `"execute_input"`, `"execute_reply"`, `"stream"`). |
| `handler` | `async (notebook, cell_id, msg_type, content, header) -> None` | Called when a matching message arrives from the kernel. |
| `on_execute_request` | `(notebook, cell_id) -> None` | Optional **sync** hook called before `execute_request` is forwarded to the kernel. Use this to clear stale state. |

## Writing cell data

The `notebook` argument passed to handlers is a `YNotebook` instance. All methods are **sync**.

### Awareness (transient)

```python
notebook.set_cell_awareness(cell_id, "my_namespace", {"key": "value"})
notebook.update_cell_awareness(cell_id, "my_namespace", key="new_value")
notebook.get_cell_awareness(cell_id, "my_namespace")   # -> dict
notebook.remove_cell_awareness(cell_id, "my_namespace")
```

- `set_cell_awareness` replaces the entire entry.
- `update_cell_awareness` merges fields into the existing entry (ignores `None` values).

Awareness data is stored under `cell_data.<namespace>.<cell_id>` in the Y.js awareness protocol and broadcast to all connected clients in real time.

### Cell metadata (persistent)

```python
notebook.set_cell_metadata(cell_id, "my_namespace", {"key": "value"})
notebook.update_cell_metadata(cell_id, "my_namespace", key="new_value")
notebook.get_cell_metadata(cell_id, "my_namespace")    # -> dict
notebook.remove_cell_metadata(cell_id, "my_namespace")
```

Same semantics as awareness, but writes to `cell.metadata.<namespace>` in the notebook CRDT and persists when the file is saved.

## Complete example

This is a minimal extension that records execution start/end times:

```python
def _on_execute_request(notebook, cell_id):
    """Clear stale data before the cell runs."""
    notebook.remove_cell_awareness(cell_id, "timing")
    notebook.set_cell_metadata(cell_id, "timing", {})

async def _handle_timing(notebook, cell_id, msg_type, content, header):
    """Write timestamps as they arrive from the kernel."""
    if msg_type == "execute_input":
        notebook.update_cell_awareness(cell_id, "timing", start=header["date"])
        notebook.update_cell_metadata(cell_id, "timing", start=header["date"])

    elif msg_type == "execute_reply":
        notebook.update_cell_awareness(cell_id, "timing", end=header["date"])
        notebook.update_cell_metadata(cell_id, "timing", end=header["date"])

def _load_jupyter_server_extension(server_app):
    server_app.io_loop.call_later(0, _register, server_app)

def _register(server_app):
    mgr = server_app.web_app.settings.get("yroom_manager")
    if mgr is None:
        return
    mgr.register_cell_data_handler(
        msg_types=["execute_input", "execute_reply"],
        handler=_handle_timing,
        on_execute_request=_on_execute_request,
    )
```

## Reading cell data on the frontend

Awareness data appears in the Y.js awareness states under `cell_data.<namespace>`:

```typescript
const states = awareness.getStates();
for (const [, state] of states) {
  const timing = state.cell_data?.timing?.[cellId];
  // { start: "2026-03-11T...", end: "2026-03-11T..." }
}
```

Cell metadata is available through the normal notebook model -- no special client code needed.
