// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.

/**
 * Regression tests for the divergent-history repair in `applyServerUpdate`.
 *
 * The repair must be IDEMPOTENT: repeating it against the same server state
 * must never delete content the server owns. The pre-fix implementation
 * cleared the full ordered range, so a second pass (reached whenever the
 * first repair's SyncStep2 (SS2) reply is lost) deleted the server's own
 * items and, once synced, emptied the document on disk — the notebook
 * truncated to a single blank cell reported in issue #305.
 *
 * Kept apart from yprovider.spec.ts, which mocks y-websocket and the request
 * layer: these tests drive the exported functions with real `Y.Doc`s only.
 */
import * as Y from 'yjs';
import {
  applyServerUpdate,
  hasDivergentHistory
} from '../docprovider/yprovider';

/**
 * Build a doc with `text` in a top-level Y.Text named `source`. Every call
 * returns a fresh `Y.Doc` with its own clientID, so two docs built from the
 * same text are, by construction, divergent peers: same visible content,
 * disjoint histories — a recreated server room and the client that outlived
 * the previous one.
 */
function makeDoc(text: string): Y.Doc {
  const doc = new Y.Doc();
  doc.getText('source').insert(0, text);
  return doc;
}

describe('applyServerUpdate divergent repair', () => {
  const TEXT = 'the quick brown fox';

  it('repairs a divergent client to exactly the server content', () => {
    const server = makeDoc(TEXT);
    const client = makeDoc(TEXT);
    const serverUpdate = Y.encodeStateAsUpdate(server);
    const serverSV = Y.encodeStateVector(server);

    expect(hasDivergentHistory(client, serverSV)).toBe(true);
    applyServerUpdate(client, serverUpdate, true, serverSV);

    expect(client.getText('source').toString()).toBe(TEXT);
  });

  it('is IDEMPOTENT: a second repair pass must not delete server content', () => {
    const server = makeDoc(TEXT);
    const client = makeDoc(TEXT);
    const serverUpdate = Y.encodeStateAsUpdate(server);
    const serverSV = Y.encodeStateVector(server);

    // Pass 1: normal repair.
    applyServerUpdate(client, serverUpdate, true, serverSV);
    expect(client.getText('source').toString()).toBe(TEXT);

    // The client's tombstones were "lost in transit" (server never applied
    // the SS2 reply), so the next handshake sees the client divergent AGAIN
    // and runs the repair against the same server state.
    expect(hasDivergentHistory(client, serverSV)).toBe(true);
    applyServerUpdate(client, serverUpdate, true, serverSV);

    // Pre-fix, the full-range clear deleted the server's items here and the
    // near-empty diff could not resurrect them: content became ''.
    expect(client.getText('source').toString()).toBe(TEXT);

    // And a third pass, for good measure.
    applyServerUpdate(client, serverUpdate, true, serverSV);
    expect(client.getText('source').toString()).toBe(TEXT);
  });

  it('preserves the server-known prefix of a partially-covered client', () => {
    // Client synced its first edit to the server, then typed more offline.
    const client = new Y.Doc();
    client.getText('source').insert(0, 'synced.');
    const server = new Y.Doc();
    Y.applyUpdate(server, Y.encodeStateAsUpdate(client));
    const serverSV = Y.encodeStateVector(server); // covers 'synced.' only
    client.getText('source').insert(7, ' offline-tail');

    const serverUpdate = Y.encodeStateAsUpdate(
      server,
      Y.encodeStateVector(client)
    );
    applyServerUpdate(client, serverUpdate, true, serverSV);

    // The covered prefix survives; the uncovered offline tail is sacrificed
    // (persisted file is the source of truth), matching the repair contract.
    expect(client.getText('source').toString()).toBe('synced.');
  });

  it('non-divergent path is a plain applyUpdate that preserves local edits', () => {
    const client = new Y.Doc();
    client.getText('source').insert(0, 'base');
    const server = new Y.Doc();
    Y.applyUpdate(server, Y.encodeStateAsUpdate(client));
    const serverSV = Y.encodeStateVector(server);
    client.getText('source').insert(4, ' + local edit');

    const serverUpdate = Y.encodeStateAsUpdate(
      server,
      Y.encodeStateVector(client)
    );
    applyServerUpdate(client, serverUpdate, false, serverSV);

    expect(client.getText('source').toString()).toBe('base + local edit');
  });

  it('leaves Y.Map content untouched during repair', () => {
    // Deleting the client's item for a key would make the key read as ABSENT
    // whenever the client's clientID outranks the server's (Yjs resolves a
    // key to its rightmost item and does not fall back to a live concurrent
    // one). Pin both orderings explicitly so such a regression is caught
    // deterministically; the surviving value is last-writer-wins.
    for (const [serverId, clientId] of [
      [1, 2],
      [2, 1]
    ]) {
      const server = new Y.Doc();
      server.clientID = serverId;
      server.getText('source').insert(0, TEXT);
      server.getMap('meta').set('kernelspec', 'python3');
      const client = new Y.Doc();
      client.clientID = clientId;
      client.getText('source').insert(0, TEXT);
      client.getMap('meta').set('kernelspec', 'stale');

      const serverUpdate = Y.encodeStateAsUpdate(server);
      const serverSV = Y.encodeStateVector(server);
      applyServerUpdate(client, serverUpdate, true, serverSV);
      applyServerUpdate(client, serverUpdate, true, serverSV);

      expect(client.getMap('meta').has('kernelspec')).toBe(true);
      expect(['python3', 'stale']).toContain(
        client.getMap('meta').get('kernelspec')
      );
    }
  });

  it('removes a fully server-unknown type with a single delete', () => {
    // A fresh divergence: the server covers none of the client's items. The
    // walker merges adjacent ranges, so however many items the type holds,
    // the repair issues one delete over the whole range rather than one
    // index-seeking delete per item. Counting `delete` calls pins the
    // merged-range strategy as a proxy for linear cost; if the implementation
    // changes, this may be loosened (e.g. to at most one call per maximal
    // uncovered run).
    const build = (): Y.Doc => {
      const doc = new Y.Doc();
      const cells = doc.getArray<Y.Map<unknown>>('cells');
      for (let i = 0; i < 50; i++) {
        const cell = new Y.Map<unknown>();
        cell.set('id', `cell-${i}`);
        cells.push([cell]);
      }
      return doc;
    };
    const server = build();
    const client = build();
    const cells = client.getArray('cells');
    const deleteSpy = jest.spyOn(cells, 'delete');

    const serverSV = Y.encodeStateVector(server);
    applyServerUpdate(
      client,
      Y.encodeStateAsUpdate(server, Y.encodeStateVector(client)),
      true,
      serverSV
    );

    expect(deleteSpy).toHaveBeenCalledTimes(1);
    expect(deleteSpy).toHaveBeenCalledWith(0, 50);
    expect(cells.length).toBe(50);
  });

  it('keeps a notebook intact across repeated repair passes', () => {
    // The document shape of issue #305: a `cells` Y.Array of Y.Map cells,
    // each with a Y.Text `source`, next to a `metadata` Y.Map.
    const build = (sources: string[]): Y.Doc => {
      const doc = new Y.Doc();
      const cells = doc.getArray<Y.Map<unknown>>('cells');
      for (const source of sources) {
        const cell = new Y.Map<unknown>();
        cell.set('cell_type', 'code');
        cell.set('source', new Y.Text(source));
        cells.push([cell]);
      }
      doc.getMap('metadata').set('kernelspec', { name: 'python3' });
      return doc;
    };
    const sourcesOf = (doc: Y.Doc): string[] =>
      doc
        .getArray<Y.Map<unknown>>('cells')
        .toArray()
        .map(cell => (cell.get('source') as Y.Text).toString());
    const handshake = (client: Y.Doc, server: Y.Doc): Uint8Array => {
      const serverSV = Y.encodeStateVector(server);
      const divergent = hasDivergentHistory(client, serverSV);
      expect(divergent).toBe(true);
      applyServerUpdate(
        client,
        Y.encodeStateAsUpdate(server, Y.encodeStateVector(client)),
        divergent,
        serverSV
      );
      // The client's SS2 reply.
      return Y.encodeStateAsUpdate(client, serverSV);
    };

    const server = build(['a=1', 'b=2']);
    const client = build(['a=1', 'b=2']);

    // Pass 1 repairs; its reply is lost.
    handshake(client, server);
    expect(sourcesOf(client)).toEqual(['a=1', 'b=2']);

    // Offline, before the next handshake: the user types into an existing
    // cell, deletes another and adds a new one.
    const cells = client.getArray<Y.Map<unknown>>('cells');
    (cells.get(0).get('source') as Y.Text).insert(3, ' # typed');
    cells.delete(1, 1);
    const added = new Y.Map<unknown>();
    added.set('cell_type', 'code');
    added.set('source', new Y.Text('c=3'));
    cells.push([added]);

    // Pass 2 against the same server state. The full-range clear this
    // replaces deleted the server's cells here: `cells` ended up [] while
    // `metadata` survived.
    const reply = handshake(client, server);
    Y.applyUpdate(server, reply);

    // The server's cells survive, as does the metadata. The edit inside an
    // existing (server-owned) cell is kept and reaches the server, and so
    // does the deletion of a server-owned cell (the walker skips items that
    // are already deleted); the offline top-level cell is sacrificed like any
    // other server-unknown top-level item.
    expect(sourcesOf(client)).toEqual(['a=1 # typed']);
    expect(sourcesOf(server)).toEqual(['a=1 # typed']);
    expect(client.getMap('metadata').get('kernelspec')).toEqual({
      name: 'python3'
    });
  });

  it('repairs Y.XmlFragment child nodes and keeps them across passes', () => {
    // The walker treats `Y.XmlFragment` (and `Y.XmlElement`) like the other
    // ordered types: child nodes are items, attributes are key-based.
    const build = (): Y.Doc => {
      const doc = new Y.Doc();
      const p = new Y.XmlElement('p');
      p.setAttribute('id', 'intro');
      p.insert(0, [new Y.XmlText(TEXT)]);
      doc.getXmlFragment('body').insert(0, [p]);
      return doc;
    };
    const server = build();
    const client = build();
    const expected = server.getXmlFragment('body').toString();
    expect(client.getXmlFragment('body').toString()).toBe(expected);

    const serverUpdate = Y.encodeStateAsUpdate(server);
    const serverSV = Y.encodeStateVector(server);
    applyServerUpdate(client, serverUpdate, true, serverSV);
    // One <p>, not two: the client's own node was deleted, the server's kept.
    expect(client.getXmlFragment('body').length).toBe(1);
    expect(client.getXmlFragment('body').toString()).toBe(expected);

    // A second pass must not delete the server's node.
    applyServerUpdate(client, serverUpdate, true, serverSV);
    expect(client.getXmlFragment('body').length).toBe(1);
    expect(client.getXmlFragment('body').toString()).toBe(expected);
  });
});

