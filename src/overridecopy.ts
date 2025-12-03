import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Clipboard } from '@jupyterlab/apputils';
import { INotebookTracker, Notebook } from '@jupyterlab/notebook';
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
   * The interface for a widget state.
   */
  export interface IState {
    /**
     * Whether the widget had focus.
     */
    wasFocused: boolean;

    /**
     * The active cell id before the action.
     *
     * We cannot rely on the Cell widget or model as it may be
     * discarded by action such as move.
     */
    activeCellId: string | null;
  }

  /**
   * Get the state of a widget before running an action.
   */
  export function getState(notebook: Notebook): IState {
    return {
      wasFocused: notebook.node.contains(document.activeElement),
      activeCellId: notebook.activeCell?.model.id ?? null
    };
  }

  /**
     * Handle the state of a widget after running an action.
     */
    export async function handleState(
      notebook: Notebook,
      state: IState,
      scrollIfNeeded = false
    ): Promise<void> {
      const { activeCell, activeCellIndex } = notebook;
      if (scrollIfNeeded && activeCell) {
        await notebook.scrollToItem(activeCellIndex, 'auto', 0).catch(reason => {
          // no-op
        });
      }
      if (state.wasFocused || notebook.mode === 'edit') {
        notebook.activate();
      }
    }

/**
   * Delete the selected cells.
   *
   * @param notebook - The target notebook widget.
   *
   * #### Notes
   * The cell after the last selected cell will be activated.
   * If the last cell is deleted, then the previous one will be activated.
   * It will add a code cell if all cells are deleted.
   * This action can be undone.
   */
  export function deleteCells(notebook: Notebook): void {
    const model = notebook.model!;
    const sharedModel = model.sharedModel;
    const toDelete: number[] = [];

    notebook.mode = 'command';

    // Find the cells to delete.
    notebook.widgets.forEach((child, index) => {
      const deletable = child.model.getMetadata('deletable') !== false;

      if (notebook.isSelectedOrActive(child) && deletable) {
        toDelete.push(index);
        notebook.model?.deletedCells.push(child.model.id);
      }
    });

    // If cells are not deletable, we may not have anything to delete.
    if (toDelete.length > 0) {
      // Delete the cells as one undo event.
      sharedModel.transact(() => {
        // Delete cells in reverse order to maintain the correct indices.
        toDelete.reverse().forEach(index => {
          sharedModel.deleteCell(index);
        });

        // Add a new cell if the notebook is empty. This is done
        // within the compound operation to make the deletion of
        // a notebook's last cell undoable.
        if (sharedModel.cells.length == toDelete.length) {
          sharedModel.insertCell(0, {
            cell_type: notebook.notebookConfig.defaultCell,
            metadata:
              notebook.notebookConfig.defaultCell === 'code'
                ? {
                    // This is an empty cell created in empty notebook, thus is trusted
                    trusted: true
                  }
                : {}
          });
        }
      });
      // Select the *first* interior cell not deleted or the cell
      // *after* the last selected cell.
      // Note: The activeCellIndex is clamped to the available cells,
      // so if the last cell is deleted the previous cell will be activated.
      // The *first* index is the index of the last cell in the initial
      // toDelete list due to the `reverse` operation above.
      notebook.activeCellIndex = toDelete[0] - toDelete.length + 1;
    }

    // Deselect any remaining, undeletable cells. Do this even if we don't
    // delete anything so that users are aware *something* happened.
    notebook.deselectAll();
  }

/**
   * Copy or cut the selected cell data to the clipboard without outputs.
   *
   * @param notebook - The target notebook widget.
   *
   * @param cut - True if the cells should be cut, false if they should be copied.
   */
  export function copyOrCut(notebook: Notebook, cut: boolean): void {
    if (!notebook.model || !notebook.activeCell) {
      return;
    }

    const state = getState(notebook);
    const clipboard = Clipboard.getInstance();

    notebook.mode = 'command';
    clipboard.clear();

    const data = selectedCellsWithoutOutputs(notebook);
    console.log(data)

    clipboard.setData(JUPYTER_CELL_MIME, data);
    if (cut) {
      deleteCells(notebook);
    } else {
      notebook.deselectAll();
    }
    if (cut) {
      notebook.lastClipboardInteraction = 'cut';
    } else {
      notebook.lastClipboardInteraction = 'copy';
    }
    void handleState(notebook, state);
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
    });
  }
};
