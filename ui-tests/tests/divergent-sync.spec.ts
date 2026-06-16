import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  dismissKernelDialogIfPresent,
  EMPTY_NOTEBOOK,
  getDocText,
  getRoomInfo,
  openDocument,
  openedDocPath,
  recreateRoom,
  sourceText,
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
 * Given an open document at `path` already containing `sentinel`, forces the
 * server to recreate its YRoom from disk under a fresh clientID (the divergent
 * history condition), then asserts the client converges with the sentinel
 * appearing exactly once — i.e. no duplication and no loss.
 */
async function assertNoDuplicationAfterRecreate(
  page: IJupyterLabPageFixture,
  path: string,
  sentinel: string
): Promise<void> {
  // Wait until the edit has synced to the server.
  await waitForServerContent(page, path, sentinel);

  // Capture the server's current clientID so we can prove it changes.
  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();
  const originalClientId = before!.client_id;

  // Force the server to recreate the room from disk under a fresh clientID.
  const freed = await recreateRoom(page, path);
  expect(freed).toContain(originalClientId);

  // Wait until the client has reconnected and the room exists again under a
  // *different* clientID — confirming divergence genuinely occurred. (During
  // the reconnect window `getRoomInfo` returns null, which the poll retries.)
  await expect
    .poll(
      async () => {
        const room = await getRoomInfo(page, path);
        return (
          room !== null &&
          room.client_id !== originalClientId &&
          sourceText(room).includes(sentinel)
        );
      },
      {
        timeout: 30000,
        message: 'server did not recreate the room under a new clientID'
      }
    )
    .toBe(true);

  // The client must converge to exactly one copy of the sentinel: more than one
  // means duplication, zero means loss.
  await expect
    .poll(
      async () => {
        const text = await getDocText(page, path);
        return text === null ? -1 : text.split(sentinel).length - 1;
      },
      {
        timeout: 30000,
        message: 'client did not converge to exactly one copy of the content'
      }
    )
    .toBe(1);
}

/**
 * Regression test for the data-loss / content-duplication bug
 * (jupyter-ai-contrib/jupyter-server-documents#252).
 *
 * Scenario: a single client authors a file's content, the content is synced and
 * saved, then the server recreates its YRoom from disk under a fresh clientID
 * (here forced deterministically via the test-only `/jsd-test` endpoint instead
 * of relying on the inactivity-GC timeout). On reconnect the client's Y.Doc
 * still holds the content under its original clientID while the server holds the
 * equivalent content under a new clientID — the "divergent history" condition.
 * Without resolution this produces duplication; the client-side divergence
 * detection in `yprovider.ts` must keep the content intact and un-duplicated.
 */
async function textFileNoDuplication({ page, tmpPath }: Fixtures): Promise<void> {
  await page.goto();

  const unique = uniqueToken();
  const fileName = `divergent-sync-${unique}.txt`;
  const targetPath = `${tmpPath}/${fileName}`;
  const sentinel = `SENTINEL-${unique}`;

  // Create the file inside galata's per-test temp dir (auto-cleaned), open it,
  // and resolve the document's real server path.
  await page.contents.uploadContent('', 'text', targetPath);
  await openDocument(page, targetPath);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  // Author the content by typing real keystrokes into the file editor.
  await typeInFileEditor(page, sentinel);

  await assertNoDuplicationAfterRecreate(page, path, sentinel);
}

/**
 * Same regression scenario as above, but for a notebook: a cell is authored via
 * the notebook UI (real keystrokes), and after the server recreates the room
 * the notebook content must contain the sentinel exactly once (no duplicated
 * cell / text, no loss).
 */
async function notebookNoDuplication({ page, tmpPath }: Fixtures): Promise<void> {
  await page.goto();

  const unique = uniqueToken();
  const nbName = `divergent-nb-${unique}.ipynb`;
  const targetPath = `${tmpPath}/${nbName}`;
  const sentinel = `SENTINEL-${unique}`;

  // Create a minimal valid notebook, open it, and resolve the real server path.
  await page.contents.uploadContent(EMPTY_NOTEBOOK, 'text', targetPath);
  await openDocument(page, targetPath);
  // Opening a notebook prompts for a kernel; dismiss it (none needed here).
  await dismissKernelDialogIfPresent(page);
  const path = await openedDocPath(page, nbName);
  await waitForRoom(page, path);

  // Author the content by typing real keystrokes into the first cell.
  await page.notebook.setCell(0, 'code', sentinel);

  await assertNoDuplicationAfterRecreate(page, path, sentinel);
}

for (let run = 1; run <= SYNC_TEST_RUNS; run++) {
  const suffix = SYNC_TEST_RUNS > 1 ? ` [run ${run}/${SYNC_TEST_RUNS}]` : '';
  test(
    `text file: no content duplication after the server recreates the room${suffix}`,
    textFileNoDuplication
  );
  test(
    `notebook: no content duplication after the server recreates the room${suffix}`,
    notebookNoDuplication
  );
}