describe('hasDivergentHistory clock comparison', () => {
  it('two tabs with unequal stale history converge without duplication (non-self clock overhang is divergent)', () => {
    // Two tabs hold unequal amounts of a dead session's history. The
    // less-complete tab repairs first and its SS2 reply teaches the
    // recreated room a PREFIX of the stale clientID, as tombstones. When
    // the fuller tab then reconnects, presence-only detection sees every
    // clientID covered and skips the repair — its stale tail syncs as live
    // items next to the server's re-authored copy: permanent duplication
    // on disk. The whole handshake is simulated so the property pinned is
    // the convergence, not just the boolean.
    const staleSession = new Y.Doc();
    staleSession.getText('source').insert(0, 'one|');
    const prefix = Y.encodeStateAsUpdate(staleSession);
    staleSession.getText('source').insert(4, 'two|');
    const full = Y.encodeStateAsUpdate(staleSession);

    // Instantiate the root type before syncing, as the provider's document
    // model does; the repair walks instantiated types only.
    const lesserTab = new Y.Doc();
    lesserTab.getText('source');
    Y.applyUpdate(lesserTab, prefix);
    const fullerTab = new Y.Doc();
    fullerTab.getText('source');
    Y.applyUpdate(fullerTab, full);

    const server = new Y.Doc();
    server.getText('source').insert(0, 'one|two|'); // re-authored from disk

    // The lesser tab reconnects first: divergent, repairs, reply lands.
    const sv0 = Y.encodeStateVector(server);
    expect(hasDivergentHistory(lesserTab, sv0)).toBe(true);
    applyServerUpdate(
      lesserTab,
      Y.encodeStateAsUpdate(server, Y.encodeStateVector(lesserTab)),
      true,
      sv0
    );
    Y.applyUpdate(server, Y.encodeStateAsUpdate(lesserTab, sv0));
    expect(server.getText('source').toString()).toBe('one|two|');

    // Now the fuller tab: the server covers the stale clientID, but only up
    // to 'one|'. Presence-only detection says "not divergent" here.
    const sv1 = Y.encodeStateVector(server);
    const divergent = hasDivergentHistory(fullerTab, sv1);
    expect(divergent).toBe(true);
    applyServerUpdate(
      fullerTab,
      Y.encodeStateAsUpdate(server, Y.encodeStateVector(fullerTab)),
      divergent,
      sv1
    );
    Y.applyUpdate(server, Y.encodeStateAsUpdate(fullerTab, sv1));

    // Without the clock comparison the stale tail is duplicated, e.g.
    // 'one|two|two|' (the order of the copies depends on the clientIDs).
    expect(fullerTab.getText('source').toString()).toBe('one|two|');
    expect(server.getText('source').toString()).toBe('one|two|');
    expect(lesserTab.getText('source').toString()).toBe('one|two|');
  });

  it("does not flag the doc's own offline-edit overhang", () => {
    const client = new Y.Doc();
    client.getText('source').insert(0, 'synced.');
    const server = new Y.Doc();
    Y.applyUpdate(server, Y.encodeStateAsUpdate(client));
    const serverSV = Y.encodeStateVector(server);

    client.getText('source').insert(7, ' offline'); // legitimate offline work
    expect(hasDivergentHistory(client, serverSV)).toBe(false);
  });
});
