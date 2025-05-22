// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.

import { TextItem } from '@jupyterlab/statusbar';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import { VDomRenderer } from '@jupyterlab/ui-components';
import React, { KeyboardEvent } from 'react';
import { ISessionContext } from '@jupyterlab/apputils';
import { Widget } from '@lumino/widgets';
import { KernelStatus as K } from '@jupyterlab/apputils';
import { NotebookPanel } from '@jupyterlab/notebook';
import { Session } from '@jupyterlab/services';

/**
 * A pure functional component for rendering kernel status.
 */
function KernelStatusComponent(
  props: KernelStatusComponent.IProps
): React.ReactElement<KernelStatusComponent.IProps> {
  const translator = props.translator || nullTranslator;
  const trans = translator.load('jupyterlab');
  let statusText = '';
  if (props.status) {
    statusText = ` | ${props.status}`;
  }
  return (
    <TextItem
      onClick={props.handleClick}
      onKeyDown={props.handleKeyDown}
      source={`${props.kernelName}${statusText}`}
      title={trans.__('Change kernel for %1', props.activityName)}
      tabIndex={0}
    />
  );
}

/**
 * A namespace for KernelStatusComponent statics.
 */
namespace KernelStatusComponent {
  /**
   * Props for the kernel status component.
   */
  export interface IProps {
    /**
     * A click handler for the kernel status component. By default
     * we have it bring up the kernel change dialog.
     */
    handleClick: () => void;

    /**
     * A key down handler for the kernel status component. By default
     * we have it bring up the kernel change dialog.
     */
    handleKeyDown: (event: KeyboardEvent<HTMLImageElement>) => void;

    /**
     * The name the kernel.
     */
    kernelName: string;

    /**
     * The name of the activity using the kernel.
     */
    activityName: string;

    /**
     * The status of the kernel.
     */
    status?: string;

    /**
     * The application language translator.
     */
    translator?: ITranslator;
  }
}

export class AwarenessKernelStatus extends VDomRenderer<AwarenessKernelStatus.Model> {
  /**
   * Construct the kernel status widget.
   */
  constructor(opts: K.IOptions, translator?: ITranslator) {
    super(new AwarenessKernelStatus.Model(translator));
    this.translator = translator || nullTranslator;
    this._handleClick = opts.onClick;
    this._handleKeyDown = opts.onKeyDown;
    this.addClass('jp-mod-highlighted');
  }

  /**
   * Render the kernel status item.
   */
  render(): JSX.Element | null {
    if (this.model === null) {
      return null;
    } else {
      return (
        <KernelStatusComponent
          status={this.model.status}
          kernelName={this.model.kernelName}
          activityName={this.model.activityName}
          handleClick={this._handleClick}
          handleKeyDown={this._handleKeyDown}
          translator={this.translator}
        />
      );
    }
  }

  translator: ITranslator;
  private _handleClick: () => void;
  private _handleKeyDown: (event: KeyboardEvent<HTMLImageElement>) => void;
}

export namespace AwarenessKernelStatus {
  export class Model extends K.Model {
    attachDocument(widget: Widget | null) {
      if (!widget) {
        return;
      }
      const panel = widget as NotebookPanel;
      const stateChanged = () => {
        if (this) {
          const awarenessStates =
            panel?.model?.sharedModel.awareness.getStates();
          if (awarenessStates) {
            for (const [, clientState] of awarenessStates) {
              if ('kernel' in clientState) {
                (this as any)._kernelStatus =
                  clientState['kernel']['execution_state'];
                (this as any).stateChanged.emit(void 0);
                return;
              }
            }
          }
        }
      };
      panel.model?.sharedModel.awareness.on('change', stateChanged);
    }

    set sessionContext(sessionContext: ISessionContext | null) {
      const oldState = (this as any)._getAllState();
      (this as any)._sessionContext = sessionContext;
      (this as any)._kernelName =
        sessionContext?.kernelDisplayName ??
        (this as any)._trans.__('No Kernel');
      (this as any)._triggerChange(oldState, (this as any)._getAllState());
      sessionContext?.kernelChanged.connect(
        this._onKernelDisplayNameChanged,
        this
      );
    }
    /**
     * React to changes in the kernel.
     */
    private _onKernelDisplayNameChanged(
      _sessionContext: ISessionContext,
      change: Session.ISessionConnection.IKernelChangedArgs
    ) {
      const oldState = (this as any)._getAllState();

      // sync setting of status and display name
      (this as any)._kernelName = _sessionContext.kernelDisplayName;
      (this as any)._triggerChange(oldState, (this as any)._getAllState());
    }
  }
}
