import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import type { ICodeCellModel } from '@jupyterlab/cells';
import { INotebookCellExecutor, runCell } from '@jupyterlab/notebook';
import { PageConfig, URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import { Notification } from '@jupyterlab/apputils';
import { jsdDocumentProviderFactory } from './docprovider';
import { disableSavePlugin } from './disablesave';
import { outputsServicePlugin } from './outputs';
import { murmur2 } from './murmur2';

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
 * Trust a code cell once its execute request is accepted (`accept()`) *and*
 * its previous outputs have been cleared, mirroring the clear-then-trust order
 * of CodeCellModel.clearExecution(). The server's clear arrives over the
 * document WebSocket, independently of the HTTP response; trusting before it
 * lands would re-render the old outputs as trusted and run their scripts.
 * Call before dispatching, so a clear that beats the response isn't missed.
 */
function trustOnceCleared(model: ICodeCellModel): {
  accept: () => void;
  cancel: () => void;
} {
  let cleared = model.outputs.length === 0;
  let accepted = false;
  const update = () => {
    cleared = cleared || model.outputs.length === 0;
    if (cleared && accepted) {
      cancel();
      model.trusted = true;
    }
  };
  const cancel = () => {
    model.outputs.changed.disconnect(update);
  };
  model.outputs.changed.connect(update);
  return {
    accept: () => {
      accepted = true;
      update();
    },
    cancel
  };
}

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
          const sourceHash = String(murmur2(source, 0));

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

          const trust = trustOnceCleared(cell.model as ICodeCellModel);
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
            if (!response.ok) {
              // A source mismatch (409) or any other failure (408, 500, etc.)
              // breaks the chain: the request was never enqueued on the
              // server, so the next run must not reference it as a
              // predecessor.
              lastRequestIdByDoc.delete(docKey);
              trust.cancel();
            }
            if (response.status === 409) {
              // Source mismatch — another user edited the cell after this user
              // pressed Run. Show a visible warning so the user knows to re-run.
              Notification.warning(
                'Cell not executed: the cell source changed while the request was in flight. Please re-run the cell.',
                { autoClose: 5000 }
              );
              onCellExecuted({ cell, success: false });
              return false;
            }
            if (response.ok) {
              // Trust the cell so rich outputs (e.g. widgets) render. Failed
              // requests never get here: granting trust can't be undone, since
              // it also writes `trusted: true` to the shared cell metadata.
              trust.accept();
            }
            onCellExecuted({ cell, success: response.ok });
            return response.ok;
          } catch (error) {
            trust.cancel();
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
  jsdDocumentProviderFactory,
  // not enabled by default
  outputsServicePlugin
];

export default plugins;
