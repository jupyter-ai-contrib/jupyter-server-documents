/*
 * Copyright (c) Jupyter Development Team.
 * Distributed under the terms of the Modified BSD License.
 */

import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import { DocumentWidget, IDocumentWidget } from '@jupyterlab/docregistry';
import { ContentsManager } from '@jupyterlab/services';

import {
  IEditorTracker,
  IEditorWidgetFactory,
  FileEditorFactory
} from '@jupyterlab/fileeditor';
import { ILogger, ILoggerRegistry } from '@jupyterlab/logconsole';
import {
  INotebookTracker,
  INotebookWidgetFactory,
  NotebookWidgetFactory
} from '@jupyterlab/notebook';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';

import { YFile, YNotebook } from './custom_ydocs';

import {
  ICollaborativeContentProvider,
  IGlobalAwareness
} from '@jupyter/collaborative-drive';
import { RtcContentProvider } from './ydrive';
import { Awareness } from 'y-protocols/awareness';

import { YChat } from './custom_ydocs';
import { IChatFactory } from 'jupyterlab-chat';
import { AbstractChatModel } from '@jupyter/chat';

const TWO_SESSIONS_WARNING =
  'The file %1 has been opened with two different views. ' +
  'This is not supported. Please close this view; otherwise, ' +
  'some of your edits may not be saved properly.';

export const rtcContentProvider: JupyterFrontEndPlugin<ICollaborativeContentProvider> =
  {
    id: '@jupyter/server-documents:rtc-content-provider',
    description: 'The RTC content provider',
    provides: ICollaborativeContentProvider,
    requires: [ITranslator],
    optional: [IGlobalAwareness],
    activate: (
      app: JupyterFrontEnd,
      translator: ITranslator,
      globalAwareness: Awareness | null
    ): ICollaborativeContentProvider => {
      const trans = translator.load('jupyter_collaboration');
      const defaultDrive = (app.serviceManager.contents as ContentsManager)
        .defaultDrive;
      if (!defaultDrive) {
        throw Error(
          'Cannot initialize content provider: default drive property not accessible on contents manager instance.'
        );
      }
      const registry = defaultDrive.contentProviderRegistry;
      if (!registry) {
        throw Error(
          'Cannot initialize content provider: no content provider registry.'
        );
      }
      const rtcContentProvider = new RtcContentProvider({
        app,
        apiEndpoint: '/api/contents',
        serverSettings: defaultDrive.serverSettings,
        user: app.serviceManager.user,
        trans,
        globalAwareness
      });
      registry.register('rtc', rtcContentProvider);
      return rtcContentProvider;
    }
  };

/**
 * Plugin to register the shared model factory for the content type 'file'.
 */
export const yfile: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:yfile',
  description:
    "Plugin to register the shared model factory for the content type 'file'",
  autoStart: true,
  requires: [ICollaborativeContentProvider, IEditorWidgetFactory],
  activate: (
    app: JupyterFrontEnd,
    contentProvider: ICollaborativeContentProvider,
    editorFactory: FileEditorFactory.IFactory
  ): void => {
    const yFileFactory = () => {
      return new YFile();
    };
    contentProvider.sharedModelFactory.registerDocumentFactory(
      'file',
      yFileFactory
    );
    editorFactory.contentProviderId = 'rtc';
  }
};

/**
 * Plugin to register the shared model factory for the content type 'notebook'.
 */
export const ynotebook: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:ynotebook',
  description:
    "Plugin to register the shared model factory for the content type 'notebook'",
  autoStart: true,
  requires: [ICollaborativeContentProvider, INotebookWidgetFactory],
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    contentProvider: ICollaborativeContentProvider,
    notebookFactory: NotebookWidgetFactory.IFactory,
    settingRegistry: ISettingRegistry | null
  ): void => {
    let disableDocumentWideUndoRedo = true;

    // Fetch settings if possible.
    if (settingRegistry) {
      settingRegistry
        .load('@jupyterlab/notebook-extension:tracker')
        .then(settings => {
          const updateSettings = (settings: ISettingRegistry.ISettings) => {
            const enableDocWideUndo = settings?.get(
              'experimentalEnableDocumentWideUndoRedo'
            ).composite as boolean;

            disableDocumentWideUndoRedo = !(enableDocWideUndo ?? false);
          };

          updateSettings(settings);
          settings.changed.connect((settings: ISettingRegistry.ISettings) =>
            updateSettings(settings)
          );
        });
    }

    const yNotebookFactory = () => {
      return new YNotebook({
        disableDocumentWideUndoRedo
      });
    };
    contentProvider.sharedModelFactory.registerDocumentFactory(
      'notebook',
      yNotebookFactory
    );
    notebookFactory.contentProviderId = 'rtc';
  }
};

