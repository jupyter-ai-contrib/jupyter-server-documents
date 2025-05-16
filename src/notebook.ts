import { CodeCell, CodeCellModel } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import { KernelMessage } from '@jupyterlab/services'
import { CellChange, createMutex, ISharedCodeCell } from '@jupyter/ydoc'
import { IOutputAreaModel } from '@jupyterlab/outputarea'
import { requestAPI } from './handler';


const globalModelDBMutex = createMutex();

// @ts-ignore
CodeCellModel.prototype._onSharedModelChanged = function(
  slot: ISharedCodeCell, change: CellChange
){
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
            if('toJSON' in output){
              // @ts-ignore
              const parsed = output.toJSON()
              const metadata = parsed.metadata
              if(metadata && metadata.url){
                // fetch the real output
                requestAPI(metadata.url).then((data) => {
                    // @ts-ignore
                    this._outputs.add(data)
                });
              } else {
                // @ts-ignore
                this._outputs.add(parsed);
              }
            } else {
              console.debug("output from doc: ", output)
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
}


// @ts-ignore
CodeCellModel.prototype.onOutputsChange = function(
  sender: IOutputAreaModel,
  event: IOutputAreaModel.ChangedArgs
){
  console.debug(
    "Inside onOutputsChange, called with event: ", event
  )
  // @ts-ignore
  const codeCell = this.sharedModel as YCodeCell;
  globalModelDBMutex(() => {
    if(event.type == "remove") {
        codeCell.updateOutputs(
          event.oldIndex,
          event.oldValues.length,
          []
        );
    }
  });
}

// @ts-ignore
CodeCell.prototype._onIOPub = (msg: KernelMessage.IIOPubMessage) => {
  const log = { ...msg.content, output_type: msg.header.msg_type };
  console.debug(log)
}

export class YNotebookContentFactory extends NotebookPanel.ContentFactory  {   
  createCodeCell(options: CodeCell.IOptions): CodeCell {
    return new CodeCell(options).initializeState()
  }
}