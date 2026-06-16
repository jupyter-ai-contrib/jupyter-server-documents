import { expect, IJupyterLabPageFixture } from '@jupyterlab/galata';

/**
 * Number of times each sync/divergent-sync test is registered (every repetition
 * is a distinct test case that must pass — this is not a retry). Resolution:
 *   - `JSD_SYNC_TEST_RUNS` env var, if set → that value
 *   - else, on CI → 5 (fan out to catch flakiness)
 *   - otherwise → 1 (fast local runs)
 */
export const SYNC_TEST_RUNS: number = (() => {
  const override = process.env.JSD_SYNC_TEST_RUNS;
  if (override !== undefined && override !== '') {
    return Number(override);
  }
  return process.env.CI ? 5 : 1;
})();

/**
 * A minimal valid notebook with a single empty code cell, as a JSON string
 * suitable for `page.contents.uploadContent(..., 'text', path)`.
 */
export const EMPTY_NOTEBOOK = JSON.stringify({
  cells: [
    {
      cell_type: 'code',
      source: [],
      metadata: {},
      outputs: [],
      execution_count: null
    }
  ],
  metadata: {},
  nbformat: 4,
  nbformat_minor: 5
});

/**
 * A unique-per-invocation token, used both as document content and as the file
 * name suffix. The random component guards against collisions across parallel
 * workers starting in the same millisecond.
 */
export function uniqueToken(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
}

/**
 * One open document room as reported by the test-only `/jsd-test/room-info`
 * endpoint.
 */
export interface IRoomInfo {
  room_id: string;
  /** Server-side YDoc clientID, as a string (avoids JS Number precision loss). */
  client_id: string;
  /**
   * Current content of the server's document. A string for text files, or the
   * notebook object for notebooks (see {@link sourceText} to normalize).
   */
  source: unknown;
}

/**
 * Normalizes a room's `source` (string for files, object for notebooks) to a
 * single searchable string. Returns `''` for a missing room.
 */
export function sourceText(room: IRoomInfo | null): string {
  if (!room || room.source == null) {
    return '';
  }
  return typeof room.source === 'string'
    ? room.source
    : JSON.stringify(room.source);
}

/**
 * Calls a `/jsd-test/*` endpoint from within the page so that the browser's
 * authentication cookies are used. Resolves the base URL and auth from the
 * running JupyterLab's server settings.
 */
async function callTestApi<T>(
  page: IJupyterLabPageFixture,
  subpath: string,
  init: { method?: string } = {}
): Promise<T> {
  return page.evaluate(
    async ({ subpath, init }) => {
      const settings = (window as any).jupyterapp.serviceManager.serverSettings;
      const xsrf = document.cookie.match(/\b_xsrf=([^;]+)/)?.[1] ?? '';
      const headers: Record<string, string> = { 'X-XSRFToken': xsrf };
      if (settings.token) {
        headers['Authorization'] = `token ${settings.token}`;
      }
      const res = await fetch(settings.baseUrl + subpath, { ...init, headers });
      if (!res.ok) {
        throw new Error(`${subpath} -> HTTP ${res.status}`);
      }
      return res.json();
    },
    { subpath, init }
  );
}

/**
 * Returns the single open document room backing the given file path, or `null`
 * if no room currently exists (e.g. during the reconnect window). Throws on any
 * other HTTP error.
 */
export async function getRoomInfo(
  page: IJupyterLabPageFixture,
  path: string
): Promise<IRoomInfo | null> {
  return page.evaluate(async (p: string) => {
    const settings = (window as any).jupyterapp.serviceManager.serverSettings;
    const xsrf = document.cookie.match(/\b_xsrf=([^;]+)/)?.[1] ?? '';
    const headers: Record<string, string> = { 'X-XSRFToken': xsrf };
    if (settings.token) {
      headers['Authorization'] = `token ${settings.token}`;
    }
    const res = await fetch(
      settings.baseUrl + `jsd-test/room-info?path=${encodeURIComponent(p)}`,
      { headers }
    );
    if (res.status === 404) {
      return null;
    }
    if (!res.ok) {
      throw new Error(`room-info -> HTTP ${res.status}`);
    }
    return res.json();
  }, path);
}

/**
 * Forces the server to free (and thus recreate-on-next-connect) the room(s)
 * for the given file path. Returns the old server clientID(s) that were freed.
 */
export async function recreateRoom(
  page: IJupyterLabPageFixture,
  path: string
): Promise<string[]> {
  const result = await callTestApi<{ freed: { old_client_id: string }[] }>(
    page,
    `jsd-test/recreate-room?path=${encodeURIComponent(path)}`,
    { method: 'POST' }
  );
  return result.freed.map(f => f.old_client_id);
}

/**
 * Resolves the full server path of an open document whose path ends with the
 * given file name. Galata stores test files under a per-test temporary
 * directory, so the real path differs from the bare file name.
 */
