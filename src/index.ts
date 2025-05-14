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

import { IStateDB, StateDB } from '@jupyterlab/statedb';
import { IGlobalAwareness } from '@jupyter/collaborative-drive';
import * as Y from 'yjs';
import { Awareness } from 'y-protocols/awareness';
import { IAwareness } from '@jupyter/ydoc';

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

/**
 * Jupyter plugin creating a global awareness for RTC.
 */
export const rtcGlobalAwarenessPlugin: JupyterFrontEndPlugin<IAwareness> = {
  id: '@jupyter/rtc-core/collaboration-extension:rtcGlobalAwareness',
  description: 'Add global awareness to share working document of users.',
  requires: [IStateDB],
  provides: IGlobalAwareness,
  activate: (app: JupyterFrontEnd, state: StateDB): IAwareness => {
    // @ts-ignore
    const { user } = app.serviceManager;

    const ydoc = new Y.Doc();
    const awareness = new Awareness(ydoc);

    // TODO: Uncomment once global awareness is working
    /*const server = ServerConnection.makeSettings();
    const url = URLExt.join(server.wsUrl, 'api/collaboration/room');

    new WebSocketAwarenessProvider({
      url: url,
      roomID: 'JupyterLab:globalAwareness',
      awareness: awareness,
      user: user
    });*/

    state.changed.connect(async () => {
      const data: any = await state.toJSON();
      const current: string = data['layout-restorer:data']?.main?.current || '';

      // For example matches `notebook:Untitled.ipynb` or `editor:untitled.txt`,
      // but not when in launcher or terminal.
      if (current.match(/^\w+:.+/)) {
        awareness.setLocalStateField('current', current);
      } else {
        awareness.setLocalStateField('current', null);
      }
    });

    return awareness;
  }
};

const plugins: JupyterFrontEndPlugin<unknown>[] = [
  rtcContentProvider,
  yfile,
  ynotebook,
  logger,
  notebookCellExecutor,
  rtcGlobalAwarenessPlugin,
  plugin
];

export default plugins;
