import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { requestAPI } from './handler';

import {
  rtcContentProvider,
  yfile,
  ynotebook,
  logger,
  notebookCellExecutor
} from './docprovider';

/**
 * Initialization data for the @jupyter/rtc-core extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/rtc-core:plugin',
  description: 'A JupyterLab extension that provides RTC capabilities.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log('JupyterLab extension @jupyter/rtc-core is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('@jupyter/rtc-core settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error(
            'Failed to load settings for @jupyter/rtc-core.',
            reason
          );
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

const plugins: JupyterFrontEndPlugin<unknown>[] = [
  rtcContentProvider,
  yfile,
  ynotebook,
  logger,
  notebookCellExecutor,
  plugin
];

export default plugins;
