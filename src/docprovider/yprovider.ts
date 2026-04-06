/* -----------------------------------------------------------------------------
| Copyright (c) Jupyter Development Team.
| Distributed under the terms of the Modified BSD License.
|----------------------------------------------------------------------------*/

import { IDocumentProvider } from '@jupyter/collaborative-drive';
import { showErrorMessage, Dialog } from '@jupyterlab/apputils';
import { User } from '@jupyterlab/services';
import { TranslationBundle } from '@jupyterlab/translation';
import { PromiseDelegate } from '@lumino/coreutils';
import { Signal } from '@lumino/signaling';
import { Notification } from '@jupyterlab/apputils';

import { DocumentChange, YDocument } from '@jupyter/ydoc';

import { Awareness } from 'y-protocols/awareness';
import { WebsocketProvider as YWebsocketProvider } from 'y-websocket';
import { requestAPI } from './requests';
import { JupyterFrontEnd } from '@jupyterlab/application';
import { DocumentWidget } from '@jupyterlab/docregistry';
import { FileEditor } from '@jupyterlab/fileeditor';
import { Notebook } from '@jupyterlab/notebook';
import { ChatWidget } from '@jupyter/chat';
import { Widget } from '@lumino/widgets';

/**
 * A class to provide Yjs synchronization over WebSocket.
 *
 * We specify custom messages that the server can interpret. For reference please look in yjs_ws_server.
 *
 */

export class WebSocketProvider implements IDocumentProvider {
  /**
   * Maximum number of reconnect attempts before showing the retry dialog.
   */
  static readonly MAX_RECONNECT_ATTEMPTS = 5;

  /**
   * Construct a new WebSocketProvider
   *
   * @param options The instantiation options for a WebSocketProvider
   */
  constructor(options: WebSocketProvider.IOptions) {
    this._app = options.app;
    this._isDisposed = false;
    this._path = options.path;
    this._contentType = options.contentType;
    this._format = options.format;
    this._serverUrl = options.url;
    this._sharedModel = options.model;
    this._yWebsocketProvider = null;
    this._trans = options.translator;

    const user = options.user;

    user.ready
      .then(() => {
        this._onUserChanged(user);
      })
      .catch(e => console.error(e));
    user.userChanged.connect(this._onUserChanged, this);

    this._connect().catch(e => console.warn(e));
  }

  /**
   * Returns the awareness object within the shared model.
   */
  get awareness(): Awareness {
    return this._sharedModel.awareness;
  }

  /**
   * Test whether the object has been disposed.
   */
  get isDisposed(): boolean {
    return this._isDisposed;
  }

  /**
   * Returns the **document widget** containing this provider's shared model.
   * Returns `null` if the document widget is not open (i.e. the tab was already
   * closed).
   */
  get parentDocumentWidget(): DocumentWidget | null {
    const shell = this._app.shell;

    // Iterate through all main area widgets
    for (const docWidget of shell.widgets()) {
      // Skip non-document widgets, i.e. widgets that aren't editing a file
      if (!(docWidget instanceof DocumentWidget)) {
        continue;
      }

      // Skip widgets that don't contain a YFile / YNotebook / YChat
      const widget = docWidget.content;
      if (
        !(
          widget instanceof FileEditor ||
          widget instanceof Notebook ||
          widget instanceof ChatWidget
        )
      ) {
        continue;
      }

      // Return the document widget if found in this iteration
      // @ts-expect-error: TSC complains here, but reference equality checks are
      // always safe.
      if (widget.model?.sharedModel === this._sharedModel) {
        return docWidget;
      }
    }

    // If document widget was not found, return `null`.
    // This indicates that the tab containing this provider's shared model has
    // already been closed.
    return null;
  }

  /**
   * A promise that resolves when the document provider is ready.
   */
  get ready(): Promise<void> {
    return this._ready.promise;
  }
  get contentType(): string {
    return this._contentType;
  }

  get format(): string {
    return this._format;
  }
  /**
   * Dispose of the resources held by the object.
   */
  dispose(): void {
    if (this.isDisposed) {
      return;
    }
    this._isDisposed = true;
    this._dismissReconnectDialog();
    this._yWebsocketProvider?.off('connection-close', this._onConnectionClosed);
    this._yWebsocketProvider?.off('sync', this._onSync);
    this._yWebsocketProvider?.off('status', this._onStatus);
    this._yWebsocketProvider?.destroy();
    this._disconnect();
    Signal.clearData(this);
  }

  async reconnect(): Promise<void> {
    this._disconnect();
    this._connect();
  }

