// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.

import { Notification } from '@jupyterlab/apputils';
import { PageConfig } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import { Signal } from '@lumino/signaling';

// The executor is the only plugin under test here. Its sibling plugins pull
// in ESM-only dependencies that this repository's Jest transform does not
// cover, so stub them out rather than loading the whole extension.
jest.mock('../docprovider', () => ({ jsdDocumentProviderFactory: {} }));
jest.mock('../disablesave', () => ({ disableSavePlugin: {} }));
jest.mock('../outputs', () => ({ outputsServicePlugin: {} }));

import { serverCellExecutorPlugin } from '../index';

/**
 * Tests for the trust granted by the server-side cell executor.
 *
 * The server-side path bypasses `CodeCellModel.clearExecution()`, which is
 * where the default executor marks a user-executed cell trusted. This
 * executor grants that trust itself, so it must grant it *only* once the
 * server has accepted the request: the method has several paths that execute
 * nothing, and it never clears the cell's outputs, so trusting on those paths
 * would retroactively trust output loaded from an untrusted notebook.
 *
 * A grant can't be taken back either. `CodeCellModel` writes `trusted: true`
 * into the shared cell metadata when trust is granted and leaves it there when
 * the flag is reset, so the tests assert that failure paths never write the
 * flag at all, rather than that it ends up false.
 *
 * The server clears a cell's previous outputs, but that clear reaches the
 * client over the document WebSocket, independently of the HTTP response.
 * Trust must wait for it, or the old outputs re-render as trusted.
 */

function makeCell(
  options: { type?: string; trusted?: boolean; outputs?: number } = {}
): any {
  let trusted = options.trusted ?? false;
  const trustWrites: boolean[] = [];
  const outputs: any = { length: options.outputs ?? 0 };
  outputs.changed = new Signal<any, void>(outputs);
  return {
    trustWrites,
    /** Simulate the server's clear arriving over the document WebSocket. */
    clearOutputs: () => {
      outputs.length = 0;
      outputs.changed.emit();
    },
    /** Simulate a new output from this run arriving. */
    addOutput: () => {
      outputs.length += 1;
      outputs.changed.emit();
    },
    model: {
      type: options.type ?? 'code',
      outputs,
      get trusted() {
        return trusted;
      },
      set trusted(value: boolean) {
        trustWrites.push(value);
        trusted = value;
      },
      sharedModel: {
        getId: () => 'cell-1',
        getSource: () => 'print(1)'
      }
    },
    isDisposed: false,
    inputHidden: false
  };
}

const notebook: any = {
  sharedModel: {
    getState: () => 'json:notebook:file-1',
    awareness: { clientID: 7 }
  }
};

/** A session context with a live kernel, so `runCell` reaches dispatch. */
function liveSessionContext(): any {
  return {
    hasNoKernel: false,
    session: { kernel: { id: 'kernel-1' }, path: 'notebook.ipynb' }
  };
}

function makeExecutor(): any {
  const app: any = {
    serviceManager: { serverSettings: ServerConnection.makeSettings() }
  };
  return serverCellExecutorPlugin.activate(app);
}

function makeCallbacks() {
  return {
    onCellExecuted: jest.fn(),
    onCellExecutionScheduled: jest.fn()
  };
}

