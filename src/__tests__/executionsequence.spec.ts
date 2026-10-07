import { conflictMessage, ExecutionSequencer } from '../executionsequence';

describe('ExecutionSequencer', () => {
  it('counts up from 0 per key', () => {
    const sequencer = new ExecutionSequencer();
    expect(sequencer.claim('doc:1:k', '1')).toEqual({
      clientId: '1:0',
      sequence: 0
    });
    expect(sequencer.claim('doc:1:k', '1').sequence).toBe(1);
    expect(sequencer.claim('doc:1:k2', '1').sequence).toBe(0);
  });

  it('starts a reset key over under a new client id', () => {
    const sequencer = new ExecutionSequencer();
    sequencer.claim('doc:1:k', '1');
    const failed = sequencer.claim('doc:1:k', '1');

    sequencer.reset('doc:1:k', failed);

    expect(sequencer.claim('doc:1:k', '1')).toEqual({
      clientId: '1:1',
      sequence: 0
    });
  });

  it('gives a Run All burst after a reset its own client id', () => {
    // Every claim after the reset must share the new id, so the server
    // orders them against each other rather than against the old counter.
    const sequencer = new ExecutionSequencer();
    sequencer.reset('doc:1:k', sequencer.claim('doc:1:k', '1'));

    const burst = [0, 1, 2].map(() => sequencer.claim('doc:1:k', '1'));

    expect(burst.map(o => o.clientId)).toEqual(['1:1', '1:1', '1:1']);
    expect(burst.map(o => o.sequence)).toEqual([0, 1, 2]);
  });

  it('resets once for a burst whose requests all fail', () => {
    // The rest of the burst reports in after the first reset; those
    // failures belong to the old epoch and must not reset the new one.
    const sequencer = new ExecutionSequencer();
    const burst = [0, 1, 2].map(() => sequencer.claim('doc:1:k', '1'));

    sequencer.reset('doc:1:k', burst[0]);
    const next = sequencer.claim('doc:1:k', '1');
    sequencer.reset('doc:1:k', burst[1]);
    sequencer.reset('doc:1:k', burst[2]);

    expect(next).toEqual({ clientId: '1:1', sequence: 0 });
    expect(sequencer.claim('doc:1:k', '1')).toEqual({
      clientId: '1:1',
      sequence: 1
    });
  });

  it('ignores a reset without an order', () => {
    const sequencer = new ExecutionSequencer();
    sequencer.claim('doc:1:k', '1');
    sequencer.reset('doc:1:k', null);
    expect(sequencer.claim('doc:1:k', '1').clientId).toBe('1:0');
  });

  it('ignores a reset for a key it has never claimed', () => {
    const sequencer = new ExecutionSequencer();
    sequencer.reset('doc:1:k', { clientId: '1:0', sequence: 0 });
    expect(sequencer.claim('doc:1:k', '1')).toEqual({
      clientId: '1:0',
      sequence: 0
    });
  });
});

describe('conflictMessage', () => {
  it('blames the source for a source mismatch', () => {
    expect(
      conflictMessage({ error: 'source_mismatch', reason: undefined })
    ).toContain('cell source changed');
  });

  it('does not blame the kernel for a timed-out predecessor', () => {
    const message = conflictMessage({
      error: 'session_reset',
      reason: 'timeout'
    });
    expect(message).not.toContain('kernel');
    expect(message).toContain('did not reach the server');
  });

  it('blames the kernel for a reset', () => {
    expect(
      conflictMessage({ error: 'session_reset', reason: 'reset' })
    ).toContain('kernel changed');
  });
});
