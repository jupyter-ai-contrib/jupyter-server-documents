import {
  YFile as DefaultYFile,
  YNotebook as DefaultYNotebook,
  ISharedNotebook
} from '@jupyter/ydoc';
import * as Y from 'yjs';
import { Awareness } from 'y-protocols/awareness';
import { ISignal, Signal } from '@lumino/signaling';

export class YFile extends DefaultYFile {
  constructor() {
    super();
    this._resetSignal = new Signal(this);
  }

  /**
   * Resets the YDoc to an empty state and emits an event for consumers to
   * respond to via the `YFile.resetSignal`.
   *
   * This method should be called when the server's YDoc history changes. This
   * may happen when the server detects an out-of-band change to the file on
   * disk, or when the server needs to erase YDoc history to save memory.
   */
  reset() {
    // TODO (?): Remove *all* observers, including those added by consumers,
    // then re-add them. We only do this for observers added by default for now.
    // The issue is that Yjs does not provide methods for accessing the list of
    // observers or migrating them to a new `Y.Doc()` instance.

    // Remove default observers
    (this as any)._ystate.unobserve(this.onStateChanged);
    this.ysource.unobserve((this as any)._modelObserver);

    // Reset `this._ydoc` to an empty state
    (this as any)._ydoc = new Y.Doc();

    // Reset all properties derived from `this._ydoc`
    (this as any).ysource = this.ydoc.getText('source');
    (this as any)._ystate = this.ydoc.getMap('state');
    (this as any)._undoManager = new Y.UndoManager([], {
      trackedOrigins: new Set([this]),
      doc: (this as any)._ydoc
    });
    (this as any)._undoManager.addToScope(this.ysource);
    (this as any)._awareness = new Awareness(this.ydoc);

    // Emit to `this.resetSignal` to inform consumers immediately
    this._resetSignal.emit(null);

    // Add back default observers
    (this as any)._ystate.observe(this.onStateChanged);
    this.ysource.observe((this as any)._modelObserver);
  }

  /**
   * Signal that is emitted to whenever the YDoc is reset. Consumers should
   * listen to this signal if they need to act when the YDoc is reset.
   *
   * The Codemirror Yjs extension defined in `ybinding.ts` listens to this
   * signal to clear the editor when the YDoc is reset.
   */
  get resetSignal(): ISignal<this, null> {
    return this._resetSignal;
  }

  _resetSignal: Signal<this, null>;
}

export class YNotebook extends DefaultYNotebook {
  constructor(options?: Omit<ISharedNotebook.IOptions, 'data'>) {
    super(options);
    this._resetSignal = new Signal(this);
  }

  /**
   * See `YFile.reset()`.
   */
  reset() {
    // Remove default observers
    this._ycells.unobserve((this as any)._onYCellsChanged);
    this.ymeta.unobserveDeep((this as any)._onMetaChanged);
    (this as any)._ystate.unobserve(this.onStateChanged);

    // Reset `this._ydoc` to an empty state
    (this as any)._ydoc = new Y.Doc();

    // Reset all properties derived from `this._ydoc`
    (this as any)._ystate = this.ydoc.getMap('state');
    (this as any)._ycells = this.ydoc.getArray('cells');
    (this as any).cells = [];
    (this as any).ymeta = this.ydoc.getMap('meta');
    (this as any)._undoManager = new Y.UndoManager([], {
      trackedOrigins: new Set([this]),
      doc: (this as any)._ydoc
    });
    (this as any)._undoManager.addToScope(this._ycells);
    (this as any)._awareness = new Awareness(this.ydoc);

    // Emit to `this.resetSignal` to inform consumers immediately
    this._resetSignal.emit(null);

    // Add back default observers
    this._ycells.observe((this as any)._onYCellsChanged);
    this.ymeta.observeDeep((this as any)._onMetaChanged);
    (this as any)._ystate.observe(this.onStateChanged);
  }

  /**
   * See `YFile.resetSignal`.
   */
  get resetSignal(): ISignal<this, null> {
    return this._resetSignal;
  }

  _resetSignal: Signal<this, null>;
}
