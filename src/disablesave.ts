import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Notification } from '@jupyterlab/apputils';

const SAVE_MESSAGE = 'Autosaving is enabled, manual saves are not needed';

/**
 * The command IDs for docmanager save operations to disable
 */
const SAVE_COMMANDS = {
  save: 'docmanager:save',
  saveAs: 'docmanager:save-as',
  saveAll: 'docmanager:save-all',
  toggleAutosave: 'docmanager:toggle-autosave'
} as const;

// Show the notification every 20 manual save operations
const NOTIFICATION_INTERVAL = 20;

/**
 * Plugin to disable save commands
 */
export const disableSavePlugin: JupyterFrontEndPlugin<void> = {
  id: 'disable-save:plugin',
  description:
    'Disables save commands and removes their keyboard shortcuts since documents are autosaved',
  autoStart: true,
  activate: (app: JupyterFrontEnd): void => {
    let saveNotifiedCount = 0;
    let saveAsNotifiedCount = 0;
    let saveAllNotifiedCount = 0;
    let toggleAutosaveNotifiedCount = 0;
    /**
     * Override save commands and remove keyboard shortcuts after app is fully loaded
     */
    app.restored.then(() => {
      // Helper function to remove existing command and add new one
      const overrideCommand = (commandId: string, options: any) => {
        if (app.commands.hasCommand(commandId)) {
          // Remove existing command using private API
          const commandRegistry = app.commands as any;
          if (commandRegistry._commands && commandRegistry._commands.delete) {
            commandRegistry._commands.delete(commandId);
          }
          app.commands.addCommand(commandId, options);
        }
      };

      const notify = () => {
        Notification.emit(SAVE_MESSAGE, 'info', {
          autoClose: 2000
        });
      };

      // Override main save command (Ctrl/Cmd+S)
      overrideCommand(SAVE_COMMANDS.save, {
        label: 'Save (Autosaving)',
        caption: SAVE_MESSAGE,
        isEnabled: () => true,
        execute: () => {
          if (saveNotifiedCount % NOTIFICATION_INTERVAL === 0) {
            notify();
          }
          saveNotifiedCount++;
          return Promise.resolve();
        }
      });

      // Override save-as command (Ctrl/Cmd+Shift+S)
      overrideCommand(SAVE_COMMANDS.saveAs, {
        label: 'Save As… (Autosaving)',
        caption: SAVE_MESSAGE,
        isEnabled: () => true,
        execute: () => {
          if (saveAsNotifiedCount % NOTIFICATION_INTERVAL === 0) {
            notify();
          }
          saveAsNotifiedCount++;
          return Promise.resolve();
        }
      });

      // Override save-all command
      overrideCommand(SAVE_COMMANDS.saveAll, {
        label: 'Save All (Autosaving)',
        caption: SAVE_MESSAGE,
        isEnabled: () => true,
        execute: () => {
          if (saveAllNotifiedCount % NOTIFICATION_INTERVAL === 0) {
            notify();
          }
          saveAllNotifiedCount++;
          return Promise.resolve();
        }
      });

      // Override toggle autosave command
      overrideCommand(SAVE_COMMANDS.toggleAutosave, {
        label: 'Autosave Documents (Autosaving)',
        caption: SAVE_MESSAGE,
        isEnabled: () => true,
        isToggled: () => true,
        execute: () => {
          if (toggleAutosaveNotifiedCount % NOTIFICATION_INTERVAL === 0) {
            notify();
          }
          toggleAutosaveNotifiedCount++;
          return Promise.resolve();
        }
      });

      console.log('Full autosave enabled, save commands disabled');
    });
  }
};
