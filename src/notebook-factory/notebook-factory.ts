import {
  CodeCell,
  CodeCellModel,
  ICellModel,
  ICodeCellModel
} from '@jupyterlab/cells';
import { IChangedArgs } from '@jupyterlab/coreutils';
import { Notebook, NotebookPanel } from '@jupyterlab/notebook';
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { requestAPI } from '../handler';
import { ResettableNotebook } from './notebook';

const globalModelDBMutex = createMutex();

/**
 * The class name added to the cell when dirty.
 */
const DIRTY_CLASS = 'jp-mod-dirty';

(CodeCellModel.prototype as any)._onSharedModelChanged = function (
  slot: ISharedCodeCell,
  change: CellChange
) {
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
          // Inserting an output always results in appending it.
          for (const output of outputsChange.insert!) {
            // For compatibility with older ydoc where a plain object,
            // (rather than a Map instance) could be provided.
            // In a future major release the use of Map will be required.
            if ('toJSON' in output) {
              const json = (output as { toJSON: () => any }).toJSON();
              if (json.metadata?.url) {
                // fetch the output from ouputs service
                requestAPI(json.metadata.url).then(data => {
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
    this.stateChanged.emit({
      name: 'executionState',
      oldValue: change.executionStateChange.oldValue,
      newValue: change.executionStateChange.newValue
    });
  }
  if (change.sourceChange && this.executionCount !== null) {
    this._setDirty(this._executedCode !== this.sharedModel.getSource().trim());
  }
};

(CodeCellModel as any).prototype.onOutputsChange = function (
  sender: IOutputAreaModel,
  event: IOutputAreaModel.ChangedArgs
) {
  // no-op
};

/* An OutputAreaModel that loads outputs from outputs service */
class RtcOutputAreaModel extends OutputAreaModel implements IOutputAreaModel {
  constructor(options: IOutputAreaModel.IOptions = {}) {
    super({ ...options, values: [] }); // Don't pass values to OutputAreaModel
    if (options.values?.length) {
      const firstValue = options.values[0];
      if ((firstValue as any).metadata?.url) {
        let outputsUrl = (firstValue as any).metadata.url;
        // Skip the last section with *.output
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
 * NOTE: We should upstream this fix. This is a bug in JupyterLab.
 *
 * The execution count comes back from the kernel immediately
 * when the execute request is made by the client, even thought
 * cell might still be running. JupyterLab holds this value in
 * memory with a Promise to set it later, once the execution
 * state goes back to Idle.
 *
 * In CRDT world, we don't need to do this gymnastics, holding
 * the state in a Promise. Instead, we can just watch the
 * executionState and executionCount in the CRDT being maintained
 * by the server-side model.
 *
 * This is a big win! It means user can close and re-open a
 * notebook while a list of executed cells are queued.
 */
(CodeCell.prototype as any).onStateChanged = function (
  model: ICellModel,
  args: IChangedArgs<any>
): void {
  switch (args.name) {
    case 'executionCount':
      // NOTE: This code should not be here. It's a bandaid
      // fix because executionState and executionCount
      // aren't handled in a single message without CRDT/YNotebook.
      // if (args.newValue !== null) {
      //   // Mark execution state if execution count was set.
      //   this.model.executionState = 'idle';
      // }
      this._updatePrompt();
      break;
    case 'executionState':
      this._updatePrompt();
      break;
    case 'isDirty':
      if ((model as ICodeCellModel).isDirty) {
        this.addClass(DIRTY_CLASS);
      } else {
        this.removeClass(DIRTY_CLASS);
      }
      break;
    default:
      break;
  }
};

CodeCellModel.ContentFactory.prototype.createOutputArea = function (
  options: IOutputAreaModel.IOptions
): IOutputAreaModel {
  return new RtcOutputAreaModel(options);
};

export class RtcNotebookContentFactory
  extends NotebookPanel.ContentFactory
  implements NotebookPanel.IContentFactory
{
  createCodeCell(options: CodeCell.IOptions): CodeCell {
    return new CodeCell(options).initializeState();
  }

  createNotebook(options: Notebook.IOptions): Notebook {
    return new ResettableNotebook(options);
  }
}
