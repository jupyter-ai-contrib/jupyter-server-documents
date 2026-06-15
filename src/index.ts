import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { INotebookCellExecutor, runCell } from '@jupyterlab/notebook';
import { PageConfig, URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

// Most of the implementation below is adapted from the following repository:
// https://github.com/garycourt/murmurhash-js/blob/master/murmurhash2_gc.js
// Which has the following MIT License:
//
// Copyright (c) 2011 Gary Court
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
const _murmur2Encoder = new TextEncoder();
function _murmur2(str: string, seed: number): number {
  const m = 0x5bd1e995;
  const data = _murmur2Encoder.encode(str);
  let len = data.length;
  let h = seed ^ len;
  let i = 0;
  while (len >= 4) {
    let k =
      (data[i] & 0xff) |
      ((data[++i] & 0xff) << 8) |
      ((data[++i] & 0xff) << 16) |
      ((data[++i] & 0xff) << 24);
    k = (k & 0xffff) * m + ((((k >>> 16) * m) & 0xffff) << 16);
    k ^= k >>> 24;
    k = (k & 0xffff) * m + ((((k >>> 16) * m) & 0xffff) << 16);
    h = ((h & 0xffff) * m + ((((h >>> 16) * m) & 0xffff) << 16)) ^ k;
    len -= 4;
    ++i;
  }
  switch (len) {
    case 3:
      h ^= (data[i + 2] & 0xff) << 16;
    // eslint-disable-next-line no-fallthrough
    case 2:
      h ^= (data[i + 1] & 0xff) << 8;
    // eslint-disable-next-line no-fallthrough
    case 1:
      h ^= data[i] & 0xff;
      h = (h & 0xffff) * m + ((((h >>> 16) * m) & 0xffff) << 16);
  }
  h ^= h >>> 13;
  h = (h & 0xffff) * m + ((((h >>> 16) * m) & 0xffff) << 16);
  h ^= h >>> 15;
  return h >>> 0;
}
import { disableSavePlugin } from './disablesave';
import { codemirrorYjsPlugin } from './codemirror-binding/plugin';
import {
  rtcContentProvider,
  ynotebook,
  ychat,
  rtcGlobalAwarenessPlugin
} from './docprovider';
import { outputsServicePlugin } from './outputs';

/**
 * Initialization data for the @jupyter-ai-contrib/server-documents extension.
 */
export const plugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter-ai-contrib/server-documents:plugin',
  description: 'A JupyterLab extension that provides RTC capabilities.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log(
      'JupyterLab extension @jupyter-ai-contrib/server-documents is activated!'
    );

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log(
            '@jupyter-ai-contrib/server-documents settings loaded:',
            settings.composite
          );
        })
        .catch(reason => {
          console.error(
            'Failed to load settings for @jupyter-ai-contrib/server-documents.',
            reason
          );
        });
    }
  }
};

/**
 * Notebook cell executor plugin.
 *
 * When serverSideExecution is enabled (set by the Python extension), runs
 * cells via POST /api/kernels/{id}/execute so outputs route through the
 * server-side YDoc rather than coming back over the kernel WebSocket.
 *
 * Falls back to the default WebSocket-based runCell when the flag is not set.
 * autoStart: false means this only activates when no other implementation
 * of INotebookCellExecutor has been provided.
 */
