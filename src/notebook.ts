import { CodeCell, CodeCellLayout } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';
import { KernelMessage } from '@jupyterlab/services'

class YCodeCell extends CodeCell { 
 /**
   * Construct a code cell widget.
   */
  constructor(options: CodeCell.IOptions) {
    super({ layout: new CodeCellLayout(), ...options, placeholder: true });
    this["_output"]["_onIOPub"] = (msg: KernelMessage.IIOPubMessage) => { 
        const log = { ...msg.content, output_type: msg.header.msg_type };
        console.log(log)
    } 
  }
}

export class YNotebookContentFactory extends NotebookPanel.ContentFactory  { 
  createCodeCell(options: CodeCell.IOptions): YCodeCell {
    return new YCodeCell(options).initializeState()
  }
}