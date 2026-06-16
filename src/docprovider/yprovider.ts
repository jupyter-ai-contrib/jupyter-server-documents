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
import * as syncProtocol from 'y-protocols/sync';
import * as Y from 'yjs';
import * as encoding from 'lib0/encoding';
import * as decoding from 'lib0/decoding';
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

    // Override the sync message handler to prevent content duplication when
    // reconnecting to a server that recreated its YRoom (divergent CRDT
    // history).
    //
    // The handshake order is: the server sends its SS2 first, then its own SS1
    // (see `handle_sync_step1` in `yroom.py`). But the server's state vector —
    // which we need to detect divergence — only arrives in the SS1. So we must
    // process these in reverse: buffer the SS2 update, and once the SS1 lands,
    // determine whether the client's history has diverged from the server's,
    // tombstone our updates to prevent content duplication in this case, and
    // only after reply with our SS2.
    const messageSync = 0;

    // Holds the server's SS2 update until its following SS1 arrives. Set on
    // SS2, consumed on SS1, so it naturally resets each handshake.
    let pendingServerUpdate: Uint8Array | null = null;

    this._yWebsocketProvider.messageHandlers[messageSync] = (
      encoder: encoding.Encoder,
      decoder: decoding.Decoder,
      provider: YWebsocketProvider,
      emitSynced: boolean,
      _messageType: number
    ) => {
      const subType = decoding.readVarUint(decoder);

      switch (subType) {
        case syncProtocol.messageYjsSyncStep2: {
          // Defer: we cannot evaluate divergence until the server's SS1 (which
          // carries the server's state vector) arrives.
          pendingServerUpdate = decoding.readVarUint8Array(decoder);
          break;
        }

        case syncProtocol.messageYjsSyncStep1: {
          // The SS1 payload is the server's state vector.
          const serverStateVector = decoding.readVarUint8Array(decoder);

          // Apply the buffered SS2 now that divergence can be evaluated.
          const serverUpdate = pendingServerUpdate;
          pendingServerUpdate = null;

          if (!serverUpdate) {
            // The server should always send SS2 before its SS1 in our
            // architecture. Reaching here means that contract was violated. We
            // can emit a warning and return early if this occurs -- the
            // server's 5s handshake timeout will trigger a reconnection.
            console.warn(
              `[${this._path}] Received SyncStep1 with no preceding ` +
                'SyncStep2; skipping server-state application for this handshake.'
            );
            break;
          }

          // Apply the SS2 message received previously from the server,
          // resolving the histories by tombstoning our YDoc items if divergent.
          const divergent = hasDivergentHistory(
            provider.doc,
            serverStateVector
          );
          applyServerUpdate(provider.doc, serverUpdate, divergent, provider);
          if (emitSynced && !provider.synced) {
            provider.synced = true;
          }

          // Reply with the SS2 response to the server's SS1 message.
          encoding.writeVarUint(encoder, messageSync);
          syncProtocol.writeSyncStep2(encoder, provider.doc, serverStateVector);
          break;
        }

        case syncProtocol.messageYjsUpdate: {
          syncProtocol.readUpdate(decoder, provider.doc, provider);
          break;
        }
      }
    };

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
      title: this._trans.__('Connection Error'),
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

/**
 * Returns whether the client's history has diverged from the server's: i.e.
 * the client's state vector contains a clientID the server's state vector does
 * not recognize.
 *
 * Such a clientID can only originate from a previous server session (the
 * current session loads its content from disk under a fresh clientID), so
 * syncing without intervention would duplicate content. Note that `self` is
 * intentionally NOT excluded: a single client that authored all content and
 * then reconnected to a recreated server session holds that content solely
 * under its own clientID, and the server has re-authored the equivalent
 * content under a new ID — so failing to clear would duplicate it.
 */
function hasDivergentHistory(
  doc: Y.Doc,
  serverStateVector: Uint8Array
): boolean {
  const clientSV = Y.decodeStateVector(Y.encodeStateVector(doc));
  const serverSV = Y.decodeStateVector(serverStateVector);
  for (const clientId of clientSV.keys()) {
    if (!serverSV.has(clientId)) {
      return true;
    }
  }
  return false;
}

/**
 * Applies the server's SS2 update to the doc.
 *
 * When `divergent` is false this is a plain `Y.applyUpdate`, preserving any
 * local/offline edits.
 *
 * When `divergent` is true, the client's history has diverged from the
 * server's (the server recreated its YRoom). We clear the content of every
 * top-level ordered shared type and apply the server state within a single
 * transaction, so the client defers to the server's state in one atomic net
 * update. Local edits never synced to the server are intentionally sacrificed
 * (the persisted file is the source of truth).
 *
 * Key-based content (`Y.Map` entries, `Y.XmlElement` attributes) is left
 * untouched — see `clearSharedType`. Deleting a key tombstones the client's
 * item for it, and Yjs reads a key as the *rightmost* item or `undefined` if
 * that item is deleted; it does not fall back to a live concurrent item. So if
 * the client's clientID outranks the server's, the cleared key reads as
 * ABSENT even though the server has a value — silently dropping e.g.
 * `metadata`/`kernelspec` ~half the time. Leaving the key lets the server's
 * value resolve via last-writer-wins, which keeps it present. (Maps don't
 * duplicate, so they never needed clearing for correctness anyway.)
 *
 * `origin` is forwarded as the transaction origin so the resulting update is
 * attributed to the provider and not re-broadcast to the server as a separate
 * update message; in the divergent case the tombstones reach the server via
 * the SS2 reply instead.
 */
function applyServerUpdate(
  doc: Y.Doc,
  serverUpdate: Uint8Array,
  divergent: boolean,
  origin?: unknown
): void {
  if (!divergent) {
    Y.applyUpdate(doc, serverUpdate, origin);
    return;
  }

  doc.transact(() => {
    for (const [, type] of doc.share) {
      clearSharedType(type);
    }
    Y.applyUpdate(doc, serverUpdate);
  }, origin);
}

/**
 * Clears the ordered content of a top-level Yjs shared type so the server's
 * state (applied next) replaces it. Considers every Yjs shared type:
 *
 *  - Ordered types — content is cleared:
 *      - `Y.Array`, `Y.Text` (and `Y.XmlText`, which extends it): delete the
 *        full index range.
 *      - `Y.XmlElement` / `Y.XmlFragment` (`Y.XmlElement` extends
 *        `Y.XmlFragment`): delete all child nodes.
 *  - Key-based content — intentionally left intact:
 *      - `Y.Map` entries (and `Y.XmlHook`, which extends `Y.Map`), and
 *        `Y.XmlElement` attributes.
 *    Deleting a key tombstones the client's item; if its clientID outranks the
 *    server's concurrent item, Yjs returns the deleted item as the key's entry
 *    and the key reads as absent — silently dropping it ~half the time. Leaving
 *    it lets the server's value resolve via last-writer-wins (never absent).
 *    Key-based types don't duplicate, so they never needed clearing anyway.
 */
function clearSharedType(type: Y.AbstractType<any>): void {
  // Key-based: skip (clearing can drop the key entirely — see above).
  if (type instanceof Y.Map) {
    return;
  }

  // Ordered: clear the full sequence. `Y.Text` also covers `Y.XmlText`.
  if (type instanceof Y.Array || type instanceof Y.Text) {
    type.delete(0, type.length);
    return;
  }

  // `Y.XmlElement` extends `Y.XmlFragment`. Clear child nodes only; element
  // attributes are key-based and left intact for the reason above.
  if (type instanceof Y.XmlFragment) {
    type.delete(0, type.length);
    return;
  }
}
