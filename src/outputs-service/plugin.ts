import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import {
  INotebookTracker,
  NotebookActions,
  NotebookPanel
} from '@jupyterlab/notebook';
import { ICodeCellModel, CodeCellModel } from '@jupyterlab/cells';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc';
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
 * Custom handler for shared model changes on a CodeCellModel.
 * Fetches outputs from the outputs service when they have a metadata.url.
 */
function rtcOnSharedModelChanged(
  this: CodeCellModel,
  _slot: ISharedCodeCell,
  change: CellChange
): void {
  const self = this as any;

  if (change.streamOutputChange) {
    globalModelDBMutex(() => {
      for (const streamOutputChange of change.streamOutputChange!) {
        if ('delete' in streamOutputChange) {
          self._outputs.removeStreamOutput(streamOutputChange.delete!);
        }
        if ('insert' in streamOutputChange) {
          self._outputs.appendStreamOutput(
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
            self._outputs.remove(retain);
          }
        }
        if ('insert' in outputsChange) {
          for (const output of outputsChange.insert!) {
            if ('toJSON' in output) {
              const json = (output as { toJSON: () => any }).toJSON();
              if (json.metadata?.url) {
                requestAPI(json.metadata.url).then(data => {
                  self._outputs.add(data);
                });
              } else {
                self._outputs.add(json);
              }
            } else {
              self._outputs.add(output);
            }
          }
        }
      }
    });
  }

  if (change.executionCountChange) {
    if (
      change.executionCountChange.newValue &&
      (self.isDirty || !change.executionCountChange.oldValue)
    ) {
      self._setDirty(false);
    }
    self.stateChanged.emit({
      name: 'executionCount',
      oldValue: change.executionCountChange.oldValue,
      newValue: change.executionCountChange.newValue
    });
  }

  if (change.sourceChange && self.executionCount !== null) {
    self._setDirty(self._executedCode !== self.sharedModel.getSource().trim());
  }
}

/**
 * Patch a single CodeCellModel to use the outputs service.
 * - Replaces the output area with RtcOutputAreaModel
 * - Disconnects default shared model handler, connects ours
 * - Disconnects onOutputsChange to prevent write-back to YDoc
 */
function patchCodeCellModel(cell: ICodeCellModel): void {
  const model = cell as any;

  // Disconnect default handlers
  model.sharedModel.changed.disconnect(model._onSharedModelChanged, model);
  model._outputs.changed.disconnect(model.onOutputsChange, model);

  // Replace output area with RtcOutputAreaModel
  const oldOutputs = model._outputs;
  model._outputs = new RtcOutputAreaModel({
    trusted: model.trusted,
    values: model.sharedModel.getOutputs()
  });
  oldOutputs.changed.disconnect(model.onGenericChange, model);
  oldOutputs.dispose();

  // Connect our custom shared model handler
  model.sharedModel.changed.connect(rtcOnSharedModelChanged, model);

  // Connect generic change to new outputs (drives dirty state, etc.)
  model._outputs.changed.connect(model.onGenericChange, model);
}

/**
 * Patch all code cells in a notebook model.
 */
function patchNotebookPanel(panel: NotebookPanel): void {
  const model = panel.content.model;
  if (!model) {
    return;
  }

  // Patch existing cells
  for (const cell of model.cells) {
    if (cell.type === 'code') {
      patchCodeCellModel(cell as ICodeCellModel);
    }
  }

  // Patch cells added later (insert, paste, split, etc.)
  model.cells.changed.connect((_sender, args) => {
    if (args.type === 'add') {
      for (const cell of args.newValues) {
        if (cell.type === 'code') {
          patchCodeCellModel(cell as ICodeCellModel);
        }
      }
    }
  });
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
 * When disabled (autoStart: false by default), outputs live directly in the YDoc.
 *
 * NOTE: The outputs service on the server must be enabled via the
 * `--OutputProcessor.use_outputs_service=True` trait to use this plugin.
 */
export const outputsServicePlugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter-ai-contrib/server-documents:outputs-service',
  description: 'Routes notebook outputs through disk-backed REST service.',
  autoStart: false,
  requires: [INotebookTracker],
  activate: (app: JupyterFrontEnd, tracker: INotebookTracker) => {
    console.log('Outputs service plugin activated.');

    tracker.widgetAdded.connect((_sender, panel: NotebookPanel) => {
      panel.revealed.then(() => {
        patchNotebookPanel(panel);
      });
    });

    NotebookActions.outputCleared.connect(handleOutputCleared);
  }
};
