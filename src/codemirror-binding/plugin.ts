/*
 * Copyright (c) Jupyter Development Team.
 * Distributed under the terms of the Modified BSD License.
 */

import { IYText } from '@jupyter/ydoc';
import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import {
  EditorExtensionRegistry,
  IEditorExtensionRegistry
} from '@jupyterlab/codemirror';
import { ybinding } from './ybinding';

/**
 * CodeMirror shared model binding provider.
 */
export const codemirrorYjsPlugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:ybinding',
  description:
    'Register the CodeMirror extension factory binding the editor and the shared model.',
  autoStart: true,
  requires: [IEditorExtensionRegistry],
  activate: (app: JupyterFrontEnd, extensions: IEditorExtensionRegistry) => {
    extensions.addExtension({
      name: 'shared-model-binding',
      factory: options => {
        const sharedModel = options.model.sharedModel as IYText;

        return EditorExtensionRegistry.createImmutableExtension(
          ybinding({
            getYText: () => sharedModel.ysource,
            ytextResetSignal: (sharedModel as any).resetSignal,
            undoManager: sharedModel.undoManager ?? undefined
          })
        );
      }
    });
  }
};
