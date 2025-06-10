import type {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { NotebookPanel } from '@jupyterlab/notebook';
import { IEditorServices } from '@jupyterlab/codeeditor';

import { RtcNotebookContentFactory } from './notebook-factory';

type NotebookFactoryPlugin =
  JupyterFrontEndPlugin<NotebookPanel.IContentFactory>;

/**
 * Custom `Notebook` factory plugin.
 */
export const notebookFactoryPlugin: NotebookFactoryPlugin = {
  id: '@jupyter/server-documents:notebook-factory',
  description: 'Provides the notebook cell factory.',
  provides: NotebookPanel.IContentFactory,
  requires: [IEditorServices],
  autoStart: true,
  activate: (app: JupyterFrontEnd, editorServices: IEditorServices) => {
    const editorFactory = editorServices.factoryService.newInlineEditor;
    return new RtcNotebookContentFactory({ editorFactory });
  }
};
