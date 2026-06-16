import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  appendToCell,
  dismissKernelDialogIfPresent,
  EMPTY_NOTEBOOK,
  getDocText,
  getRoomInfo,
  openDocument,
  openedDocPath,
  SYNC_TEST_RUNS,
  typeInFileEditor,
  uniqueToken,
  waitForRoom,
  waitForServerContent
} from './helpers';

/**
 * Don't load JupyterLab webpage before running the tests, matching the
 * convention in the other specs.
 */
test.use({ autoGoto: false });

/** Fixtures used by the test bodies below. */
type Fixtures = { page: IJupyterLabPageFixture; tmpPath: string };

/**
 * Brings the client back online and asserts that a *normal* reconnect (the
 * server room was never recreated) preserves all content — including edits made
 * while offline that the server never saw — with each part appearing exactly
 * once (no loss, no duplication). This is the counterpart to the divergent-sync
 * tests: it guards against the divergence detection over-firing and clearing
 * content on an ordinary reconnect (Proof 3).
 */
async function assertReconnectPreservesEdits(
  page: IJupyterLabPageFixture,
  path: string,
  originalClientId: string,
  parts: string[]
): Promise<void> {
  await page.context().setOffline(false);

  // Wait for reconnect and up-sync of the offline edit (the last part).
  await waitForServerContent(page, path, parts[parts.length - 1]);

  // The room must be the *same* one (clientID unchanged): this confirms the
  // client reconnected to the existing session rather than a recreated one, so
  // we are genuinely exercising the non-divergent path.
  const after = await getRoomInfo(page, path);
  expect(after).not.toBeNull();
  expect(after!.client_id).toBe(originalClientId);

  // Every part is preserved exactly once.
  const text = await getDocText(page, path);
  expect(text).not.toBeNull();
  for (const part of parts) {
    expect(text!.split(part).length - 1).toBe(1);
  }
}

/**
 * Normal reconnect for a text file: an edit made while offline (never synced)
 * must survive the reconnect rather than being cleared.
 */
async function textFileOfflineEdits({ page, tmpPath }: Fixtures): Promise<void> {
  await page.goto();

  const unique = uniqueToken();
  const fileName = `sync-${unique}.txt`;
  const targetPath = `${tmpPath}/${fileName}`;
  const online_edit = `ALPHA-${unique}`;
  const offline_edit = `BETA-${unique}`;

  await page.contents.uploadContent('', 'text', targetPath);
  await openDocument(page, targetPath);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  // Author and sync the first part while online.
  await typeInFileEditor(page, online_edit);
  await waitForServerContent(page, path, online_edit);
  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();

  // Drop the connection (no server-side room recreation) and edit offline.
  await page.context().setOffline(true);
  await typeInFileEditor(page, offline_edit);

  await assertReconnectPreservesEdits(page, path, before!.client_id, [
    online_edit,
    offline_edit
  ]);
}

/**
 * Normal reconnect for a notebook: a cell edit made while offline must survive
 * the reconnect rather than being cleared.
 */
async function notebookOfflineEdits({ page, tmpPath }: Fixtures): Promise<void> {
  await page.goto();

  const unique = uniqueToken();
  const nbName = `sync-${unique}.ipynb`;
  const targetPath = `${tmpPath}/${nbName}`;
  const online_edit = `ALPHA-${unique}`;
  const offline_edit = `BETA-${unique}`;

  await page.contents.uploadContent(EMPTY_NOTEBOOK, 'text', targetPath);
  await openDocument(page, targetPath);
  await dismissKernelDialogIfPresent(page);
  const path = await openedDocPath(page, nbName);
  await waitForRoom(page, path);

  // Author and sync the first part while online.
  await page.notebook.setCell(0, 'code', online_edit);
  await waitForServerContent(page, path, online_edit);
  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();

  // Drop the connection (no server-side room recreation) and edit offline.
  await page.context().setOffline(true);
  await appendToCell(page, 0, offline_edit);

  await assertReconnectPreservesEdits(page, path, before!.client_id, [
    online_edit,
    offline_edit
  ]);
}

for (let run = 1; run <= SYNC_TEST_RUNS; run++) {
  const suffix = SYNC_TEST_RUNS > 1 ? ` [run ${run}/${SYNC_TEST_RUNS}]` : '';
  test(`text file: offline edits survive a normal reconnect${suffix}`, textFileOfflineEdits);
  test(`notebook: offline edits survive a normal reconnect${suffix}`, notebookOfflineEdits);
}