export const serverCellExecutorPlugin: JupyterFrontEndPlugin<INotebookCellExecutor> =
  {
    id: '@jupyter-ai-contrib/server-documents:server-cell-executor',
    description:
      'Provides notebook cell executor; uses server-side execution when enabled.',
    autoStart: false,
    provides: INotebookCellExecutor,
    activate: (app: JupyterFrontEnd): INotebookCellExecutor => {
      if (PageConfig.getOption('serverSideExecution') !== 'true') {
        return Object.freeze({ runCell });
      }

      const serverSettings = app.serviceManager.serverSettings;
      // Track the last request_id per document so successive runCell calls
      // can chain previous_request_id without touching any notebook internals.
      const lastRequestIdByDoc = new Map<string, string>();
      return {
        async runCell({
          cell,
          notebook,
          onCellExecuted,
          onCellExecutionScheduled,
          sessionContext,
          sessionDialogs,
          translator
        }) {
          if (cell.model.type !== 'code') {
            if (cell.model.type === 'markdown') {
              (cell as any).rendered = true;
              cell.inputHidden = false;
            }
            onCellExecuted({ cell, success: true });
            return true;
          }

          if (!sessionContext) {
            return true;
          }

          if (sessionContext.hasNoKernel) {
            const shouldSelect = await sessionContext.startKernel();
            if (shouldSelect && sessionDialogs) {
              await sessionDialogs.selectKernel(sessionContext);
            }
          }

          if (sessionContext.hasNoKernel) {
            return true;
          }

          const kernelId = sessionContext?.session?.kernel?.id;
          const apiURL = URLExt.join(
            serverSettings.baseUrl,
            `api/kernels/${kernelId}/execute`
          );
          const cellId = cell.model.sharedModel.getId();
          // Prefer document_id from the shared model state — this is the
          // room name set by the WebSocket provider (same key used by
          // jupyter-server-nbmodel).  Falls back to path so the server can
          // resolve it via file_id_manager if document_id is not yet set.
          const documentId = notebook.sharedModel.getState('document_id') as
            | string
            | undefined;
          const path = sessionContext?.session?.path ?? '';

          // Compute MurmurHash2 of the cell source so the server can detect
          // if another user's edit arrived after this user pressed Run.
          // Uses seed 0 to match the hash format sent to the server.
          // MurmurHash2 is synchronous and works in non-secure (HTTP) contexts,
          // consistent with its use in @jupyterlab/debugger.
          const source = cell.model.sharedModel.getSource();
          const sourceHash = String(_murmur2(source, 0));

          // Include the client ID so the server can attribute who executed
          // the cell and scope the ordering chain per-client.  Each browser tab
          // gets a unique client ID from the collaborative drive's awareness.
          const clientId = String(
            notebook.sharedModel.awareness?.clientID ?? ''
          );

          // Generate a unique ID for this request and chain it to the
          // previous one so the server can enforce FIFO order even when
          // network jitter causes requests to arrive out of sequence.
          // The chain is keyed per document+client so that two users running
          // cells simultaneously don't block each other.
          const docKey = `${documentId ?? path}:${clientId}`;
          const requestId = crypto.randomUUID();
          const previousRequestId = lastRequestIdByDoc.get(docKey);
          lastRequestIdByDoc.set(docKey, requestId);

          if (!documentId) {
            // document_id not yet in shared model state — fall back to path.
            // The server resolves it via file_id_manager.
            console.warn('[JSD] document_id not set; falling back to path');
          }

          onCellExecutionScheduled({ cell });
          try {
            const response = await ServerConnection.makeRequest(
              apiURL,
              {
                method: 'POST',
                body: JSON.stringify({
                  document_id: documentId ?? path,
                  cells: [{ cell_id: cellId, source_hash: sourceHash }],
                  client_id: clientId || undefined,
                  request_id: requestId,
                  ...(previousRequestId
                    ? { previous_request_id: previousRequestId }
                    : {})
                })
              },
              serverSettings
            );
            if (response.status === 409) {
              // Source mismatch — another user edited the cell after this user
              // pressed Run.  Treat as a soft failure: clear the running state
              // and report to the user without throwing.
              console.warn(
                `[JSD] Cell ${cellId} not executed: source changed since Run was pressed`
              );
              onCellExecuted({ cell, success: false });
              return false;
            }
            onCellExecuted({ cell, success: response.ok });
            return response.ok;
          } catch (error) {
            onCellExecuted({ cell, success: false });
            if (!cell.isDisposed) {
              throw error;
            }
            return false;
          }
        }
      };
    }
  };

const plugins: JupyterFrontEndPlugin<unknown>[] = [
  plugin,
  serverCellExecutorPlugin,
  disableSavePlugin,
  codemirrorYjsPlugin,
  // Provide our own collaborative content provider so notebooks connect to
  // our YRoom WebSocket directly, without requiring jupyter-collaboration's
  // Python server extension or its contentProviderRegistry machinery.
  rtcContentProvider,
  ynotebook,
  ychat,
  // Override jupyter-collaboration's global awareness to ensure it connects
  // to our own backend. See #249 and dlqqq's review comment on #248.
  rtcGlobalAwarenessPlugin,
  outputsServicePlugin
];

export default plugins;
