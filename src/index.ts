import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
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
      // Sequence-based ordering: per (document, client, kernel) monotonic
      // counter. The server enqueues in sequence order; out-of-order
      // arrivals are buffered until their predecessors show up. Reset to
      // 0 signals a session reset to the server.
      const nextSeqByDoc = new Map<string, number>();

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

          // sessionContext.hasNoKernel can flip to false the moment a
          // Kernel object exists, before the server has assigned it an
          // id. Await ``sessionContext.ready`` (resolves once the
          // session + kernel are fully connected) and re-check the
          // kernel id — otherwise we POST to
          // ``/api/kernels/undefined/execute`` and the server rejects
          // with "YNotebookRoom is not connected to a kernel".
          await sessionContext.ready;
          const kernelId = sessionContext?.session?.kernel?.id;
          if (!kernelId) {
            onCellExecuted({ cell, success: false });
            return false;
          }

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

          // Generate a unique ID for this request (opaque, for tracing)
          // and attach a monotonic sequence number so the server enqueues
          // requests in strict order per (document, client, kernel)
          // regardless of arrival timing. The counter is keyed by
          // kernel_id as well so that when the kernel changes, the
          // counter naturally resets to 0 for the new kernel — matching
          // the server's per-disconnect _next_seq clear.
          const docKey = `${documentId ?? path}:${clientId}:${kernelId}`;
          const requestId = crypto.randomUUID();
          const sequence = nextSeqByDoc.get(docKey) ?? 0;
          nextSeqByDoc.set(docKey, sequence + 1);

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
                  sequence
                })
              },
              serverSettings
            );
            if (response.status === 409) {
              // Two distinct 409 shapes:
              //   { error: "source_mismatch", cell_id: ... } — the source
              //     changed under us; the server advanced the sequence
              //     slot regardless, so our counter is still in sync.
              //   { error: "session_reset" } — the server rewound state
              //     (kernel disconnect or an explicit seq=0 from us);
              //     reset our counter so the next request starts fresh.
              let body: { error?: string } = {};
              try {
                body = await response.json();
              } catch {
                // fall through with empty body
              }
              if (body.error === 'session_reset') {
                nextSeqByDoc.delete(docKey);
                Notification.warning(
                  'Cell not executed: the kernel changed while the request was in flight. Please re-run the cell.',
                  { autoClose: 5000 }
                );
                onCellExecuted({ cell, success: false });
                return false;
              }
              Notification.warning(
                'Cell not executed: the cell source changed while the request was in flight. Please re-run the cell.',
                { autoClose: 5000 }
              );
              onCellExecuted({ cell, success: false });
              return false;
            }
            if (!response.ok) {
              // 4xx/5xx other than 409 — conservatively reset the counter
              // so we don't wedge on a sequence the server may not have
              // observed.
              nextSeqByDoc.delete(docKey);
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
  jsdDocumentProviderFactory,
  // not enabled by default
  outputsServicePlugin
];

export default plugins;
