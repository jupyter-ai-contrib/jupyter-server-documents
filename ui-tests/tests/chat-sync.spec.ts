import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  chatInstalled,
  getRoomInfo,
  openChat,
  openedDocPath,
  recreateRoom,
  renderedMessageCount,
  sendChatMessage,
  sourceText,
  uniqueToken,
  waitForRoom,
  waitForServerContent
} from './helpers';

/**
 * Don't load JupyterLab webpage before running the tests (matches the other
 * specs).
 */
test.use({ autoGoto: false });

/** Fixtures used by the test bodies below. */
type Fixtures = { page: IJupyterLabPageFixture; tmpPath: string };

/** Occurrences of `sentinel` in the server's copy of the document. */
async function serverOccurrences(
  page: IJupyterLabPageFixture,
  path: string,
  sentinel: string
): Promise<number> {
  return sourceText(await getRoomInfo(page, path)).split(sentinel).length - 1;
}

/**
 * Creates an empty `.chat` file under the per-test temp dir, opens it, and
 * resolves its real server path. Skips the test if chat isn't installed.
 */
async function setupChat(
  page: IJupyterLabPageFixture,
  tmpPath: string
): Promise<{ path: string; sentinel: string }> {
  await page.goto();
  test.skip(
    !(await chatInstalled(page)),
    'jupyterlab-chat is not installed in this environment'
  );

  const unique = uniqueToken();
  const fileName = `chat-${unique}.chat`;
  const target = `${tmpPath}/${fileName}`;

  // An empty chat document is the JSON string "{}".
  await page.contents.uploadContent('{}', 'text', target);
  await openChat(page, target);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  return { path, sentinel: `SENTINEL-${unique}` };
}

// ---------------------------------------------------------------------------
// Divergent sync: no content duplication
//
// Author a message, force the server to recreate the room from disk under a
// fresh clientID (the divergent-history condition), and assert the message
// converges to exactly one copy. Chat messages live in a top-level Y.Array
// ('messages'), which the client-side divergence resolution clears + re-applies
// — so duplication must not occur.
// ---------------------------------------------------------------------------
async function chatNoDuplication({ page, tmpPath }: Fixtures): Promise<void> {
  const { path, sentinel } = await setupChat(page, tmpPath);

  await sendChatMessage(page, sentinel);
  await waitForServerContent(page, path, sentinel);

  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();
  const originalClientId = before!.client_id;

  // Force room recreation; the freed room's clientID must be the original one.
  const freed = await recreateRoom(page, path);
  expect(freed).toContain(originalClientId);

  // Divergence really happened: the room comes back under a *different*
  // clientID, still holding the message. (room-info is null mid-reconnect.)
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

  // Exactly one copy, both server-side and in the rendered message list.
  await expect
    .poll(async () => serverOccurrences(page, path, sentinel), {
      timeout: 30000,
      message: 'server did not converge to exactly one copy of the message'
    })
    .toBe(1);
  await expect
    .poll(async () => renderedMessageCount(page, sentinel), {
      timeout: 30000,
      message: 'client did not render exactly one copy of the message'
    })
    .toBe(1);
}

// ---------------------------------------------------------------------------
// Normal (non-divergent) reconnect: no data loss
//
// Send a message, then drop the network (no room recreation), send another
// message offline, and reconnect. Both messages must survive exactly once, and
// the room's clientID must be unchanged — proving this was a same-session,
// non-divergent reconnect (the over-fire guard for the divergence logic).
// ---------------------------------------------------------------------------
async function chatNoDataLoss({ page, tmpPath }: Fixtures): Promise<void> {
  const { path, sentinel } = await setupChat(page, tmpPath);
  const first = `${sentinel}-A`;
  const second = `${sentinel}-B`;

  await sendChatMessage(page, first);
  await waitForServerContent(page, path, first);

  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();

  // Drop the network, author a message offline, then reconnect.
  await page.context().setOffline(true);
  await sendChatMessage(page, second);
  await page.context().setOffline(false);

  // The offline message must sync up (no loss).
  await waitForServerContent(page, path, second);

  // Both messages present exactly once, server-side and in the rendered list.
  for (const message of [first, second]) {
    expect(await serverOccurrences(page, path, message)).toBe(1);
    expect(await renderedMessageCount(page, message)).toBe(1);
  }

  // Same session (no recreation) => clientID unchanged => non-divergent.
  const after = await getRoomInfo(page, path);
  expect(after).not.toBeNull();
  expect(after!.client_id).toBe(before!.client_id);
}

test(
  'chat: no content duplication after the server recreates the room',
  chatNoDuplication
);
test('chat: no data loss on a normal reconnect', chatNoDataLoss);