/**
 * This plugin provides the YChat shared model and handles document resets by
 * listening to the `YChat.resetSignal` property automatically.
 *
 * Whenever a YChat is reset, this plugin will iterate through all of the app's
 * document widgets and find the one containing the `YChat` shared model which
 * was reset. It then clears the content.
 */
export const ychat: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:ychat',
  description:
    'Plugin to register a custom YChat factory and handle document resets.',
  autoStart: true,
  requires: [ICollaborativeContentProvider],
  optional: [IChatFactory],
  activate: (
    app: JupyterFrontEnd,
    contentProvider: ICollaborativeContentProvider,
    chatFactory?: IChatFactory
  ): void => {
    if (!chatFactory) {
      console.warn(
        'No existing shared model factory found for chat. Not providing custom chat shared model.'
      );
      return;
    }

    const onYChatReset = (ychat: YChat) => {
      console.log('Detected YChat reset. Reseting frontend state.');
      for (const widget of app.shell.widgets()) {
        if (!(widget instanceof DocumentWidget)) {
          continue;
        }
        const model = widget.content.model;
        const sharedModel = model && model._sharedModel;
        if (
          !(model instanceof AbstractChatModel && sharedModel instanceof YChat)
        ) {
          continue;
        }
        if (sharedModel !== ychat) {
          continue;
        }

        // If this point is reached, we have identified the correct parent
        // `model: AbstractChatModel` that maintains the message state for the
        // `YChat` which was reset. We clear its content directly & emit a
        // `contentChanged` signal to update the UI.
        (model as any)._messages = [];
        (model as any)._messagesUpdated.emit();
        console.log('Chat room reset successfully.');
        break;
      }
    };

    // Override the existing `YChat` factory to provide a custom `YChat` with a
    // `resetSignal`, which is automatically subscribed to & refreshes the UI
    // state upon document reset.
    const yChatFactory = () => {
      const ychat = new YChat();
      ychat.resetSignal.connect(() => {
        onYChatReset(ychat);
      });
      return ychat;
    };
    contentProvider.sharedModelFactory.registerDocumentFactory(
      'chat',
      yChatFactory as any
    );
  }
};

/**
 * The default collaborative drive provider.
 */
export const logger: JupyterFrontEndPlugin<void> = {
  id: '@jupyter/server-documents:rtc-drive-logger',
  description: 'A logging plugin for debugging purposes.',
  autoStart: true,
  optional: [ILoggerRegistry, IEditorTracker, INotebookTracker, ITranslator],
  activate: (
    app: JupyterFrontEnd,
    loggerRegistry: ILoggerRegistry | null,
    fileTracker: IEditorTracker | null,
    nbTracker: INotebookTracker | null,
    translator: ITranslator | null
  ): void => {
    const trans = (translator ?? nullTranslator).load('jupyter_collaboration');
    const schemaID =
      'https://schema.jupyter.org/jupyter_collaboration/session/v1';

    if (!loggerRegistry) {
      app.serviceManager.events.stream.connect((_, emission) => {
        if (emission.schema_id === schemaID) {
          console.debug(
            `[${emission.room}(${emission.path})] ${emission.action ?? ''}: ${
              emission.msg ?? ''
            }`
          );

          if (emission.level === 'WARNING') {
            showDialog({
              title: trans.__('Warning'),
              body: trans.__(TWO_SESSIONS_WARNING, emission.path),
              buttons: [Dialog.okButton()]
            });
          }
        }
      });

      return;
    }

    const loggers: Map<string, ILogger> = new Map();

    const addLogger = (sender: unknown, document: IDocumentWidget) => {
      const logger = loggerRegistry.getLogger(document.context.path);
      loggers.set(document.context.localPath, logger);

      document.disposed.connect(document => {
        loggers.delete(document.context.localPath);
      });
    };

    if (fileTracker) {
      fileTracker.widgetAdded.connect(addLogger);
    }

    if (nbTracker) {
      nbTracker.widgetAdded.connect(addLogger);
    }

    void (async () => {
      const { events } = app.serviceManager;
      for await (const emission of events.stream) {
        if (emission.schema_id === schemaID) {
          const logger = loggers.get(emission.path as string);

          logger?.log({
            type: 'text',
            level: (emission.level as string).toLowerCase() as any,
            data: `[${emission.room}] ${emission.action ?? ''}: ${
              emission.msg ?? ''
            }`
          });

          if (emission.level === 'WARNING') {
            showDialog({
              title: trans.__('Warning'),
              body: trans.__(TWO_SESSIONS_WARNING, emission.path),
              buttons: [Dialog.warnButton({ label: trans.__('Ok') })]
            });
          }
        }
      }
    })();
  }
};
