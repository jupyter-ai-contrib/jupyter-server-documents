import { CodeCell } from '@jupyterlab/cells';
import { NotebookPanel } from '@jupyterlab/notebook';


class YCodeCell extends CodeCell { 

}


export class YNotebookContentFactory extends NotebookPanel.ContentFactory  { 

  createCodeCell(options: CodeCell.IOptions): YCodeCell {
    return new YCodeCell(options).initializeState()
  }
}