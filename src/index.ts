import {
  ILabShell,
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { Title, Widget } from '@lumino/widgets';

import {
  INotebookTracker,
  NotebookPanel,
  INotebookModel
} from '@jupyterlab/notebook';
import { IStatusBar } from '@jupyterlab/statusbar';
import { IDisposable } from '@lumino/disposable';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import { DocumentRegistry } from '@jupyterlab/docregistry';
import {
  IKernelStatusModel,
  ISessionContext,
  ISessionContextDialogs,
  SessionContextDialogs
} from '@jupyterlab/apputils';
import { KeyboardEvent } from 'react';
import { IToolbarWidgetRegistry } from '@jupyterlab/apputils';
import { INotebookCellExecutor, runCell } from '@jupyterlab/notebook';
import { AwarenessExecutionIndicator } from './executionindicator';

import { requestAPI } from './handler';

import { rtcContentProvider, yfile, ynotebook, logger } from './docprovider';

import { IStateDB, StateDB } from '@jupyterlab/statedb';
import { IGlobalAwareness } from '@jupyter/collaborative-drive';
import * as Y from 'yjs';
import { Awareness } from 'y-protocols/awareness';
import { IAwareness } from '@jupyter/ydoc';

import { ServerConnection } from '@jupyterlab/services';
import { WebSocketAwarenessProvider } from './docprovider/awareness';
import { URLExt } from '@jupyterlab/coreutils';
import { AwarenessKernelStatus } from './kernelstatus';

import { codemirrorYjsPlugin } from './codemirror-binding/plugin';
import { notebookFactoryPlugin } from './notebook-factory';

/**
 * Initialization data for the @jupyter/server-documents extension.
 */
export const plugin: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:plugin',
  description: 'A JupyterLab extension that provides RTC capabilities.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log('JupyterLab extension @jupyter/server-documents is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log(
            '@jupyter/server-documents settings loaded:',
            settings.composite
          );
        })
        .catch(reason => {
          console.error(
            'Failed to load settings for @jupyter/server-documents.',
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
          `The jupyter_server_documents server extension appears to be missing.\n${reason}`
        );
      });
  }
};

/**
 * Jupyter plugin creating a global awareness for RTC.
 */
