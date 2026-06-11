import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { INotebookTracker, NotebookActions } from '@jupyterlab/notebook';
import { CodeCellModel } from '@jupyterlab/cells';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc';
import { PageConfig } from '@jupyterlab/coreutils';
import { requestAPI } from '../handler';

const globalModelDBMutex = createMutex();

/**
 * An OutputAreaModel that loads outputs from the outputs service on construction.
 */
class RtcOutputAreaModel extends OutputAreaModel implements IOutputAreaModel {
  constructor(options: IOutputAreaModel.IOptions = {}) {
    super({ ...options, values: [] });
    if (options.values?.length) {
      const firstValue = options.values[0];
      if ((firstValue as any).metadata?.url) {
        let outputsUrl = (firstValue as any).metadata.url;
        outputsUrl = outputsUrl.substring(0, outputsUrl.lastIndexOf('/'));
        requestAPI(outputsUrl)
          .then(outputs => {
            (outputs as any).forEach((output: any) => {
              if (!(this as any).isDisposed) {
                const index = (this as any)._add(output) - 1;
                const item = (this as any).list.get(index);
                item.changed.connect((this as any)._onGenericChange, this);
              }
            });
          })
          .catch(error => {
            console.error('Error fetching output:', error);
          });
      } else {
        options.values.forEach((output: any) => {
          if (!(this as any).isDisposed) {
            const index = (this as any)._add(output) - 1;
            const item = (this as any).list.get(index);
            item.changed.connect((this as any)._onGenericChange, this);
          }
        });
      }
    }
  }
}

/**
 * Patch CodeCellModel at the prototype level so all instances use the outputs service.
 * - Overrides _onSharedModelChanged to fetch outputs from URLs
 * - No-ops onOutputsChange to prevent write-back to YDoc
 * - Overrides createOutputArea to use RtcOutputAreaModel
 */
function patchCodeCellModelClass(): void {
  (CodeCellModel.prototype as any)._onSharedModelChanged = function (
    _slot: ISharedCodeCell,
    change: CellChange
  ): void {
    if (change.streamOutputChange) {
      globalModelDBMutex(() => {
        for (const streamOutputChange of change.streamOutputChange!) {
          if ('delete' in streamOutputChange) {
            this._outputs.removeStreamOutput(streamOutputChange.delete!);
          }
          if ('insert' in streamOutputChange) {
            this._outputs.appendStreamOutput(
              streamOutputChange.insert!.toString()
            );
          }
        }
      });
    }

    if (change.outputsChange) {
      globalModelDBMutex(() => {
        let retain = 0;
        for (const outputsChange of change.outputsChange!) {
          if ('retain' in outputsChange) {
            retain += outputsChange.retain!;
          }
          if ('delete' in outputsChange) {
            for (let i = 0; i < outputsChange.delete!; i++) {
              this._outputs.remove(retain);
            }
          }
          if ('insert' in outputsChange) {
            for (const output of outputsChange.insert!) {
              if ('toJSON' in output) {
                const json = (output as { toJSON: () => any }).toJSON();
                if (json.metadata?.url) {
                  requestAPI(json.metadata.url).then((data: any) => {
                    this._outputs.add(data);
                  });
                } else {
                  this._outputs.add(json);
                }
              } else {
                this._outputs.add(output);
              }
            }
          }
        }
      });
    }

    if (change.executionCountChange) {
      if (
        change.executionCountChange.newValue &&
        (this.isDirty || !change.executionCountChange.oldValue)
      ) {
        this._setDirty(false);
      }
      this.stateChanged.emit({
        name: 'executionCount',
        oldValue: change.executionCountChange.oldValue,
        newValue: change.executionCountChange.newValue
      });
    }

    if (change.executionStateChange) {
      if (change.executionStateChange.newValue === 'running') {
        this._setDirty(false);
      }
      this.stateChanged.emit({
        name: 'executionState',
        oldValue: change.executionStateChange.oldValue,
        newValue: change.executionStateChange.newValue
      });
    }

    if (change.sourceChange && this.executionCount !== null) {
      this._setDirty(
        this._executedCode !== this.sharedModel.getSource().trim()
      );
    }
  };

  (CodeCellModel.prototype as any).onOutputsChange = function () {
    // no-op: prevent output area changes from writing back to YDoc
  };

  CodeCellModel.ContentFactory.prototype.createOutputArea = function (
    options: IOutputAreaModel.IOptions
  ): IOutputAreaModel {
    return new RtcOutputAreaModel(options);
  };
}

/**
 * Handle the "Clear Outputs" action: clear YDoc and disk.
 */
function handleOutputCleared(
  _sender: typeof NotebookActions,
  args: { notebook: any; cell: any }
): void {
  const { notebook, cell } = args;
  const cellId = cell.model.sharedModel.getId();
  const awareness = notebook.model?.sharedModel.awareness;
  const awarenessStates = awareness?.getStates();

  // Clear outputs in YDoc for immediate real-time sync
  try {
    const sharedCodeCell = cell.model.sharedModel as ISharedCodeCell;
    sharedCodeCell.setOutputs([]);
  } catch (error: unknown) {
    console.error('Error clearing YDoc outputs:', error);
  }

  if (awarenessStates?.size === 0) {
    return;
  }

  let fileId = null;
  for (const [_, state] of awarenessStates || []) {
    if (state && 'file_id' in state) {
      fileId = state['file_id'];
    }
  }

  if (fileId === null) {
    return;
  }

  // Clear outputs from disk storage
  requestAPI(`/api/outputs/${fileId}/${cellId}`, { method: 'DELETE' }).catch(
    (error: Error) => {
      console.error(
        `Failed to clear outputs from disk for cell ${cellId}:`,
        error
      );
    }
  );
}

/**
 * Plugin that routes notebook outputs through the disk-backed REST service.
 *
 * This plugin is always loaded (autoStart: true) but only activates its
 * behavior when the server has enabled the outputs service via the
 * `c.OutputProcessor.use_outputs_service = True` trait. The server injects
 * this setting into page_config_data, which the plugin reads at activation.
 *
 * When disabled, outputs live directly in the YDoc and .ipynb file.
 */
export const outputsServicePlugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter-ai-contrib/server-documents:outputs-service',
  description: 'Routes notebook outputs through disk-backed REST service.',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (app: JupyterFrontEnd, tracker: INotebookTracker) => {
    const enabled = PageConfig.getOption('outputsServiceEnabled') === 'true';
    if (!enabled) {
      return;
    }

    console.log('Outputs service plugin activated.');

    patchCodeCellModelClass();
    NotebookActions.outputCleared.connect(handleOutputCleared);
  }
};
