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
  return
  // @ts-ignore
  const codeCell = this.sharedModel as YCodeCell;
  globalModelDBMutex(() => {
    if (event.type == 'remove') {
      codeCell.updateOutputs(event.oldIndex, event.oldValues.length, []);
    }
  });
};

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

CodeCellModel.ContentFactory.prototype.createOutputArea = function(options: IOutputAreaModel.IOptions): IOutputAreaModel {
  return new RtcOutputAreaModel(options);
}

export class YNotebookContentFactory extends NotebookPanel.ContentFactory implements NotebookPanel.IContentFactory{
  createCodeCell(options: CodeCell.IOptions): CodeCell {
    return new CodeCell(options).initializeState();
  }
}
