import { CodeCell, CodeCellModel } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { requestAPI } from './handler';

const globalModelDBMutex = createMutex();

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
    if (options.values) {
      // Create an array to store promises for each value
      const valuePromises = options.values.map(value => {
        console.debug('output #${index}, value: ${value}');
        if ((value as any).metadata?.url) {
          return requestAPI((value as any).metadata.url)
            .then(data => {
              return data;
            })
            .catch(error => {
              console.error('Error fetching output:', error);
              return null;
            });
        } else {
          // For values without url, return immediately with original value
          return Promise.resolve(value);
        }
      });

      // Wait for all promises to resolve and add values in original order
      Promise.all(valuePromises).then(results => {
        console.log('After fetching from outputs service:');
        // Add each value in order
        results.forEach((data, index) => {
          console.debug('output #${index}, data: ${data}');
          if (data && !(this as any).isDisposed) {
            const index = (this as any)._add(data) - 1;
            const item = (this as any).list.get(index);
            item.changed.connect((this as any)._onGenericChange, this);
          }
        });
      });
    }
  }
}

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
}
