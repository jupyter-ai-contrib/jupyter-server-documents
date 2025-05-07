// Copyright (c) Jupyter Development Team.
// Distributed under the terms of the Modified BSD License.
import React from 'react';

import { ISessionContext } from '@jupyterlab/apputils';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import {
  VDomRenderer
} from '@jupyterlab/ui-components';

import { 
  Notebook, 
  ExecutionIndicatorComponent, 
  ExecutionIndicator as E,
} from '@jupyterlab/notebook';
import { Poll } from '@lumino/polling';


const EXECUTION_STATE_KEY = "executionState";


/**
 * A VDomRenderer widget for displaying the execution status.
 */

export class AwarenessExecutionIndicator extends VDomRenderer<AwarenessExecutionIndicator.Model> {
  /**
   * Construct the kernel status widget.
   */
  constructor(translator?: ITranslator, showProgress: boolean = true) {
    super(new AwarenessExecutionIndicator.Model());
    this.translator = translator || nullTranslator;
    this.addClass('jp-mod-highlighted');
  }

  /**
   * Render the execution status item.
   */
  render(): JSX.Element | null {
    if (this.model === null || !this.model.renderFlag) {
      return <div></div>;
    } else {
      const nb = this.model.currentNotebook;
      if (!nb) {
        return (
          <ExecutionIndicatorComponent
            displayOption={this.model.displayOption}
            state={undefined}
            translator={this.translator}
          />
        );
      }

      return (
        <ExecutionIndicatorComponent
          displayOption={this.model.displayOption}
          state={this.model.executionState(nb)}
          translator={this.translator}
        />
      );
    }
  }

  private translator: ITranslator;
}

export namespace AwarenessExecutionIndicator {

  export class Model extends E.Model {

    /**
     * A weak map to hold execution status of multiple notebooks.
     */
  
    attachNotebook(data: { content?: Notebook; context?: ISessionContext; } | null): void {
      let nb = data?.content;
      if (!nb) {
        return;
      }
      (this as any)._currentNotebook = nb;
      // Artificially toggle the execution state.
      new Poll({
        auto: true,
        factory: () => {
          let fullState = nb?.model?.sharedModel.awareness.getLocalState();
          let state = 'idle'
          if (fullState && fullState[EXECUTION_STATE_KEY] === "idle") {
            state = 'busy'
          }
          nb?.model?.sharedModel.awareness.setLocalState({ executionState: state}) 
          return Promise.resolve()
        },
        frequency: { interval: 2000, backoff: false }
      });
  
      (this as any)._notebookExecutionProgress.set(nb, {
        executionStatus: 'idle',
        kernelStatus: 'idle',
        totalTime: 0,
        interval: 0,
        timeout: 0,
        scheduledCell: new Set<string>(),
        scheduledCellNumber: 0, 
        needReset: true
      });
      const state = (this as any)._notebookExecutionProgress.get(nb);
  
      const contextStatusChanged = (ctx: ISessionContext) => {
        if (state) {
          let fullState = nb?.model?.sharedModel.awareness.getLocalState();
          if (fullState) {
            let currentState = fullState[EXECUTION_STATE_KEY];
            state.kernelStatus = currentState;
          }
        }
        this.stateChanged.emit(void 0);
      };
      
      nb?.model?.sharedModel.awareness.on('change', contextStatusChanged);
      super.attachNotebook(data);
    }
  }
}


