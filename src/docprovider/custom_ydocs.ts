import {
  YFile as DefaultYFile
  // YNotebook as DefaultYNotebook
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
   * Resets the current YDoc.
   */
  reset() {
    /* TODO: Remove all existing observers ? */

    /* Constructor from YDocument */
    (this as any)._ydoc = new Y.Doc();
    (this as any)._ystate = (this as any)._ydoc.getMap('state');

    (this as any)._undoManager = new Y.UndoManager([], {
      trackedOrigins: new Set([this]),
      doc: (this as any)._ydoc
    });

    (this as any)._awareness = new Awareness((this as any)._ydoc);

    (this as any)._ystate.observe(this.onStateChanged);

    /* CUSTOM: Reset ysource */
    (this as any).ysource = (this as any)._ydoc.getText('source');
    this._resetSignal.emit(null);
    console.log('RESET YDOC.');
    console.log('new source', this.ysource.toString());

    /* CUSTOM (TODO ?): Migrate observers */
    // SEE RtcContentProvider._onChanged() in ydrive.ts

    /* Constructor from YFile */
    this.undoManager.addToScope(this.ysource);
    this.ysource.observe((this as any)._modelObserver);
  }

  get resetSignal(): ISignal<this, null> {
    return this._resetSignal;
  }

  setSource(value: string): void {
    console.log('SETTING SOURCE');
    console.log('from', this.ysource.toString());
    console.log('to', value);
    this.transact(() => {
      const ytext = this.ysource;
      ytext.delete(0, ytext.length);
      ytext.insert(0, value);
    });
  }

  _resetSignal: Signal<this, null>;
}
