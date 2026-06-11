import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { INotebookCellExecutor, runCell } from '@jupyterlab/notebook';
import { PageConfig, URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';
import { disableSavePlugin } from './disablesave';
import { codemirrorYjsPlugin } from './codemirror-binding/plugin';
import { rtcContentProvider, ynotebook, ychat, rtcGlobalAwarenessPlugin } from './docprovider';
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
export const backupCellExecutorPlugin: JupyterFrontEndPlugin<INotebookCellExecutor> =
  {
    id: '@jupyter-ai-contrib/server-documents:backup-cell-executor',
    description:
      'Provides notebook cell executor; uses server-side execution when enabled.',
    autoStart: false,
    provides: INotebookCellExecutor,
    activate: (app: JupyterFrontEnd): INotebookCellExecutor => {
      if (PageConfig.getOption('serverSideExecution') !== 'true') {
        return Object.freeze({ runCell });
      }

      const serverSettings = app.serviceManager.serverSettings;
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
          // Prefer document_id from the shared model state — this is the Yjs
          // room name set by the WebSocket provider (same key used by
          // jupyter-server-nbmodel).  Falls back to path so the server can
          // resolve it via file_id_manager if document_id is not yet set.
          const documentId = (notebook.sharedModel as any).getState?.('document_id') as string | undefined;
          const path = sessionContext?.session?.path ?? '';

          onCellExecutionScheduled({ cell });
          try {
            const response = await ServerConnection.makeRequest(
              apiURL,
              {
                method: 'POST',
                body: JSON.stringify(
                  documentId
                    ? { cell_id: cellId, document_id: documentId }
                    : { cell_id: cellId, path }
                )
              },
              serverSettings
            );
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
  backupCellExecutorPlugin,
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
