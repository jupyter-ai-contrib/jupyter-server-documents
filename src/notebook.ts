// @ts-nocheck
import {
  Cell,
  CodeCell,
  CellModel,
  CodeCellModel,
  MarkdownCellModel,
  RawCellModel
} from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import { KernelMessage } from '@jupyterlab/services';
import {
  CellChange,
  createMutex,
  ISharedCodeCell,
  ISharedMarkdownCell,
  ISharedRawCell,
  YCodeCell
} from '@jupyter/ydoc';
import { IOutputAreaModel, OutputAreaModel } from '@jupyterlab/outputarea';
import { requestAPI } from './handler';
import { CellList } from '@jupyterlab/notebook';
/*import {
  ISharedNotebook
} from '@jupyter/ydoc';*/

import {
  IObservableList,
  ObservableList
} from '@jupyterlab/observables';

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
  return
  // @ts-ignore
  const codeCell = this.sharedModel as YCodeCell;
  globalModelDBMutex(() => {
    if (event.type == 'remove') {
      codeCell.updateOutputs(event.oldIndex, event.oldValues.length, []);
    }
  });
};

// @ts-ignore
/*CellList.prototype.updateCodeCellOutputs = function(sharedModel: ISharedCodeCell): Promise<void> {
    const outputs = sharedModel.getOutputs();
    // @ts-ignore
    const updatePromises = [];

    outputs.forEach((output, index) => {
        // @ts-ignore
        if (output.metadata && output.metadata.url) {
            // @ts-ignore
            const promise = requestAPI(output.metadata.url).then(data => {
                (sharedModel as YCodeCell).updateOutputs(
                    index,
                    index + 1,
                    // @ts-ignore
                    [data],
                    'silent-change'
                );
                // @ts-ignore
                promise.resolve(sharedModel)
            }).catch(error => {
                console.error('Error fetching output:', error);
            });
            updatePromises.push(promise);
        }
    });

    // @ts-ignore
    return Promise.all(updatePromises);
}

// @ts-ignore
CellList.prototype._insertCells = function(index: number, cells: Array<ISharedCell>) {
    const cellPromises = cells.map(sharedModel => {
        return new Promise<void>((resolve) => {
            if (sharedModel.cell_type === 'code') {
                // For code cells, update outputs first
                // @ts-ignore
                this.updateCodeCellOutputs(sharedModel as ISharedCodeCell)
                    .then((sharedModel: ISharedCodeCell) => {
                        let cellModel = new CodeCellModel({
                            sharedModel: sharedModel as ISharedCodeCell
                        });
                        // @ts-ignore
                        this._cellMap.set(sharedModel, cellModel);
                        sharedModel.disposed.connect(() => {
                            cellModel.dispose();
                            // @ts-ignore
                            this._cellMap.delete(sharedModel);
                        });
                        resolve();
                    }).catch(() => {
                        let cellModel = new CodeCellModel({
                            sharedModel: sharedModel as ISharedCodeCell
                        });
                        // @ts-ignore
                        this._cellMap.set(sharedModel, cellModel);
                        sharedModel.disposed.connect(() => {
                            cellModel.dispose();
                            // @ts-ignore
                            this._cellMap.delete(sharedModel);
                        });
                    });
            } else {
                // For non-code cells, create model directly
                let cellModel: CellModel;
                if (sharedModel.cell_type === 'markdown') {
                    cellModel = new MarkdownCellModel({
                        sharedModel: sharedModel as ISharedMarkdownCell
                    });
                } else {
                    cellModel = new RawCellModel({
                        sharedModel: sharedModel as ISharedRawCell
                    });
                }
                // @ts-ignore
                this._cellMap.set(sharedModel, cellModel);
                sharedModel.disposed.connect(() => {
                    cellModel.dispose();
                    // @ts-ignore
                    this._cellMap.delete(sharedModel);
                });
                resolve();
            }
        });
    });

    Promise.all(cellPromises).then(() => {
        console.log('All outputs have been updated')
    }).catch(error => {
        console.error('Error updating outputs:', error);
    });
}
*/
/*CellList.prototype.constructor = function(model: ISharedNotebook) {

    // Update the model to get the real output from outputs service
    const outputPromises: Array<Promise<any>> = [];
    // @ts-ignore
    this.model.cells.forEach(sharedModel => {
      if(sharedModel.cell_type == "code") {
        const outputs = (sharedModel as ISharedCodeCell).getOutputs()
        outputs.forEach((output, index) => {
            // @ts-ignore
            if(output.metadata && output.metadata.url) {
                // fetch the actual output
                // @ts-ignore
                const promise = requestAPI(output.metadata.url).then(data => {
                    // @ts-ignore
                    sharedModel.updateOutputs(
                        index,
                        index + 1,
                        [data],
                        'silent-change'
                    )
                }).catch(error => {
                    console.error('Error fetching output:', error);
                });
                outputPromises.push(promise);
            } 
        }) 
      }
    });

    Promise.all(outputPromises).then(() => {
        console.log('All outputs have been updated');
        // @ts-ignore
        this._insertCells(0, this.model.cells);

        // @ts-ignore
        this.model.changed.connect(this._onSharedModelChanged, this);        
    }).catch(error => {
        console.error('Error updating outputs:', error);
    });
}*/

