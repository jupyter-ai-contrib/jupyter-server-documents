import { CodeCell, ICellModel, ICodeCellModel } from '@jupyterlab/cells';
import { IChangedArgs } from '@jupyterlab/coreutils';
import { Notebook, NotebookPanel } from '@jupyterlab/notebook';
import { ResettableNotebook } from './notebook';

/**
 * The class name added to the cell when dirty.
 */
const DIRTY_CLASS = 'jp-mod-dirty';

/**
 * NOTE: We should upstream this fix. This is a bug in JupyterLab.
 *
 * The execution count comes back from the kernel immediately
 * when the execute request is made by the client, even thought
 * cell might still be running. JupyterLab holds this value in
 * memory with a Promise to set it later, once the execution
 * state goes back to Idle.
 *
 * In CRDT world, we don't need to do this gymnastics, holding
 * the state in a Promise. Instead, we can just watch the
 * executionState and executionCount in the CRDT being maintained
 * by the server-side model.
 *
 * This is a big win! It means user can close and re-open a
 * notebook while a list of executed cells are queued.
 */
(CodeCell.prototype as any).onStateChanged = function (
  model: ICellModel,
  args: IChangedArgs<any>
): void {
  switch (args.name) {
    case 'executionCount':
      this._updatePrompt();
      break;
    case 'isDirty':
      if ((model as ICodeCellModel).isDirty) {
        this.addClass(DIRTY_CLASS);
      } else {
        this.removeClass(DIRTY_CLASS);
      }
      break;
    default:
      break;
  }

  // Always update prompt to check for awareness state on any state change
  this._updatePrompt();
};

/**
 * Override the _updatePrompt method to check awareness execution state for real-time updates.
 */
(CodeCell.prototype as any)._updatePrompt = function (): void {
  let prompt: string;

  const cellExecutionState = this._getCellExecutionStateFromAwareness();

  if (cellExecutionState === 'busy') {
    prompt = '*';
  } else {
    prompt = `${this.model.executionCount || ''}`;
  }

  this._setPrompt(prompt);
};

/**
 * Get execution state for this cell from awareness system.
 *
 * Returns:
 * - 'busy'|'idle'|'running': actual execution state from awareness
 * - null: awareness connection lost
 * - undefined: cell never executed
 */
(CodeCell.prototype as any)._getCellExecutionStateFromAwareness = function ():
  | string
  | null
  | undefined {
  const notebook = this.parent?.parent;
  if (!notebook?.model?.sharedModel?.awareness) {
    return null;
  }

  const awareness = notebook.model.sharedModel.awareness;
  const awarenessStates = awareness.getStates();

  if (awarenessStates.size === 0) {
    return null;
  }

  let hasAnyExecutionStates = false;
  for (const [_, clientState] of awarenessStates) {
    if (clientState && 'cell_execution_states' in clientState) {
      const cellStates = clientState['cell_execution_states'];
      hasAnyExecutionStates = true;
      if (cellStates && this.model.sharedModel.getId() in cellStates) {
        return cellStates[this.model.sharedModel.getId()];
      }
    }
  }

  if (hasAnyExecutionStates) {
    return undefined;
  } else {
    return null;
  }
};

/**
 * Initialize CodeCell state including awareness listener setup.
 */
(CodeCell.prototype as any).initializeState = function (): CodeCell {
  this._setupAwarenessListener();
  return this;
};

/**
 * Set up awareness listener for prompt updates.
 */
(CodeCell.prototype as any)._setupAwarenessListener = function (): void {
  const updatePromptFromAwareness = () => {
    this._updatePrompt();
  };

  this.ready.then(() => {
    const notebook = this.parent?.parent;
    if (notebook?.model?.sharedModel?.awareness) {
      notebook.model.sharedModel.awareness.on(
        'change',
        updatePromptFromAwareness
      );

      this._awarenessUpdateListener = updatePromptFromAwareness;
      this._awarenessInstance = notebook.model.sharedModel.awareness;

      this._updatePrompt();
    }
  });
};

/**
 * Override dispose to clean up awareness listener.
 */
const originalDispose = CodeCell.prototype.dispose;
(CodeCell.prototype as any).dispose = function (): void {
  if (this._awarenessUpdateListener && this._awarenessInstance) {
    this._awarenessInstance.off('change', this._awarenessUpdateListener);
    this._awarenessUpdateListener = null;
    this._awarenessInstance = null;
  }
  originalDispose.call(this);
};

export class RtcNotebookContentFactory
  extends NotebookPanel.ContentFactory
  implements NotebookPanel.IContentFactory
{
  createNotebook(options: Notebook.IOptions): Notebook {
    return new ResettableNotebook(options);
  }
}
