import { INotebookModel, Notebook } from '@jupyterlab/notebook';
import { YNotebook } from '../docprovider/custom_ydocs';

/**
 * A custom implementation of `Notebook` that resets the notebook to an empty
 * state when `YNotebook.resetSignal` is emitted to.
 *
 * This requires the custom `YNotebook` class defined by this labextension.
 */
export class ResettableNotebook extends Notebook {
  constructor(options: Notebook.IOptions) {
    super(options);
    this._resetSignalSlot = () => this._onReset();
  }

  get model(): INotebookModel | null {
    return super.model;
  }

  set model(newModel: INotebookModel | null) {
    // if there is an existing model, remove the `resetSignal` observer
    const oldModel = this.model;
    if (oldModel) {
      const ynotebook = oldModel.sharedModel as YNotebook;
      ynotebook.resetSignal.disconnect(this._resetSignalSlot);
    }

    // call parent property setter
    super.model = newModel;

    // return early if `newValue === null`
    if (!newModel) {
      return;
    }

    // otherwise, listen to `YNotebook.resetSignal`.
    const ynotebook = newModel.sharedModel as YNotebook;
    ynotebook.resetSignal.connect(this._resetSignalSlot);
  }

  /**
   * Function called when the YDoc has been reset. This simply refreshes the UI
   * to reflect the new YDoc state.
   */
  _onReset() {
    if (!this.model) {
      console.warn(
        'The notebook was reset without a model. This should never happen.'
      );
      return;
    }

    // Refresh the UI by emitting to the `modelContentChanged` signal
    this.onModelContentChanged(this.model);
  }

  _resetSignalSlot: () => void;
}