class RtcOutputAreaModel extends OutputAreaModel implements IOutputAreaModel{
  /**
   * Construct a new observable outputs instance.
   */
  constructor(options: IOutputAreaModel.IOptions = {}) {
    super({...options, values: []})
    this._trusted = !!options.trusted;
    this.contentFactory =
      options.contentFactory || OutputAreaModel.defaultContentFactory;
    this.list = new ObservableList<IOutputModel>();
    if (options.values) {
      // Create an array to store promises for each value
      const valuePromises = options.values.map((value, originalIndex) => {
        console.log("originalIndex: ", originalIndex, ", value: ", value);
        // If value has a URL, fetch the data, otherwise just use the value directly
        if (value.metadata?.url) {
          return requestAPI(value.metadata.url)
            .then(data => {
              console.log("data from outputs service: " , data)
              return {data, originalIndex}
            })
            .catch(error => {
              console.error('Error fetching output:', error);
              // If fetch fails, return original value to maintain order
              return { data: null, originalIndex };
            });
        } else {
          // For values without url, return immediately with original value
          return Promise.resolve({ data: value, originalIndex });
        }
      });

      // Wait for all promises to resolve and add values in original order
      Promise.all(valuePromises)
        .then(results => {
          // Sort by original index to maintain order
          results.sort((a, b) => a.originalIndex - b.originalIndex);

          console.log("After fetching outputs...")
          // Add each value in order
          results.forEach((result) => {
            console.log("originalIndex: ", result.originalIndex, ", data: ", result.data)
            if(result.data && !this.isDisposed){
              const index = this._add(result.data) - 1;
              const item = this.list.get(index);
              item.changed.connect(this._onGenericChange, this);
            }
          });

          // Connect the list changed handler after all items are added
          //this.list.changed.connect(this._onListChanged, this);
        })/*
        .catch(error => {
          console.error('Error processing values:', error);
          // If something goes wrong, fall back to original behavior
          options.values.forEach(value => {
            const index = this._add(value) - 1;
            const item = this.list.get(index);
            item.changed.connect(this._onGenericChange, this);
          });
          this.list.changed.connect(this._onListChanged, this);
        });*/
    } else {
      // If no values, just connect the list changed handler
      //this.list.changed.connect(this._onListChanged, this);
    }
    
    this.list.changed.connect(this._onListChanged, this);
  }
}

// This doesn't seem to work
/*Cell.ContentFactory.prototype.createOutputArea = function(options: IOutputAreaModel.IOptions) {
  return new YOutputAreaModel(options);
}*/

CodeCellModel.ContentFactory.prototype.createOutputArea = function(options: IOutputAreaModel.IOptions): IOutputAreaModel {
  return new RtcOutputAreaModel(options);
}



export class YNotebookContentFactory extends NotebookPanel.ContentFactory implements NotebookPanel.IContentFactory{
  createCodeCell(options: CodeCell.IOptions): CodeCell {
    return new CodeCell(options).initializeState();
  }
}