  /**
   * Gets the file ID for this path. This should only be called once when the
   * provider connects for the first time, because any future in-band moves may
   * cause `this._path` to not refer to the correct file.
   */
  private async _getFileId(): Promise<string | null> {
    let fileId: string | null = null;
    try {
      const resp = await requestAPI(`api/fileid/index?path=${this._path}`, {
        method: 'POST'
      });
      if (resp && 'id' in resp && typeof resp['id'] === 'string') {
        fileId = resp['id'];
      }
    } catch (e) {
      console.error(`Could not get file ID for path '${this._path}'.`);
      return null;
    }
    return fileId;
  }

  private async _connect(): Promise<void> {
    // Fetch file ID from the file ID service, if not cached
    if (!this._fileId) {
      this._fileId = await this._getFileId();
    }

    // If file ID could not be retrieved, show an error dialog asking for a bug
    // report, as this error is irrecoverable.
    if (!this._fileId) {
      showErrorMessage(
        this._trans.__('File ID error'),
        `The file '${this._path}' cannot be opened because its file ID could not be retrieved. Please report this issue on GitHub.`,
        [Dialog.okButton()]
      );
      return;
    }

    // Otherwise, initialize the `YWebsocketProvider` to connect
    this._yWebsocketProvider = new YWebsocketProvider(
      this._serverUrl,
      `${this._format}:${this._contentType}:${this._fileId}`,
      this._sharedModel.ydoc,
      {
        disableBc: true,
        // params: { sessionId: session.sessionId },
        awareness: this.awareness
      }
    );

    this._yWebsocketProvider.on('sync', this._onSync);
    this._yWebsocketProvider.on('connection-close', this._onConnectionClosed);
    this._yWebsocketProvider.on('status', this._onStatus);
  }

  get wsProvider() {
    return this._yWebsocketProvider;
  }
  private _disconnect(): void {
    this._yWebsocketProvider?.off('connection-close', this._onConnectionClosed);
    this._yWebsocketProvider?.off('sync', this._onSync);
    this._yWebsocketProvider?.off('status', this._onStatus);
    this._yWebsocketProvider?.destroy();
    this._yWebsocketProvider = null;
  }

  private _onUserChanged(user: User.IManager): void {
    this.awareness.setLocalStateField('user', user.identity);
  }

  /**
   * Handles disconnections from the YRoom Websocket.
   *
   * Resolves: https://github.com/jupyter-ai-contrib/jupyter-server-documents/issues/196
   */
  private _onConnectionClosed = (event: CloseEvent): void => {
    const close_code = event.code;

    // 4001 := indicates out-of-band move/deletion
    if (close_code === 4001) {
      this._handleOobMove();
      return;
    }

    // 4002 := indicates in-band deletion
    if (close_code === 4002) {
      this._handleIbDeletion();
      return;
    }

    // For all other close codes (e.g. 1006 abnormal closure, 1001 going away,
    // ping timeout), let y-websocket's built-in exponential backoff handle
    // reconnection automatically. Only log a warning.
    console.warn(
      `WebSocket connection closed (code=${close_code}). ` +
        'y-websocket will attempt to reconnect automatically.',
      event
    );
  };

  /**
   * Handles y-websocket status changes ('connected' / 'disconnected').
   * Tracks reconnect attempts and provides user feedback via a single
   * overlay dialog that blocks notebook interaction during reconnection.
   */
  private _onStatus = ({ status }: { status: string }): void => {
    if (status === 'connected') {
      if (WebSocketProvider._reconnectedManually) {
        console.info('WebSocket reconnected successfully.');
        WebSocketProvider._reconnectedManually = false;
        Notification.success(this._trans.__('Connection restored.'), {
          autoClose: 3000
        });
      }
      this._reconnectAttempts = 0;
      return;
    }

    // status === 'disconnected'
    this._reconnectAttempts++;

    if (this._reconnectAttempts > WebSocketProvider.MAX_RECONNECT_ATTEMPTS) {
      console.error(
        `WebSocket failed to reconnect after ${this._reconnectAttempts} attempts.`
      );
      // Stop y-websocket's auto-reconnect and show the retry dialog.
      this._yWebsocketProvider?.disconnect();
      this._showRetryDialog();
      return;
    }
  };

  // ---------------------------------------------------------------------------
  // Reconnect overlay dialog
  // ---------------------------------------------------------------------------

