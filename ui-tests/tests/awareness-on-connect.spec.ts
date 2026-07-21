import { expect, IJupyterLabPageFixture, test } from '@jupyterlab/galata';
import {
  closeDocument,
  getClientAwareness,
  getRoomInfo,
  openDocument,
  openedDocPath,
  seedAwareness,
  uniqueToken,
  waitForRoom,
  waitForServerContent,
  typeInFileEditor
} from './helpers';

/**
 * Awareness-on-connect (jupyter-ai-contrib/jupyter-server-documents#279).
 *
 * A client that connects (or refreshes) must receive the room's *current*
 * awareness state as part of the sync handshake — not only when a later change
 * delta happens to re-touch a slot. Before the fix, awareness was broadcast
 * solely as deltas, so a slot published while the client wasn't connected (e.g.
 * a persona that announced itself before the client opened the document) could
 * take many seconds to appear, or never appear until something mutated it
 * again. This surfaced downstream as personas taking ~10s to load on refresh
 * (jupyter-ai-contrib/jupyter-ai-persona-manager#76).
 *
 * Reproduction — the fresh-connect path, matching the production scenario:
 *
 *   1. Open the document (client connects, room created).
 *   2. Close it (client disconnects; the room survives — GC is 60s).
 *   3. Seed a persona awareness slot into the still-alive room while no client
 *      is connected. The seeded peer never renews its clock, so no later delta
 *      re-touches the slot.
 *   4. Reopen the document — a genuinely fresh sync handshake against the same
 *      room, exactly like a browser refresh.
 *
 * On `main` step 4's handshake never carries awareness, so the persona slot
 * doesn't arrive within the window (its only hope is the seeded peer aging out
 * / renewing, which it doesn't) and the poll times out. With the fix the slot
 * rides the handshake and appears well under the 5s bar enforced here.
 */

test.use({ autoGoto: false });

type Fixtures = { page: IJupyterLabPageFixture; tmpPath: string };

/** The connect-to-awareness bar: personas must load fast, not in ~10s. */
const AWARENESS_DEADLINE_MS = 5000;

test('awareness present in a room is delivered on fresh connect', async ({
  page,
  tmpPath
}: Fixtures) => {
  await page.goto();

  const unique = uniqueToken();
  const fileName = `awareness-${unique}.txt`;
  const targetPath = `${tmpPath}/${fileName}`;
  const edit = `ALPHA-${unique}`;
  const personaToken = `PERSONA-${unique}`;

  await page.contents.uploadContent('', 'text', targetPath);
  await openDocument(page, targetPath);
  const path = await openedDocPath(page, fileName);
  await waitForRoom(page, path);

  // Establish + sync an edit so the room is live and on disk, then capture the
  // room's clientID: reopening must hit this *same* room (not a recreated one).
  await typeInFileEditor(page, edit);
  await waitForServerContent(page, path, edit);
  const before = await getRoomInfo(page, path);
  expect(before).not.toBeNull();

  // Disconnect this client by closing the document. The room stays alive.
  await closeDocument(page, path);

  // Publish a persona's awareness into the room while no client is connected,
  // so there is no live delta for any client to observe — the slot exists only
  // in the room's awareness map.
  const peerClientId = await seedAwareness(page, path, personaToken);
  const room = await getRoomInfo(page, path);
  expect(room, 'room should survive the disconnect').not.toBeNull();
  expect(room!.client_id).toBe(before!.client_id);

  // Reopen: a fresh sync handshake against the same room (like a refresh).
  const reopenStart = Date.now();
  await openDocument(page, targetPath);
  const reopenedPath = await openedDocPath(page, fileName);

  // Time how long the persona takes to appear in the reconnected client's
  // awareness. This is the connect path #279 fixes.
  await expect
    .poll(
      async () => {
        const states = await getClientAwareness(page, reopenedPath);
        return states != null && peerClientId in states;
      },
      {
        timeout: AWARENESS_DEADLINE_MS,
        message:
          'client never received the persona awareness slot within the ' +
          `${AWARENESS_DEADLINE_MS}ms deadline (issue #279)`
      }
    )
    .toBe(true);

  const elapsed = Date.now() - reopenStart;

  // Same room throughout — proves we exercised the ordinary connect handshake,
  // not a divergent room-recreation path.
  const after = await getRoomInfo(page, reopenedPath);
  expect(after).not.toBeNull();
  expect(after!.client_id).toBe(before!.client_id);

  // The slot carries the seeded persona payload, and it loaded fast.
  const finalStates = await getClientAwareness(page, reopenedPath);
  expect(finalStates?.[peerClientId]).toMatchObject({
    persona: { name: personaToken, id: personaToken }
  });
  expect(elapsed).toBeLessThan(AWARENESS_DEADLINE_MS);
});