export async function getDocPath(
  page: IJupyterLabPageFixture,
  fileName: string
): Promise<string | null> {
  return page.evaluate((name: string) => {
    const app = (window as any).jupyterapp;
    for (const widget of app.shell.widgets('main')) {
      const context = (widget as any).context;
      if (context?.path && context.path.endsWith(name)) {
        return context.path as string;
      }
    }
    return null;
  }, fileName);
}

/**
 * Reads the current content of an open document from its shared model and
 * normalizes it to a searchable string (text source for files, JSON for
 * notebooks). Robust to editor DOM virtualization.
 */
export async function getDocText(
  page: IJupyterLabPageFixture,
  path: string
): Promise<string | null> {
  return page.evaluate((p: string) => {
    const app = (window as any).jupyterapp;
    for (const widget of app.shell.widgets('main')) {
      const context = (widget as any).context;
      if (context?.path === p && context.model?.sharedModel) {
        const source = context.model.sharedModel.getSource();
        return typeof source === 'string' ? source : JSON.stringify(source);
      }
    }
    return null;
  }, path);
}

/**
 * Types text into the open file editor with real per-character keystrokes
 * (exercising the editor → shared model path, not a direct model mutation).
 * The cursor is moved to the end of the line first, so repeated calls append.
 */
export async function typeInFileEditor(
  page: IJupyterLabPageFixture,
  text: string
): Promise<void> {
  const textbox = page.locator('.jp-FileEditor').getByRole('textbox');
  await textbox.click();
  await page.keyboard.press('End');
  await textbox.pressSequentially(text);
}

/**
 * Appends text to the end of a notebook cell with real keystrokes, via the
 * notebook UI (enter edit mode → move to end → type).
 */
export async function appendToCell(
  page: IJupyterLabPageFixture,
  cellIndex: number,
  text: string
): Promise<void> {
  await page.notebook.enterCellEditingMode(cellIndex);
  await page.keyboard.press('End');
  await page.keyboard.type(text);
  await page.notebook.leaveCellEditingMode();
}

/**
 * Opens a document by its exact path via the `docmanager:open` command. Avoids
 * file-browser navigation, which matches list items by name prefix and is
 * therefore fragile when sibling paths share a prefix.
 */
export async function openDocument(
  page: IJupyterLabPageFixture,
  path: string
): Promise<void> {
  await page.evaluate(async (p: string) => {
    await (window as any).jupyterapp.commands.execute('docmanager:open', {
      path: p
    });
  }, path);
}

/**
 * Resolves the open document's real server path, polling until the widget is
 * open. Galata stores files under a per-test temp dir, so the path differs from
 * the bare file name.
 */
export async function openedDocPath(
  page: IJupyterLabPageFixture,
  fileName: string
): Promise<string> {
  let path: string | null = null;
  await expect
    .poll(
      async () => {
        path = await getDocPath(page, fileName);
        return path;
      },
      { timeout: 30000, message: 'document widget never opened' }
    )
    .not.toBeNull();
  return path!;
}

/**
 * Waits until the document at `path` has an open server room. Doubles as a
 * check that the test extension loaded (a missing endpoint 404s just like a
 * missing room, and the room is created once the document is open).
 */
export async function waitForRoom(
  page: IJupyterLabPageFixture,
  path: string
): Promise<void> {
  await expect
    .poll(async () => (await getRoomInfo(page, path)) !== null, {
      timeout: 30000,
      message: 'room never created (is jsd_test_ext loaded?)'
    })
    .toBe(true);
}

/**
 * Waits until the server's copy of the document at `path` contains `token`,
 * confirming a client edit has synced to the server.
 */
export async function waitForServerContent(
  page: IJupyterLabPageFixture,
  path: string,
  token: string
): Promise<void> {
  await expect
    .poll(async () => sourceText(await getRoomInfo(page, path)).includes(token), {
      timeout: 30000,
      message: `server never received content '${token}'`
    })
    .toBe(true);
}

/**
 * Dismisses the "Select Kernel" dialog that appears when opening a notebook,
 * choosing "No Kernel" (none is needed for these content-sync tests). No-op if
 * no dialog appears.
 */
export async function dismissKernelDialogIfPresent(
  page: IJupyterLabPageFixture
): Promise<void> {
  const dialog = page.locator('.jp-Dialog');
  try {
    await dialog.waitFor({ state: 'visible', timeout: 10000 });
  } catch {
    return; // no dialog appeared
  }
  const combobox = dialog.getByRole('combobox');
  if (await combobox.count()) {
    // 'null' is the option value for "No Kernel" (see galata's createNew).
    await combobox.selectOption('null').catch(() => undefined);
  }
  await dialog.locator('.jp-mod-accept').click();
  await dialog
    .waitFor({ state: 'hidden', timeout: 10000 })
    .catch(() => undefined);
}
