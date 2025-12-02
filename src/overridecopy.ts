import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Clipboard } from '@jupyterlab/apputils';
import { INotebookTracker, Notebook, NotebookActions } from '@jupyterlab/notebook';
import * as nbformat from '@jupyterlab/nbformat';
import { JSONObject } from '@lumino/coreutils';

/**
 * The mimetype used for Jupyter cell data.
 */
const JUPYTER_CELL_MIME = 'application/vnd.jupyter.cells';

/**
 * Get the selected cell(s) as JSON without outputs.
 *
 * This is based on the private `selectedCells()` function from JupyterLab's
 * notebook actions, but clears outputs from code cells.
 *
 * @param notebook - The target notebook widget.
 * @returns A list of selected cells without outputs
 */
function selectedCellsWithoutOutputs(notebook: Notebook): nbformat.ICell[] {
  return notebook.widgets
    .filter(cell => notebook.isSelectedOrActive(cell))
    .map(cell => cell.model.toJSON())
    .map(cellJSON => {
      // Clear outputs from code cells
      if (cellJSON.cell_type === 'code') {
        (cellJSON as nbformat.ICodeCell).outputs = [];
        (cellJSON as nbformat.ICodeCell).execution_count = null;
      }
      // Remove deletable metadata (same as original implementation)
      if ((cellJSON.metadata as JSONObject).deletable !== undefined) {
        delete (cellJSON.metadata as JSONObject).deletable;
      }
      return cellJSON;
    });
}

/**
 * Copy or cut the selected cell data to the clipboard without outputs.
 *
 * This is based on the private `copyOrCut()` function from JupyterLab's
 * notebook actions.
 *
 * @param notebook - The target notebook widget.
 * @param cut - True if the cells should be cut, false if they should be copied.
 */
function copyOrCut(notebook: Notebook, cut: boolean): void {
  if (!notebook.model || !notebook.activeCell) {
    return;
  }

  const clipboard = Clipboard.getInstance();

  notebook.mode = 'command';
  clipboard.clear();

  // Get selected cells without outputs
  const data = selectedCellsWithoutOutputs(notebook);
  console.log(data)

  clipboard.setData(JUPYTER_CELL_MIME, data);

  if (cut) {
    NotebookActions.deleteCells(notebook);
    notebook.lastClipboardInteraction = 'cut';
  } else {
    notebook.deselectAll();
    notebook.lastClipboardInteraction = 'copy';
  }
}

/**
 * Duplicate selected cells without outputs.
 *
 * This is based on the `duplicate()` function from JupyterLab's notebook actions.
 *
 * @param notebook - The target notebook widget.
 */
function duplicateWithoutOutputs(notebook: Notebook): void {
  if (!notebook.model || !notebook.activeCell) {
    return;
  }

  // Get cells without outputs
  const values = selectedCellsWithoutOutputs(notebook);

  if (!values || values.length === 0) {
    return;
  }

  const model = notebook.model;
  notebook.mode = 'command';

  let index = 0;
  const prevActiveCellIndex = notebook.activeCellIndex;

  // Find the last selected cell to insert after it (belowSelected mode)
  notebook.widgets.forEach((child, childIndex) => {
    if (notebook.isSelectedOrActive(child)) {
      index = childIndex + 1;
    }
  });

  model.sharedModel.transact(() => {
    model.sharedModel.insertCells(
      index,
      values.map(cell => {
        // Don't preserve cell IDs for duplicated cells
        cell.id = undefined;
        return cell;
      })
    );
  });

  notebook.activeCellIndex = prevActiveCellIndex + values.length;
  notebook.deselectAll();
}

/**
 * Plugin to override copy, cut, and duplicate commands to exclude outputs.
 */
export const overrideCopyPlugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter-ai-contrib/server-documents:override-copy-plugin',
  description:
    'Overrides copy, cut, and duplicate commands to exclude cell outputs',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (app: JupyterFrontEnd, notebookTracker: INotebookTracker): void => {
    /**
     * Override commands after app is fully loaded
     */
    app.restored.then(() => {
      // Helper function to get original command and override only the execute
      const overrideCommand = (
        commandId: string,
        newExecute: () => void
      ) => {
        if (!app.commands.hasCommand(commandId)) {
          return;
        }

        // Get the original command descriptor
        const commandRegistry = app.commands as any;
        const originalCommand = commandRegistry._commands?.get(commandId);

        if (!originalCommand) {
          return;
        }

        // Store original properties
        const originalOptions = { ...originalCommand };

        // Remove existing command
        if (commandRegistry._commands && commandRegistry._commands.delete) {
          commandRegistry._commands.delete(commandId);
        }

        // Re-add command with original properties but new execute
        app.commands.addCommand(commandId, {
          ...originalOptions,
          execute: newExecute
        });
      };

      // Helper to get current notebook
      const getCurrentNotebook = (): Notebook | null => {
        return notebookTracker.currentWidget?.content ?? null;
      };

      // Override copy command
      overrideCommand('notebook:copy-cell', () => {
        const notebook = getCurrentNotebook();
        if (notebook) {
          copyOrCut(notebook, false);
        }
      });

      // Override cut command
      overrideCommand('notebook:cut-cell', () => {
        const notebook = getCurrentNotebook();
        if (notebook) {
          copyOrCut(notebook, true);
        }
      });

      // Override duplicate command
      overrideCommand('notebook:duplicate-below', () => {
        const notebook = getCurrentNotebook();
        if (notebook) {
          duplicateWithoutOutputs(notebook);
        }
      });

      console.log('Copy/cut/duplicate commands overridden to exclude outputs');
    });
  }
};
