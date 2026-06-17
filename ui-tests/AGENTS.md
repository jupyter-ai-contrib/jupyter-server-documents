# UI Tests (Playwright E2E) — Agent Guide

This directory holds the browser-level end-to-end tests for
`jupyter-server-documents` (JSD), built on
[`@jupyterlab/galata`](https://github.com/jupyterlab/jupyterlab/tree/main/galata)
(JupyterLab's Playwright wrapper). This guide documents the setup so you can add
more UI tests without rediscovering the gotchas.

> Conventions: prefix `jlpm`/`jupyter` with the workspace venv if they aren't on
> your PATH, e.g. `PATH="../../.venv/bin:$PATH" jlpm playwright test`.

## TL;DR — how to run

```bash
cd ui-tests

# one-time setup
jlpm install
jlpm playwright install chromium

# run everything (Playwright auto-starts the server)
jlpm playwright test

# a single spec / a single test by title
jlpm playwright test tests/sync.spec.ts
jlpm playwright test -g "offline edits survive"

# list/compile-check without running the server
jlpm playwright test --list

# watch it happen / debug
jlpm playwright test --headed --slow-mo=500   # visible browser
jlpm playwright test --ui                      # interactive runner w/ time-travel
jlpm playwright test --debug                   # step through (Inspector)

# stability: run each test N times, ALL must pass (not a retry)
jlpm playwright test --repeat-each=10
```

## Layout

```
ui-tests/
├── jupyter_server_test_config.py   # Jupyter Server config used by the test server
├── jsd_test_ext.py                 # TEST-ONLY server extension (/jsd-test/* endpoints)
├── playwright.config.js            # Playwright config (port, webServer, base)
├── package.json                    # jlpm scripts + galata/playwright deps
└── tests/
    ├── helpers.ts                  # shared fixtures/utilities (import from here)
    ├── jupyter_server_documents.spec.ts  # extension-activation smoke test
    ├── sync.spec.ts                # normal (non-divergent) reconnect: edits preserved
    ├── divergent-sync.spec.ts      # divergent reconnect: no duplication / no loss
    ├── chat-sync.spec.ts           # jupyterlab-chat: no dup (divergent) / no loss (normal)
    └── chat-router.spec.ts         # jupyter-ai-router: each msg fires once; reconnect doesn't re-fire
```

## Optional dependencies (chat + router tests)

`chat-sync.spec.ts` and `chat-router.spec.ts` exercise two optional packages.
They `test.skip` cleanly when the package isn't installed, so the suite stays
green without them — but to run them locally you need:

```bash
# from the workspace root (uv-managed)
uv add "jupyterlab-chat>=0.18.2" jupyter-ai-router
# CI installs the same via pip in the integration-tests job.
```

- **`jupyterlab-chat`** provides the `.chat` document factory + the `YChat`
  shared model (messages live in a top-level `Y.Array` named `messages`).
- **`jupyter-ai-router`** provides the `MessageRouter` (at
  `settings["jupyter-ai"]["router"]`) that routes chat messages to observers.

**Version matching matters.** JSD bundles `jupyterlab-chat` as a shared
singleton in its prebuilt frontend (currently 0.18.2). The _installed_
`jupyterlab-chat` labextension must be module-federation-compatible with that
bundled version, or its plugins fail to activate and **the entire lab boot
hangs** (every ui-test then times out on the splash screen). `>=0.18.2` is the
floor; newer (e.g. 0.22.x) is compatible. Do **not** install an older
`jupyterlab-chat` (e.g. 0.12.x) — it is _not_ federation-compatible with the
0.18.2 frontend. Note `jupyterlab-chat` pulls in the full `jupyter-collaboration`
stack transitively; JSD ships config that disables the competing
`jupyter_server_ydoc` server extension and `@jupyter/docprovider-extension`
labextension, so JSD remains the sole collaboration provider.

## How the test server runs

- `playwright.config.js` defines a single `webServer` (`jlpm start` →
  `jupyter lab --config jupyter_server_test_config.py`). Playwright starts it
  once for the whole run and tears it down at the end.
- **Dedicated port `8899`** with `reuseExistingServer: false`. This means the
  test suite always launches its **own** auth-disabled server and never reuses
  (or collides with) a dev server you might have on the default `8888`. Both
  `webServer.url` and `use.baseURL` are pinned to `:8899`.
- `jupyter_server_test_config.py` calls galata's `configure_jupyter_server`
  (which disables auth and exposes JupyterLab JS objects on `window`), then adds
  the test-only extension to `sys.path` and enables it via
  `c.ServerApp.jpserver_extensions = {"jsd_test_ext": True}`.

### Parallelism & retries (current defaults)

- **One shared server** for all tests. With multiple workers, different spec
  _files_ may run concurrently against it; tests _within_ a file run serially
  (`fullyParallel` is not enabled in galata's base config).
- **`retries: 0`** — nothing is auto-retried, so a failure is a real failure and
  flakiness is never masked.
- Isolation comes from the test layer (see below), which is why concurrent runs
  against one server are safe.

## The test-only server extension (`jsd_test_ext.py`)

The data-loss bug only manifests when the **server recreates a document's YRoom
from disk under a fresh clientID** while the browser keeps its existing `Y.Doc`.
In production that's triggered by inactivity GC; relying on real timeouts is
flaky, so we trigger it deterministically with two endpoints (loaded **only** by
the test config — never ship this in production):

- `GET /jsd-test/room-info?path=<path>` → the single open room for that file as
  `{ room_id, client_id, source }`, or **404** if no room exists. `client_id` is
  a **string** (avoids JS `Number` precision loss); `source` is the file text or
  the notebook object. **Read-only**: it uses `list_document_rooms()` +
  `get_id()` and never calls `get_room()`, so it can't create a room.
- `POST /jsd-test/recreate-room?path=<path>` → calls `delete_room()` (which
  saves to disk + disconnects clients with close code 1001), so the next client
  message rebuilds the room fresh from disk under a new clientID — i.e. the
  divergent-history condition. Returns the freed old `client_id`(s).

Both endpoints are strictly **scoped by file path → file id**, so they only ever
touch the document under test, never another test's room or the shared
`JupyterLab:globalAwareness` room.

### Router hook (`/jsd-test/router-fires`)

For the `jupyter-ai-router` test, `jsd_test_ext.py` also attaches an observer to
the router's `MessageRouter` and records every routed message body per room:

- `GET /jsd-test/router-fires?path=<path>` → `{ fires: string[], count, hooked }`.
  `fires` is the ordered list of message bodies the router routed for the file's
  room; `hooked` is whether the router observer attached (i.e.
  `jupyter-ai-router` is installed — tests skip when it's `false`).

The hook is registered lazily (`IOLoop.add_callback` → poll
`settings["jupyter-ai"]["router"]`), because the `jupyter_ai_router` server
extension may load after this one. It calls `router.observe_chat_init(...)` and,
per room, `router.observe_chat_msg(room_id, recorder)`. The router only routes
messages newer than its connection time, so messages reloaded from disk on a
reconnect are **not** re-routed — which is exactly what `chat-router.spec.ts`
asserts.

## What the tests exercise (and where the fix lives)

- The client-side fix is in `src/docprovider/yprovider.ts`
  (`hasDivergentHistory` — a full state-vector subset check, **no** self
  exclusion — and `applyServerUpdate`, which clears + re-applies on divergence).
- The backend logs (but does not act on) divergence in
  `jupyter_server_documents/rooms/yroom.py` (`handle_sync` →
  `_has_divergent_history`).
- `divergent-sync.spec.ts`: author content → `recreate-room` → assert the client
  converges with the content present **exactly once** (catches duplication _and_
  loss). Asserts the room's `client_id` changed, proving divergence really
  happened.
- `sync.spec.ts`: the **negative/over-fire guard** — drop the network with
  `page.context().setOffline(true)` (no room recreation), edit offline,
  reconnect, and assert all edits survive and `client_id` is **unchanged**
  (proving it was a same-session, non-divergent reconnect).
- `chat-sync.spec.ts` (needs `jupyterlab-chat`): the same no-duplication
  (divergent recreate) and no-data-loss (offline reconnect) guarantees, but for
  a `.chat` document. Chat content is read from the rendered message DOM
  (`.jp-chat-messages-container .jp-chat-message`) since `getDocText` doesn't
  apply to chat.
- `chat-router.spec.ts` (needs `jupyterlab-chat` + `jupyter-ai-router`): asserts
  each sent message fires the router **exactly once**, and that a reconnection
  (room recreation + disk reload) does **not** re-fire the router — while a new
  message after reconnect still fires once. Reads `/jsd-test/router-fires`.

GC defaults make the offline approach safe: `YRoom.inactivity_timeout=60s`,
`YRoomManager.auto_free_interval=300s`, so a ~1s offline blip never GCs the room.

## `helpers.ts` API reference

Import everything from `./helpers`.

| Export                                        | Purpose                                                                                                                   |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `SYNC_TEST_RUNS`                              | How many times to register each repeatable test. `JSD_SYNC_TEST_RUNS` env override → else `5` on CI → else `1`.           |
| `EMPTY_NOTEBOOK`                              | JSON string of a minimal 1-empty-code-cell notebook for `uploadContent`.                                                  |
| `uniqueToken()`                               | `Date.now()-rand` token; use it for both file names and content sentinels.                                                |
| `IRoomInfo` / `sourceText(room)`              | Room shape; `sourceText` normalizes `source` (string or notebook object) to a searchable string (`''` if room is `null`). |
| `getRoomInfo(page, path)`                     | Single room or `null` (404). Throws on other HTTP errors.                                                                 |
| `recreateRoom(page, path)`                    | Forces server room recreation; returns freed old `client_id`s.                                                            |
| `openDocument(page, path)`                    | Opens a doc by **exact path** via the `docmanager:open` command.                                                          |
| `getDocPath(page, fileName)`                  | Real server path of an open widget whose path ends with `fileName` (or `null`).                                           |
| `openedDocPath(page, fileName)`               | Polls until the widget is open, returns its real path.                                                                    |
| `getDocText(page, path)`                      | Client-side document content as a normalized string (file source or notebook JSON).                                       |
| `typeInFileEditor(page, text)`                | Real keystrokes into the file editor (appends at end of line).                                                            |
| `appendToCell(page, idx, text)`               | Real keystrokes appended to a notebook cell.                                                                              |
| `waitForRoom(page, path)`                     | Polls until a room exists (also verifies the test extension loaded).                                                      |
| `waitForServerContent(page, path, token)`     | Polls until the server's copy contains `token` (i.e. the edit synced up).                                                 |
| `dismissKernelDialogIfPresent(page)`          | Dismisses the "Select Kernel" dialog (picks "No Kernel").                                                                 |
| `chatInstalled(page)`                         | Whether `jupyterlab-chat` is installed (`hasCommand('jupyterlab-chat:open')`); use to `test.skip`.                        |
| `openChat(page, path)`                        | Opens a `.chat` doc by exact path and waits for the chat input.                                                           |
| `sendChatMessage(page, content)`              | Types `content` into the chat input and sends it (real keystrokes).                                                       |
| `renderedMessageCount(page, sentinel)`        | Count of rendered chat messages containing `sentinel` (1=ok, 2=dup, 0=loss).                                              |
| `getRouterFires(page, path)` / `IRouterFires` | jupyter-ai-router fire record for the file's room: `{ fires, count, hooked }`.                                            |

## Recipe: add a new UI test

```ts
import { expect, test } from '@jupyterlab/galata';
import {
  EMPTY_NOTEBOOK,
  openDocument,
  openedDocPath,
  uniqueToken,
  waitForRoom,
  waitForServerContent,
  getDocText,
  typeInFileEditor,
  dismissKernelDialogIfPresent
} from './helpers';

test.use({ autoGoto: false });

test('my new file test', async ({ page, tmpPath }) => {
  await page.goto();

  const unique = uniqueToken();
  const fileName = `myfeature-${unique}.txt`;
  const target = `${tmpPath}/${fileName}`; // create inside the per-test temp dir
  const sentinel = `SENTINEL-${unique}`;

  await page.contents.uploadContent('', 'text', target);
  await openDocument(page, target);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  await typeInFileEditor(page, sentinel); // real keystrokes
  await waitForServerContent(page, path, sentinel); // wait for upsync

  // ... your scenario + assertions on getDocText(page, path) ...
});
```

For a notebook, upload `EMPTY_NOTEBOOK`, `openDocument`, then
`await dismissKernelDialogIfPresent(page)` before editing with
`page.notebook.setCell(...)` / `appendToCell(...)`.

### Repeating a test N times (every run must pass)

To bake repetition into a spec (per-test, in code — there is no
`test.repeat()`), register the test body in a loop. Reuse the shared
`SYNC_TEST_RUNS` constant so behavior is consistent and CI-aware:

```ts
import { SYNC_TEST_RUNS } from './helpers';

async function myBody({ page, tmpPath }: { page; tmpPath: string }) {
  /* ... */
}

for (let run = 1; run <= SYNC_TEST_RUNS; run++) {
  const suffix = SYNC_TEST_RUNS > 1 ? ` [run ${run}/${SYNC_TEST_RUNS}]` : '';
  test(`my new test${suffix}`, myBody);
}
```

Each repetition is a distinct test case (not a retry) and all must pass.

## Gotchas / conventions (read before writing tests)

1. **Open with `openDocument` (exact path), not `page.filebrowser.open` /
   `page.notebook.openByPath`.** The file-browser navigation matches list items
   by **name prefix**, which breaks (`strict mode violation: resolved to N
elements`) when sibling temp dirs share a prefix — exactly what happens under
   `--repeat-each`. `docmanager:open` takes the exact path and is robust.
2. **Use `tmpPath` + `uniqueToken()`.** Create files under galata's per-test
   `tmpPath` (auto-created, auto-deleted) and give them unique names so parallel
   tests/repeats never collide and nothing litters the server root.
3. **Resolve the real path.** Because of `tmpPath`, the document's server path is
   `tmpPath/fileName`, not the bare name. Use `openedDocPath(page, fileName)`.
4. **Read content via the shared model (`getDocText`), not the editor DOM.**
   CodeMirror virtualizes its DOM. Notebook source comes back as an object, so
   `getDocText`/`sourceText` JSON-stringify it — assert with substring/occurrence
   counts (`text.split(sentinel).length - 1 === 1`).
5. **Edit via real keystrokes**, not `sharedModel.setSource(...)`. Use
   `typeInFileEditor`, `appendToCell`, or `page.notebook.setCell` — these
   exercise the editor → CRDT path the way a user does.
6. **Notebooks pop a kernel dialog.** Always
   `await dismissKernelDialogIfPresent(page)` after opening a notebook, or
   subsequent clicks get intercepted by the modal.
7. **`getRoomInfo` returns `null` during the reconnect window** (room briefly
   gone after `recreate-room`). Poll for the condition you want; don't assume a
   room is always present.
8. **Don't touch `globalAwareness`.** It's the one genuinely global room; all
   helpers here are file-scoped on purpose.

## Known-benign log noise (not failures)

When the suite passes you may still see these in `[WebServer]` output — they're
teardown/eventing artifacts, unrelated to assertions:

- `An exception occurred when saving JupyterYDoc … 'NoneType' object has no
attribute 'strip'` — a final teardown save racing galata's deletion of the
  `tmpPath` file (the path resolves to `None` because the file is already gone).
- `Event listener Task-… failed for https://events.jupyter.org/…` — jupyter
  events emission noise.
- `Task was destroyed but it is pending! … _auto_free_rooms` — the GC background
  task being cancelled at shutdown.

## CI

The repo's integration-tests job runs `jlpm playwright test`; specs under
`ui-tests/tests/` are picked up automatically (no extra wiring). `SYNC_TEST_RUNS`
defaults to `5` on CI (set `JSD_SYNC_TEST_RUNS` to override). `test-results/` and
`playwright-report/` are git-ignored.
