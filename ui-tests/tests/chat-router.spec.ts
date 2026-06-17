import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  chatInstalled,
  getRoomInfo,
  getRouterFires,
  openChat,
  openedDocPath,
  recreateRoom,
  sendChatMessage,
  sourceText,
  SYNC_TEST_RUNS,
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

/** Number of recorded router fires whose body contains `sentinel`. */
function fireCount(fires: string[], sentinel: string): number {
  return fires.filter(body => body.includes(sentinel)).length;
}

/**
 * Creates + opens an empty `.chat`, resolving its server path. Skips the test
 * unless both jupyterlab-chat and jupyter-ai-router are installed (the router
 * observer must be attached for the fire counts to be meaningful).
 */
async function setupRouterChat(
  page: IJupyterLabPageFixture,
  tmpPath: string
): Promise<{ path: string; sentinel: string }> {
  await page.goto();
  test.skip(
    !(await chatInstalled(page)),
    'jupyterlab-chat is not installed in this environment'
  );

  const unique = uniqueToken();
  const fileName = `chat-router-${unique}.chat`;
  const target = `${tmpPath}/${fileName}`;

  await page.contents.uploadContent('{}', 'text', target);
  await openChat(page, target);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  const fires = await getRouterFires(page, path);
  test.skip(
    !fires.hooked,
    'jupyter-ai-router is not installed in this environment'
  );

  return { path, sentinel: `SENTINEL-${unique}` };
}

// ---------------------------------------------------------------------------
// Each sent message fires the router exactly once.
// ---------------------------------------------------------------------------
async function eachMessageFiresOnce({ page, tmpPath }: Fixtures): Promise<void> {
  const { path, sentinel } = await setupRouterChat(page, tmpPath);
  const first = `${sentinel}-A`;
  const second = `${sentinel}-B`;

  await sendChatMessage(page, first);
  await expect
    .poll(async () => fireCount((await getRouterFires(page, path)).fires, first), {
      timeout: 30000,
      message: 'router did not fire for the first message'
    })
    .toBe(1);

  await sendChatMessage(page, second);
  await expect
    .poll(async () => fireCount((await getRouterFires(page, path)).fires, second), {
      timeout: 30000,
      message: 'router did not fire for the second message'
    })
    .toBe(1);

  // Each message fired exactly once — no duplicate routing.
  const fires = (await getRouterFires(page, path)).fires;
  expect(fireCount(fires, first)).toBe(1);
  expect(fireCount(fires, second)).toBe(1);
}

// ---------------------------------------------------------------------------
// A reconnection (server room recreation) does not, on its own, re-fire the
// router for messages reloaded from disk.
// ---------------------------------------------------------------------------
async function reconnectionDoesNotRefire({
  page,
  tmpPath
}: Fixtures): Promise<void> {
  const { path, sentinel } = await setupRouterChat(page, tmpPath);

  // Send a message and wait for the router to fire for it (exactly once).
  await sendChatMessage(page, sentinel);
  await waitForServerContent(page, path, sentinel);
  await expect
    .poll(
      async () => fireCount((await getRouterFires(page, path)).fires, sentinel),
      { timeout: 30000, message: 'router did not fire for the message' }
    )
    .toBe(1);

  // Force the server to recreate the room from disk under a fresh clientID.
  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();
  const originalClientId = before!.client_id;
  expect(await recreateRoom(page, path)).toContain(originalClientId);

  // Wait until the room is back under a new clientID with the message reloaded
  // (proving the reconnection + disk reload genuinely happened).
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

  // The reload must NOT have re-fired the router: messages older than the
  // (re)connection time are skipped. Give any spurious fire a chance to land,
  // then assert the count is still exactly one.
  await page.waitForTimeout(1500);
  expect(
    fireCount((await getRouterFires(page, path)).fires, sentinel)
  ).toBe(1);

  // The router is still live after reconnect: a new message fires exactly once.
  // Use a token that does NOT contain `sentinel` as a substring, so the
  // per-token counts below don't collide.
  const after = sentinel.replace('SENTINEL', 'AFTERMSG');
  await sendChatMessage(page, after);
  await expect
    .poll(async () => fireCount((await getRouterFires(page, path)).fires, after), {
      timeout: 30000,
      message: 'router did not fire for the post-reconnect message'
    })
    .toBe(1);
  // ...and the original message is still only counted once.
  expect(
    fireCount((await getRouterFires(page, path)).fires, sentinel)
  ).toBe(1);
}

for (let run = 1; run <= SYNC_TEST_RUNS; run++) {
  const suffix = SYNC_TEST_RUNS > 1 ? ` [run ${run}/${SYNC_TEST_RUNS}]` : '';
  test(`router: each chat message fires the router exactly once${suffix}`, eachMessageFiresOnce);
  test(
    `router: reconnection alone does not re-fire the router${suffix}`,
    reconnectionDoesNotRefire
  );
}
