/**
 * Ordering for server-side execute requests.
 *
 * Each key (document, client, kernel) gets a monotonic `sequence`. A reset
 * moves the key to a new epoch, which is folded into the `client_id` sent to
 * the server, so the next request starts a fresh server-side sequence instead
 * of relying on `sequence=0` arriving before its successors.
 */
export class ExecutionSequencer {
  /**
   * Claim the next slot for `key`.
   *
   * @param key - Identifies the (document, client, kernel) the counter covers.
   * @param clientId - The tab's client id; scoped by the current epoch.
   */
  claim(key: string, clientId: string): IExecutionOrder {
    let state = this._state.get(key);
    if (!state) {
      state = { clientId, epoch: 0, next: 0 };
      this._state.set(key, state);
    }
    return { clientId: scoped(state), sequence: state.next++ };
  }

  /**
   * Start `key` over under a new epoch after `order` failed, e.g. with a slot
   * the server may or may not have consumed.
   *
   * Only a failure from the current epoch resets: the rest of a failed burst
   * reports in after the first reset and must not reset again under requests
   * claimed since. A reset gives up ordering against the old epoch's
   * requests still in flight.
   */
  reset(key: string, order: IExecutionOrder | null): void {
    const state = this._state.get(key);
    if (state && order && order.clientId === scoped(state)) {
      state.epoch++;
      state.next = 0;
    }
  }

  private _state = new Map<string, ISequenceState>();
}

interface ISequenceState {
  clientId: string;
  epoch: number;
  next: number;
}

function scoped(state: ISequenceState): string {
  return `${state.clientId}:${state.epoch}`;
}

/**
 * The ordering fields of one execute request.
 */
export interface IExecutionOrder {
  clientId: string;
  sequence: number;
}

/**
 * The warning shown when the server rejects an execute request with a 409.
 */
export function conflictMessage(body: {
  error?: string;
  reason?: string;
}): string {
  if (body.error !== 'session_reset') {
    return 'Cell not executed: the cell source changed while the request was in flight. Please re-run the cell.';
  }
  if (body.reason === 'timeout') {
    return 'Cell not executed: an earlier run request did not reach the server in time. Please re-run the cell.';
  }
  return 'Cell not executed: the kernel changed while the request was in flight. Please re-run the cell.';
}
