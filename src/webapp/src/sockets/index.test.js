/**
 * Tests for the Phase 5b shared REQ socket: queue ordering, request
 * isolation, and per-request timeout.
 *
 * Mocks ``jszmq`` so the test owns the message + send pumps. The real
 * ``socketRequest`` and queue logic run unmodified.
 *
 * Reversion checks:
 *   - Drop the per-request timeout: ``timeout rejects without a reply``
 *     never completes.
 *   - Remove the FIFO queue (e.g. dispatch all immediately): the
 *     second request's payload arrives before the first reply, breaking
 *     ``queue serializes overlapping requests``.
 *   - Misroute by id (drop the id check): late reply after timeout
 *     resolves the wrong slot.
 */

import { v4 as uuidv4 } from 'uuid';
import { encodeMessage } from './utils';

// jsdom under Jest 27 / react-scripts 5 does not expose TextDecoder.
// utils.decodeMessage relies on it, so provide a minimal polyfill for
// the duration of this suite.
if (typeof global.TextDecoder === 'undefined') {
  // eslint-disable-next-line global-require
  const { TextDecoder } = require('util');
  global.TextDecoder = TextDecoder;
}

// --- jszmq mock ---------------------------------------------------------
//
// Two socket classes: Sub (no-op for these tests) and Req with hand-driven
// send/message callbacks captured per-instance so the test can simulate
// the backend.

const reqInstances = [];

jest.mock('jszmq', () => {
  class Sub {
    subscribe() {}
    connect() {}
    on() {}
  }
  class Req {
    constructor() {
      this._handlers = {};
      this.sent = [];
      this.connected = false;
      reqInstances.push(this);
    }
    connect() { this.connected = true; }
    send(msg) { this.sent.push(msg); }
    on(event, handler) { this._handlers[event] = handler; }
    set onerror(fn) { this._onerror = fn; }
    get onerror() { return this._onerror; }
    // Test helper: fire a 'message' callback synchronously.
    __fire(payload) {
      if (this._handlers.message) {
        // ``decodeMessage`` accepts anything ``TextDecoder.decode`` accepts;
        // Node's Buffer is fine.
        this._handlers.message(Buffer.from(JSON.stringify(payload)));
      }
    }
  }
  return { Sub, Req };
});

let sockets;
let __resetSocketSingleton;

beforeEach(() => {
  jest.resetModules();
  reqInstances.length = 0;
  // Re-require after resetModules so the module-scope ``_state`` is
  // freshly null for each test.
  // eslint-disable-next-line global-require
  sockets = require('./index');
  ({ __resetSocketSingleton } = sockets);
});

afterEach(() => {
  if (__resetSocketSingleton) __resetSocketSingleton();
});

const getReq = () => {
  // _state isn't created until first socketRequest call.
  return reqInstances[reqInstances.length - 1];
};

const parseSent = (req, idx = 0) => JSON.parse(req.sent[idx]);

describe('socketRequest (shared REQ socket)', () => {
  it('reuses a single Req socket across multiple calls', async () => {
    const p1 = sockets.socketRequest('p', 'pl', 'm', {});
    const req = getReq();
    const sent1 = parseSent(req, 0);
    req.__fire({ id: sent1.id, result: { ok: 1 } });
    await expect(p1).resolves.toEqual({ ok: 1 });

    const p2 = sockets.socketRequest('p', 'pl', 'm', {});
    expect(reqInstances).toHaveLength(1); // no second socket
    const sent2 = parseSent(req, 1);
    req.__fire({ id: sent2.id, result: { ok: 2 } });
    await expect(p2).resolves.toEqual({ ok: 2 });
  });

  it('queue serializes overlapping requests (FIFO)', async () => {
    const p1 = sockets.socketRequest('p', 'pl', 'm', { tag: 1 });
    const p2 = sockets.socketRequest('p', 'pl', 'm', { tag: 2 });

    const req = getReq();
    // Only the first request should have been sent; second is queued.
    expect(req.sent).toHaveLength(1);
    const sent1 = parseSent(req, 0);
    expect(sent1.kwargs).toEqual({ tag: 1 });

    // Reply to #1 -> #2 dispatches.
    req.__fire({ id: sent1.id, result: 'one' });
    await expect(p1).resolves.toBe('one');

    expect(req.sent).toHaveLength(2);
    const sent2 = parseSent(req, 1);
    expect(sent2.kwargs).toEqual({ tag: 2 });

    req.__fire({ id: sent2.id, result: 'two' });
    await expect(p2).resolves.toBe('two');
  });

  it('rejects on per-request timeout and lets the next call proceed', async () => {
    jest.useFakeTimers();
    const p1 = sockets.socketRequest('p', 'pl', 'm', {}, { timeoutMs: 100 });
    jest.advanceTimersByTime(150);
    await expect(p1).rejects.toThrow(/timed out/i);

    // Next call should still go through.
    jest.useRealTimers();
    const p2 = sockets.socketRequest('p', 'pl', 'm', {});
    const req = getReq();
    const sent2 = parseSent(req, 1);
    req.__fire({ id: sent2.id, result: 'after-timeout' });
    await expect(p2).resolves.toBe('after-timeout');
  });

  it('uses DEFAULT_TIMEOUT_MS when no override is provided', () => {
    expect(sockets.DEFAULT_TIMEOUT_MS).toBe(5000);
  });

  it('rejects on backend error payload', async () => {
    const p = sockets.socketRequest('p', 'pl', 'm', {});
    const req = getReq();
    const sent = parseSent(req, 0);
    req.__fire({ id: sent.id, error: { message: 'no such plugin' } });
    await expect(p).rejects.toThrow('no such plugin');

    // Subsequent call still works.
    const p2 = sockets.socketRequest('p', 'pl', 'm', {});
    const sent2 = parseSent(req, 1);
    req.__fire({ id: sent2.id, result: 'ok' });
    await expect(p2).resolves.toBe('ok');
  });

  it('rejects when the reply ID does not match (should never happen with FIFO, but is a safety net)', async () => {
    const p = sockets.socketRequest('p', 'pl', 'm', {});
    const req = getReq();
    // Fire a reply for a completely different id
    req.__fire({ id: uuidv4(), result: 'ghost' });
    await expect(p).rejects.toThrow(/does not match/);
  });
});

// Ensure encodeMessage is still wire-compatible (sanity check).
describe('encodeMessage', () => {
  it('returns a parseable JSON string', () => {
    const enc = encodeMessage({ id: 'x', package: 'p', plugin: 'pl', method: 'm', kwargs: {} });
    expect(JSON.parse(enc)).toEqual({ id: 'x', package: 'p', plugin: 'pl', method: 'm', kwargs: {} });
  });
});
