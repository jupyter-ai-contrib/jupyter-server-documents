import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { IEditorServices } from '@jupyterlab/codeeditor';
import { requestAPI } from './handler';
import { NotebookPanel } from '@jupyterlab/notebook';
import { YNotebookContentFactory } from './notebook';

/**
 * Initialization data for the @jupyter/rtc-core extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/rtc-core:plugin',
  description: 'A JupyterLab extension that provides RTC capabilities.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (app: JupyterFrontEnd, settingRegistry: ISettingRegistry | null) => {
    console.log('JupyterLab extension @jupyter/rtc-core is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('@jupyter/rtc-core settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for @jupyter/rtc-core.', reason);
        });
    }

    requestAPI<any>('get-example')
      .then(data => {
        console.log(data);
      })
      .catch(reason => {
        console.error(
          `The jupyter_rtc_core server extension appears to be missing.\n${reason}`
        );
      });
  }
};

/**
 * The notebook cell factory provider.
 */
const factory: JupyterFrontEndPlugin<NotebookPanel.IContentFactory> = {
  id: '@jupyter-rtc-core/notebook-extension:factory',
  description: 'Provides the notebook cell factory.',
  provides: NotebookPanel.IContentFactory,
  requires: [IEditorServices],
  autoStart: true,
  activate: (app: JupyterFrontEnd, editorServices: IEditorServices) => {
    const editorFactory = editorServices.factoryService.newInlineEditor;
    return new YNotebookContentFactory({ editorFactory });
  }
};

const plugins: JupyterFrontEndPlugin<any>[] = [
  plugin,
  factory
];

export default plugins;
