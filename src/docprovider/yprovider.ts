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
import { YFile } from './custom_ydocs';

/**
 * A class to provide Yjs synchronization over WebSocket.
 *
 * We specify custom messages that the server can interpret. For reference please look in yjs_ws_server.
 *
 */

export class WebSocketProvider implements IDocumentProvider {
  /**
   * Construct a new WebSocketProvider
   *
   * @param options The instantiation options for a WebSocketProvider
   */
  constructor(options: WebSocketProvider.IOptions) {
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
    this._yWebsocketProvider?.off('connection-close', this._onConnectionClosed);
    this._yWebsocketProvider?.off('sync', this._onSync);
    this._yWebsocketProvider?.destroy();
    this._disconnect();
    Signal.clearData(this);
  }

  async reconnect(): Promise<void> {
    this._disconnect();
    this._connect();
  }

  private async _connect(): Promise<void> {
    // Fetch file ID from the file ID service.
    const resp = await requestAPI(`api/fileid/index?path=${this._path}`, {
      method: 'POST'
    });
    const fileId: string = resp['id'];

    this._yWebsocketProvider = new YWebsocketProvider(
      this._serverUrl,
      `${this._format}:${this._contentType}:${fileId}`,
      this._sharedModel.ydoc,
      {
        disableBc: true,
        // params: { sessionId: session.sessionId },
        awareness: this.awareness
      }
    );

    this._yWebsocketProvider.on('sync', this._onSync);
    this._yWebsocketProvider.on('connection-close', this._onConnectionClosed);
  }

  get wsProvider() {
    return this._yWebsocketProvider;
  }
  private _disconnect(): void {
    this._yWebsocketProvider?.off('connection-close', this._onConnectionClosed);
    this._yWebsocketProvider?.off('sync', this._onSync);
    this._yWebsocketProvider?.destroy();
    this._yWebsocketProvider = null;
  }

  private _onUserChanged(user: User.IManager): void {
    this.awareness.setLocalStateField('user', user.identity);
  }

  /**
   * Handles disconnections from the YRoom Websocket.
   *
   * TODO: Issue #45.
   */
  private _onConnectionClosed = (event: CloseEvent): void => {
    // Handle close events based on code
    const close_code = event.code;

    // 4000 := server close code on out-of-band change
    if (close_code === 4000 && this._sharedModel instanceof YFile) {
      this._handleOobChange();
      return;
    }

    // If the close code is unhandled, log an error to the browser console and
    // show a popup asking user to refresh the page.
    console.error('WebSocket connection was closed. Close event: ', event);
    showErrorMessage(
      this._trans.__('Document session error'),
      'Please refresh the browser tab.',
      [Dialog.okButton()]
    );

    // Stop `y-websocket` from re-connecting by disposing of the shared model.
    // This seems to be the only way to halt re-connection attempts.
    this._sharedModel.dispose();
  };

  /**
   * Handles an out-of-band change that requires reseting the YDoc before
   * re-connecting. The server extension indicates this by closing the YRoom
   * Websocket connection with close code 4000.
   */
  private _handleOobChange() {
    // Reset YDoc
    // TODO: handle YNotebooks.
    // TODO: is it safe to assume that we only need YFile & YNotebook?
    const sharedModel = this._sharedModel as YFile;
    sharedModel.reset();

    // Re-connect and display a notification to the user
    this.reconnect();
    Notification.info(
      'The contents of this file were changed on disk. The document state has been reset.',
      {
        autoClose: false
      }
    );
  }

  private _onSync = (isSynced: boolean) => {
    if (isSynced) {
      if (this._yWebsocketProvider) {
        this._yWebsocketProvider.off('sync', this._onSync);

        const state = this._sharedModel.ydoc.getMap('state');
        state.set('document_id', this._yWebsocketProvider.roomname);
      }
      this._ready.resolve();
    }
  };

  private _contentType: string;
  private _format: string;
  private _isDisposed: boolean;
  private _path: string;
  private _ready = new PromiseDelegate<void>();
  private _serverUrl: string;
  private _sharedModel: YDocument<DocumentChange>;
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment
  // @ts-ignore
  private _sharedModelFactory: ISharedModelFactory;
  private _yWebsocketProvider: YWebsocketProvider | null;
  private _trans: TranslationBundle;
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
