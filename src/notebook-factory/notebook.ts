import { INotebookModel, Notebook, NotebookModel } from '@jupyterlab/notebook';
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

  set model(newValue: INotebookModel | null) {
    // if current model exists, remove the `resetSignal` observer
    if (this.model) {
      const ynotebook = this.model.sharedModel as YNotebook;
      ynotebook.resetSignal.disconnect(this._resetSignalSlot);
    }

    // call parent property setter
    super.model = newValue;

    // return early if `newValue === null`
    if (!newValue) {
      return;
    }

    // otherwise, listen to `YNotebook.resetSignal`.
    const ynotebook = newValue.sharedModel as YNotebook;
    ynotebook.resetSignal.connect(this._resetSignalSlot);
  }

  /**
   * Function called when the YDoc has been reset. This recreates the notebook
   * model using this model's options.
   *
   * TODO (?): we may want to use NotebookModelFactory, but that factory only
   * seems to set some configuration options. The NotebookModel constructor
   * does not require any arguments so this is OK for now.
   */
  _onReset() {
    if (!this.model) {
      console.warn(
        'The notebook was reset without a model. This should never happen.'
      );
      return;
    }

    this.model = new NotebookModel({
      collaborationEnabled: this.model.collaborative,
      sharedModel: this.model.sharedModel
      // other options in `NotebookModel.IOptions` are either unused or
      // forwarded to `YNotebook`, which is preserved here
    });
  }

  _resetSignalSlot: () => void;
}
