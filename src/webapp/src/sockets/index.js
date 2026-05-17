import { v4 as uuidv4 } from 'uuid';
import * as zmq from 'jszmq';

import {
  PUBSUB_ENDPOINT,
  REQRES_ENDPOINT,
  SUBSCRIPTIONS,
} from '../config';
import {
  decodeMessage,
  decodePubSubMessage,
  encodeMessage,
  preparePayload
} from './utils';

const socket_sub = new zmq.Sub();

SUBSCRIPTIONS.forEach(
  (topic) => socket_sub.subscribe(topic)
);

socket_sub.connect(PUBSUB_ENDPOINT);

const socketEvents = ({ setState, events = [] }) => {
  socket_sub.on('message', (_topic, _payload) => {
    const { topic, data, error } = decodePubSubMessage(_topic, _payload);

    if (events.includes(topic) && data) {
      setState(state => ({ ...state, [topic]: data }));
    }

    if (error) {
      // TODO: Better error handling
      console.error(`[PubSub][${topic}]: ${error}`);
    }
  });
};

const initSockets = ({ setState, events }) => {
  socketEvents({ setState, events });
};

/**
 * Phase 5b — long-lived REQ socket with serialized request queue and
 * per-request timeout.
 *
 * Previously, ``socketRequest`` created a fresh ``zmq.Req`` socket for
 * every call. With overlapping requests (volume slider + status poll +
 * search) the first response would race the others: ZMQ REQ sockets
 * require strict req→rep lockstep so this was always buggy. The
 * mitigation in the old code was "don't close the channel and hope" —
 * but pending callbacks could resolve against the wrong reply.
 *
 * The new design:
 *   1. One ``zmq.Req`` socket is created once and reused for the
 *      lifetime of the tab.
 *   2. Calls are pushed onto a FIFO queue and dispatched one at a time.
 *      A new send only happens after the previous reply arrives (or
 *      times out).
 *   3. Each send is matched against its request ``id`` so the reply
 *      cannot be misrouted, but with serial dispatch this is just a
 *      safety check.
 *   4. Each call has a per-request timeout (``timeoutMs``, default
 *      ``DEFAULT_TIMEOUT_MS``). On timeout the promise rejects so the
 *      UI can surface an error instead of hanging forever.
 *
 * Security notes (per phase 5 ``/security-review``):
 *   - The endpoint is a same-origin proxied WebSocket so no
 *     cross-origin amplification.
 *   - Each timeout reject clears its slot so a slow backend cannot DoS
 *     the queue indefinitely; subsequent requests proceed normally.
 *   - The serial queue means a flood of requests does not allocate
 *     extra sockets; the cost is bounded by the queue length only.
 */

export const DEFAULT_TIMEOUT_MS = 5000;

// Lazily-initialised module-scope state. Constructed on first call so
// tests that mock the ``../sockets`` module before any consumer imports
// never instantiate jszmq at all.
let _state = null;

const _initState = () => {
  if (_state) return _state;
  const server = new zmq.Req();
  _state = {
    server,
    /** Currently in-flight request, or null. */
    active: null,
    /** Pending requests, FIFO. */
    queue: [],
    /** True once we've tried to connect (regardless of outcome). */
    connected: false,
  };

  server.on('message', (msg) => {
    const { active } = _state;
    if (!active) return; // late reply after timeout — drop
    let decoded;
    try {
      decoded = decodeMessage(msg);
    } catch (err) {
      _settle(active, new Error('Failed to decode socket reply'));
      return;
    }
    const { id, error, result } = decoded;
    if (error && error.message) {
      _settle(active, new Error(error.message));
      return;
    }
    if (id && id === active.id) {
      _settle(active, null, result);
      return;
    }
    _settle(active, new Error('Received socket message ID does not match sender ID.'));
  });

  server.onerror = function (err) {
    const { active } = _state;
    if (active) _settle(active, err);
  };

  return _state;
};

const _settle = (slot, error, result) => {
  if (slot.settled) return;
  slot.settled = true;
  if (slot.timer) {
    clearTimeout(slot.timer);
    slot.timer = null;
  }
  if (_state) _state.active = null;
  if (error) slot.reject(error);
  else slot.resolve(result);
  _drain();
};

const _drain = () => {
  if (!_state || _state.active || _state.queue.length === 0) return;
  const next = _state.queue.shift();
  _dispatch(next);
};

const _dispatch = (slot) => {
  const state = _state;
  state.active = slot;

  if (!state.connected) {
    try {
      state.server.connect(REQRES_ENDPOINT);
      state.connected = true;
    } catch (error) {
      console.error(`WebSocket connection to '${REQRES_ENDPOINT}' failed: `, error);
      _settle(slot, error);
      return;
    }
  }

  slot.timer = setTimeout(() => {
    _settle(slot, new Error(`Request timed out after ${slot.timeoutMs}ms`));
  }, slot.timeoutMs);

  try {
    state.server.send(encodeMessage(slot.payload));
  } catch (err) {
    _settle(slot, err);
  }
};

/**
 * Issue a single RPC request through the shared REQ socket.
 *
 * @param {string} _package
 * @param {string} plugin
 * @param {string} method
 * @param {object} [kwargs]
 * @param {object} [options]
 * @param {number} [options.timeoutMs] Override the default 5s timeout.
 */
const socketRequest = (_package, plugin, method, kwargs, options) => {
  const state = _initState();
  const timeoutMs = (options && options.timeoutMs) || DEFAULT_TIMEOUT_MS;
  return new Promise((resolve, reject) => {
    const id = uuidv4();
    const payload = preparePayload(id, _package, plugin, method, kwargs);
    const slot = {
      id,
      payload,
      timeoutMs,
      resolve,
      reject,
      settled: false,
      timer: null,
    };
    state.queue.push(slot);
    _drain();
  });
};

// Test-only: reset the singleton between scenarios. Not part of the
// public API. Drains pending slots without surfacing unhandled
// rejections (any pending promise's rejection is swallowed; callers
// that still hold a reference must attach their own .catch).
const __resetSocketSingleton = () => {
  if (_state) {
    const drain = (slot) => {
      if (!slot || slot.settled) return;
      slot.settled = true;
      if (slot.timer) {
        clearTimeout(slot.timer);
        slot.timer = null;
      }
      // Resolve (rather than reject) so we never produce an unhandled
      // rejection from a leaked test request. Callers that depended on
      // the request should be racing on test teardown anyway.
      slot.resolve(undefined);
    };
    drain(_state.active);
    while (_state.queue.length) drain(_state.queue.shift());
  }
  _state = null;
};

export {
  initSockets,
  socketRequest,
  __resetSocketSingleton,
};