  /**
   * Replaces the spinner dialog with a retry dialog after MAX_RECONNECT_ATTEMPTS.
   * The user can click "Retry" to reset the counter and try again.
   */
  private async _showRetryDialog(): Promise<void> {
    // If the global retry dialog is already open, just await it and reconnect.
    if (WebSocketProvider._retryDialogPromise) {
      await WebSocketProvider._retryDialogPromise;
      this._reconnectAttempts = 0;
      this._yWebsocketProvider?.connect();
      return;
    }

    // Otherwise open the global retry dialog.
    const body = new Widget();
    body.node.innerHTML = `
      <div style="padding:8px 0;">
        ${this._trans.__('Unable to reconnect to the server. Would you like to try again?')}
      </div>
    `;
    const dialog = new Dialog({
      title: this._trans.__('Document session error'),
      body,
      buttons: [Dialog.okButton({ label: this._trans.__('Reconnect') })],
      hasClose: false
    });
    WebSocketProvider._retryDialog = dialog;

    // Add a callback that clears the `_retryDialogPromise` global so future
    // disconnects show a new dialog, and set `_reconnectedManually` to true to
    // show a single notification on re-connection.
    WebSocketProvider._retryDialogPromise = dialog.launch().then(
      () => {
        WebSocketProvider._retryDialog = null;
        WebSocketProvider._retryDialogPromise = null;
        WebSocketProvider._reconnectedManually = true;
      },
      () => {
        // dialog.launch() rejects when dispose() is called while open.
        // Catching here ensures _retryDialogPromise always resolves.
        WebSocketProvider._retryDialog = null;
        WebSocketProvider._retryDialogPromise = null;
      }
    );

    // Wait until user clicks "Reconnect", then reconnect
    await WebSocketProvider._retryDialogPromise;
    this._reconnectAttempts = 0;
    this._yWebsocketProvider?.connect();
  }

  /**
   * Dismisses the shared reconnect dialog if one is showing.
   */
  private _dismissReconnectDialog(): void {
    WebSocketProvider._retryDialog?.dispose();
    WebSocketProvider._retryDialog = null;
    WebSocketProvider._retryDialogPromise = null;
  }

  /**
   * Handles an out-of-band move/deletion indicated by close code 4001.
   *
   * This always stops the provider from reconnecting. If the parent document
   * widget is open, this method also closes the tab and emits a warning
   * notification to the user.
   *
   * No notification is emitted if the document isn't open, since the user does
   * not need to be notified.
   */
  private _handleOobMove() {
    this._stopCloseAndNotify(
      `The file '${this._path}' no longer exists, and was either moved or deleted. The document tab has been closed.`
    );
  }

  /**
   * Handles an in-band deletion indicated by close code 4002. This behaves
   * similarly to `_handleOobMove()`, but with a different notification message.
   */
  private _handleIbDeletion() {
    this._stopCloseAndNotify(
      `The file '${this._path}' was deleted. The document tab has been closed.`
    );
  }

  /**
   * Stops the provider from reconnecting. If the parent document widget is
   * open, this method also closes the tab and emits a warning notification to
   * the user with the given message.
   */
  private _stopCloseAndNotify(message: string) {
    this._sharedModel.dispose();
    const documentWidget = this.parentDocumentWidget;
    if (documentWidget) {
      documentWidget.close();
      Notification.warning(message, {
        autoClose: 10000
      });
    }
  }

  private _onSync = (isSynced: boolean) => {
    if (isSynced) {
      if (this._yWebsocketProvider) {
        this._yWebsocketProvider.off('sync', this._onSync);
      }
      this._ready.resolve();
    }
  };

  private _app: JupyterFrontEnd;
  private _contentType: string;
  private _format: string;
  private _isDisposed: boolean;
  private _path: string;
  private _ready = new PromiseDelegate<void>();
  private _serverUrl: string;
  private _sharedModel: YDocument<DocumentChange>;
  private _yWebsocketProvider: YWebsocketProvider | null;
  private _trans: TranslationBundle;
  private _fileId: string | null = null;
  private _reconnectAttempts = 0;

  /**
   * Reference to the global retry dialog.
   */
  private static _retryDialog: Dialog<unknown> | null = null;

  /**
   * Promise that resolves when the user clicks "reconnect" in the global retry
   * dialog.
   */
  private static _retryDialogPromise: Promise<void> | null = null;

  /**
   * Stores whether the user clicked "reconnect" in the global retry dialog.
   * This is reset to false as soon as we show the "Connection restored"
   * notification, ensuring only one notification is shown per reconnection.
   */
  private static _reconnectedManually = false;
}

/**
 * A namespace for WebSocketProvider statics.
 */
export namespace WebSocketProvider {
  /**
   * The instantiation options for a WebSocketProvider.
   */
  export interface IOptions {
    /**
     * The top-level application. Used to close document tabs when the file was
     * deleted.
     */
    app: JupyterFrontEnd;
    /**
     * The server URL
     */
    url: string;

    /**
     * The document file path
     */
    path: string;

    /**
     * Content type
     */
    contentType: string;

    /**
     * The source format
     */
    format: string;

    /**
     * The shared model
     */
    model: YDocument<DocumentChange>;

    /**
     * The user data
     */
    user: User.IManager;

    /**
     * The jupyterlab translator
     */
    translator: TranslationBundle;
  }
}