export const rtcGlobalAwarenessPlugin: JupyterFrontEndPlugin<IAwareness> = {
  id: '@jupyter/server-documents:rtc-global-awareness',
  description: 'Add global awareness to share working document of users.',
  requires: [IStateDB],
  provides: IGlobalAwareness,
  activate: (app: JupyterFrontEnd, state: StateDB): IAwareness => {
    const { user } = app.serviceManager;

    const ydoc = new Y.Doc();
    const awareness = new Awareness(ydoc);

    // TODO: Uncomment once global awareness is working
    const server = ServerConnection.makeSettings();
    const url = URLExt.join(server.wsUrl, 'api/collaboration/room');

    new WebSocketAwarenessProvider({
      url: url,
      roomID: 'JupyterLab:globalAwareness',
      awareness: awareness,
      user: user
    });

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

class AwarenessExecutionIndicatorIcon
  implements DocumentRegistry.IWidgetExtension<NotebookPanel, INotebookModel>
{
  createNew(panel: NotebookPanel): IDisposable {
    const item = new AwarenessExecutionIndicator();
    const nb = panel.content;
    item.model.attachNotebook({ content: nb });
    panel.toolbar.insertAfter('kernelName', 'awarenessExecutionProgress', item);
    return item;
  }
}

/**
 * A plugin that provides a execution indicator item to the status bar.
 */
export const executionIndicator: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:awareness-execution-indicator',
  description: 'Adds a notebook execution status widget.',
  autoStart: true,
  requires: [INotebookTracker, ILabShell, ITranslator, IToolbarWidgetRegistry],
  optional: [IStatusBar, ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    notebookTracker: INotebookTracker,
    labShell: ILabShell,
    translator: ITranslator,
    statusBar: IStatusBar | null,
    settingRegistry: ISettingRegistry | null,
    toolbarRegistry: IToolbarWidgetRegistry
  ) => {
    console.log(
      'JupyterLab extension activated: Awareness Execution Indicator'
    );
    app.docRegistry.addWidgetExtension(
      'Notebook',
      new AwarenessExecutionIndicatorIcon()
    );
  }
};

/**
 * A plugin that provides a kernel status item to the status bar.
 */
export const kernelStatus: JupyterFrontEndPlugin<IKernelStatusModel> = {
  id: '@jupyter/server-documents:awareness-kernel-status',
  description: 'Provides the kernel status indicator model.',
  autoStart: true,
  requires: [IStatusBar],
  provides: IKernelStatusModel,
  optional: [ISessionContextDialogs, ITranslator, ILabShell],
  activate: (
    app: JupyterFrontEnd,
    statusBar: IStatusBar,
    sessionDialogs_: ISessionContextDialogs | null,
    translator_: ITranslator | null,
    labShell: ILabShell | null
  ): IKernelStatusModel => {
    console.log(
      'JupyterLab extension activated: Awareness Kernel Status Indicator'
    );
    const translator = translator_ ?? nullTranslator;
    const sessionDialogs =
      sessionDialogs_ ?? new SessionContextDialogs({ translator });
    // When the status item is clicked, launch the kernel
    // selection dialog for the current session.
    const changeKernel = async () => {
      if (!item.model.sessionContext) {
        return;
      }
      await sessionDialogs.selectKernel(item.model.sessionContext);
    };

    const changeKernelOnKeyDown = async (
      event: KeyboardEvent<HTMLImageElement>
    ) => {
      if (
        event.key === 'Enter' ||
        event.key === 'Spacebar' ||
        event.key === ' '
      ) {
        event.preventDefault();
        event.stopPropagation();
        return changeKernel();
      }
    };

    // Create the status item.
    const item = new AwarenessKernelStatus(
      { onClick: changeKernel, onKeyDown: changeKernelOnKeyDown },
      translator
    );

    const providers = new Set<(w: Widget | null) => ISessionContext | null>();

    const addSessionProvider = (
      provider: (w: Widget | null) => ISessionContext | null
    ): void => {
      providers.add(provider);

      if (app.shell.currentWidget) {
        updateSession(app.shell, {
          newValue: app.shell.currentWidget,
          oldValue: null
        });
      }
    };

    function updateSession(
      shell: JupyterFrontEnd.IShell,
      changes: ILabShell.IChangedArgs
    ) {
      const { oldValue, newValue } = changes;

      // Clean up after the old value if it exists,
      // listen for changes to the title of the activity
      if (oldValue) {
        oldValue.title.changed.disconnect(onTitleChanged);
      }

      item.model.attachDocument(newValue);
      item.model.sessionContext =
        [...providers]
          .map(provider => provider(changes.newValue))
          .filter(session => session !== null)[0] ?? null;

      if (newValue && item.model.sessionContext) {
        onTitleChanged(newValue.title);
        newValue.title.changed.connect(onTitleChanged);
      }
    }

    // When the title of the active widget changes, update the label
    // of the hover text.
    const onTitleChanged = (title: Title<Widget>) => {
      item.model!.activityName = title.label;
    };

    if (labShell) {
      labShell.currentChanged.connect(updateSession);
    }

    statusBar.registerStatusItem(kernelStatus.id, {
      priority: 1,
      item,
      align: 'left',
      rank: 1,
      isActive: () => true
    });

    return { addSessionProvider };
  }
};

/**
 * Notebook cell executor plugin, provided by JupyterLab by default. Re-provided
 * to ensure compatibility with `jupyter_collaboration`.
 *
 * The `@jupyter/docprovider-extension` disables this plugin to override it, but
 * we disable that labextension, leaving `INotebookCellExecutor` un-implemented.
 * This plugin fixes that issue by re-providing this plugin with `autoStart:
 * false`, which specifies that this plugin only gets activated if no other
 * implementation exists, e.g. only when `jupyter_collaboration` is installed.
 */
export const backupCellExecutorPlugin: JupyterFrontEndPlugin<INotebookCellExecutor> =
  {
    id: '@jupyter/server-documents:backup-cell-executor',
    description:
      'Provides a backup default implementation of the notebook cell executor.',
    autoStart: false,
    provides: INotebookCellExecutor,
    activate: (): INotebookCellExecutor => {
      return Object.freeze({ runCell });
    }
  };

const plugins: JupyterFrontEndPlugin<unknown>[] = [
  rtcContentProvider,
  yfile,
  ynotebook,
  logger,
  rtcGlobalAwarenessPlugin,
  plugin,
  executionIndicator,
  kernelStatus,
  notebookFactoryPlugin,
  codemirrorYjsPlugin,
  backupCellExecutorPlugin
];

export default plugins;