describe('serverCellExecutorPlugin runCell trust', () => {
  let requestSpy: jest.SpyInstance;

  beforeAll(() => {
    PageConfig.setOption('serverSideExecution', 'true');
    // `crypto.randomUUID` is used to build the request ID; jsdom may not
    // provide it.
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => 'request-1' },
      configurable: true,
      writable: true
    });
  });

  beforeEach(() => {
    requestSpy = jest.spyOn(ServerConnection, 'makeRequest');
    jest.spyOn(Notification, 'warning').mockImplementation(() => '');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('grants trust once the server accepts the request', async () => {
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();
    let trustedWhileInFlight: boolean | undefined;
    requestSpy.mockImplementation(async () => {
      trustedWhileInFlight = cell.model.trusted;
      return { ok: true, status: 200 } as any;
    });

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(result).toBe(true);
    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(trustedWhileInFlight).toBe(false);
    expect(cell.trustWrites).toEqual([true]);
  });

  it('waits for previous outputs to be cleared before granting trust', async () => {
    requestSpy.mockResolvedValue({ ok: true, status: 200 } as any);
    const executor = makeExecutor();
    // Outputs loaded with the notebook, which may be untrusted.
    const cell = makeCell({ outputs: 1 });
    const callbacks = makeCallbacks();

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    // The response arrived before the server's clear did: trusting now would
    // re-render the old outputs as trusted.
    expect(result).toBe(true);
    expect(cell.trustWrites).toEqual([]);

    cell.clearOutputs();
    expect(cell.trustWrites).toEqual([true]);

    // New outputs don't trigger another grant.
    cell.addOutput();
    expect(cell.trustWrites).toEqual([true]);
  });

  it('grants trust on the response when the clear arrived first', async () => {
    const executor = makeExecutor();
    const cell = makeCell({ outputs: 2 });
    const callbacks = makeCallbacks();
    // The clear, and then the run's first new output, both beat the response.
    requestSpy.mockImplementation(async () => {
      cell.clearOutputs();
      cell.addOutput();
      return { ok: true, status: 200 } as any;
    });

    await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(cell.trustWrites).toEqual([true]);
  });

  it('does not grant trust when a failed request is followed by a clear', async () => {
    requestSpy.mockResolvedValue({ ok: false, status: 409 } as any);
    const executor = makeExecutor();
    const cell = makeCell({ outputs: 1 });
    const callbacks = makeCallbacks();

    await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });
    // e.g. the user clears the outputs by hand afterwards.
    cell.clearOutputs();

    expect(cell.trustWrites).toEqual([]);
  });

  it('does not grant trust when there is no session context', async () => {
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: undefined,
      ...callbacks
    });

    expect(result).toBe(true);
    // Nothing was dispatched, so nothing may be trusted.
    expect(cell.trustWrites).toEqual([]);
    expect(requestSpy).not.toHaveBeenCalled();
    expect(callbacks.onCellExecutionScheduled).not.toHaveBeenCalled();
  });

  it('does not grant trust when no kernel is available after starting one', async () => {
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();
    // The user declines the kernel selection, so `hasNoKernel` stays true.
    const sessionContext: any = {
      hasNoKernel: true,
      startKernel: jest.fn().mockResolvedValue(false)
    };

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext,
      ...callbacks
    });

    expect(result).toBe(true);
    expect(sessionContext.startKernel).toHaveBeenCalled();
    expect(cell.trustWrites).toEqual([]);
    expect(requestSpy).not.toHaveBeenCalled();
    expect(callbacks.onCellExecutionScheduled).not.toHaveBeenCalled();
  });

  it('does not grant trust when the source hash is rejected', async () => {
    requestSpy.mockResolvedValue({ ok: false, status: 409 } as any);
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(result).toBe(false);
    expect(cell.trustWrites).toEqual([]);
  });

  it('does not grant trust when the request fails', async () => {
    requestSpy.mockResolvedValue({ ok: false, status: 500 } as any);
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(result).toBe(false);
    expect(cell.trustWrites).toEqual([]);
  });

  it('does not grant trust when the request throws', async () => {
    requestSpy.mockRejectedValue(new Error('network down'));
    const executor = makeExecutor();
    const cell = makeCell();
    const callbacks = makeCallbacks();

    await expect(
      executor.runCell({
        cell,
        notebook,
        sessionContext: liveSessionContext(),
        ...callbacks
      })
    ).rejects.toThrow('network down');

    expect(cell.trustWrites).toEqual([]);
  });

  it('leaves an already-trusted cell trusted when the request fails', async () => {
    requestSpy.mockResolvedValue({ ok: false, status: 500 } as any);
    const executor = makeExecutor();
    // A cell from a trusted notebook must not be *downgraded* by a failure.
    const cell = makeCell({ trusted: true });
    const callbacks = makeCallbacks();

    await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(cell.model.trusted).toBe(true);
  });

  it('does not grant trust to a markdown cell', async () => {
    const executor = makeExecutor();
    const cell = makeCell({ type: 'markdown' });
    const callbacks = makeCallbacks();

    const result = await executor.runCell({
      cell,
      notebook,
      sessionContext: liveSessionContext(),
      ...callbacks
    });

    expect(result).toBe(true);
    expect(cell.trustWrites).toEqual([]);
    expect(requestSpy).not.toHaveBeenCalled();
  });
});
