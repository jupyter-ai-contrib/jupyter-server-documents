import { CodeCell, CodeCellLayout } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
//import { KernelMessage } from '@jupyterlab/services'
import { CellChange } from '@jupyter/ydoc'

class YCodeCell extends CodeCell { 
  /** CodeCell that replaces output area with noop IOPub handler */
  constructor(options: CodeCell.IOptions) {
    super({ layout: new CodeCellLayout(), ...options, placeholder: true });
    /*this["_output"]["_onIOPub"] = (msg: KernelMessage.IIOPubMessage) => { 
        const log = { ...msg.content, output_type: msg.header.msg_type };
        console.debug(log)
    }*/ 
    this.model.sharedModel.changed.connect((_, cellChange: CellChange) => {
      console.log(cellChange)
    })
  }
}

export class YNotebookContentFactory extends NotebookPanel.ContentFactory  {   
  createCodeCell(options: CodeCell.IOptions): YCodeCell {
    return new YCodeCell(options).initializeState()
  }
}