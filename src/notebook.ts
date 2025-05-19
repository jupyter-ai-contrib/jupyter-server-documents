import { CodeCell, CodeCellModel } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { IOutputModel } from '@jupyterlab/rendermime';
import { requestAPI } from './handler';

import { ObservableList } from '@jupyterlab/observables';

const globalModelDBMutex = createMutex();

// @ts-ignore
CodeCellModel.prototype._onSharedModelChanged = function (
  slot: ISharedCodeCell,
  change: CellChange
) {
  if (change.streamOutputChange) {
    globalModelDBMutex(() => {
      for (const streamOutputChange of change.streamOutputChange!) {
        if ('delete' in streamOutputChange) {
          // @ts-ignore
          this._outputs.removeStreamOutput(streamOutputChange.delete!);
        }
        if ('insert' in streamOutputChange) {
          // @ts-ignore
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
            // @ts-ignore
            this._outputs.remove(retain);
          }
        }
        if ('insert' in outputsChange) {
          // Inserting an output always results in appending it.
          for (const output of outputsChange.insert!) {
            // For compatibility with older ydoc where a plain object,
            // (rather than a Map instance) could be provided.
            // In a future major release the use of Map will be required.
            //@ts-ignore
            if ('toJSON' in output) {
              // @ts-ignore
              const parsed = output.toJSON();
              const metadata = parsed.metadata;
              if (metadata && metadata.url) {
                // fetch the real output
                requestAPI(metadata.url).then(data => {
                  // @ts-ignore
                  this._outputs.add(data);
                });
              } else {
                // @ts-ignore
                this._outputs.add(parsed);
              }
            } else {
              console.debug('output from doc: ', output);
              // @ts-ignore
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
      // @ts-ignore
      (this.isDirty || !change.executionCountChange.oldValue)
    ) {
      // @ts-ignore
      this._setDirty(false);
    }
    // @ts-ignore
    this.stateChanged.emit({
      name: 'executionCount',
      oldValue: change.executionCountChange.oldValue,
      newValue: change.executionCountChange.newValue
    });
  }

  if (change.executionStateChange) {
    // @ts-ignore
    this.stateChanged.emit({
      name: 'executionState',
      oldValue: change.executionStateChange.oldValue,
      newValue: change.executionStateChange.newValue
    });
  }
  // @ts-ignore
  if (change.sourceChange && this.executionCount !== null) {
    // @ts-ignore
    this._setDirty(this._executedCode !== this.sharedModel.getSource().trim());
  }
};

// @ts-ignore
CodeCellModel.prototype.onOutputsChange = function (
  sender: IOutputAreaModel,
  event: IOutputAreaModel.ChangedArgs
) {
  console.debug('Inside onOutputsChange, called with event: ', event);
};

/* A new OutputAreaModel that loads outputs from outputs service */
class RtcOutputAreaModel extends OutputAreaModel implements IOutputAreaModel {
  constructor(options: IOutputAreaModel.IOptions = {}) {
    super({ ...options, values: [] });
    // @ts-ignore
    this._trusted = !!options.trusted;
    // @ts-ignore
    this.contentFactory =
      options.contentFactory || OutputAreaModel.defaultContentFactory;
    this.list = new ObservableList<IOutputModel>();
    // @ts-ignore
    this.list.changed.connect(this._onListChanged, this);
    if (options.values) {
      // Create an array to store promises for each value
      const valuePromises = options.values.map((value, index) => {
        console.debug('output #${index}, value: ${value}');
        // @ts-ignore
        if (value.metadata?.url) {
          // @ts-ignore
          return requestAPI(value.metadata.url)
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
          if (data && !this.isDisposed) {
            // @ts-ignore
            const index = this._add(data) - 1;
            const item = this.list.get(index);
            // @ts-ignore
            item.changed.connect(this._onGenericChange, this);
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

export class YNotebookContentFactory
  extends NotebookPanel.ContentFactory
  implements NotebookPanel.IContentFactory
{
  createCodeCell(options: CodeCell.IOptions): CodeCell {
    return new CodeCell(options).initializeState();
  }
}
