/**
 * Mock for the ZMQ sockets module used in React tests.
 *
 * Usage in a test file:
 *
 *     import {
 *       __mockSocketLog,
 *       __setMockResponse,
 *       __resetMockSocket,
 *     } from '../../test-utils/mockSocket';
 *     jest.mock('../../sockets', () => require('../../test-utils/mockSocket'));
 *
 * `socketRequest` returns the configured response for a given
 * `package.plugin.method` key, or `undefined` if none configured.
 * `initSockets` is a no-op.
 *
 * Tests should call `__resetMockSocket()` in `beforeEach` to clear state.
 */

const __mockSocketLog = [];
const __mockSocketResponses = {};
const __mockSubscribers = [];

const __setMockResponse = (key, response) => {
  __mockSocketResponses[key] = response;
};

const __resetMockSocket = () => {
  __mockSocketLog.length = 0;
  __mockSubscribers.length = 0;
  Object.keys(__mockSocketResponses).forEach((k) => delete __mockSocketResponses[k]);
};

// Note: do NOT wrap these in ``jest.fn(impl)``. Create React App 5 ships
// with ``resetMocks: true`` enabled by default, which clears all
// ``jest.fn`` implementations between tests. Plain functions keep their
// behavior across tests and let ``__mockSocketLog`` / response routing
// remain the source of truth for assertions.
const socketRequest = (_package, plugin, method, kwargs) => {
  const key = [_package, plugin, method].filter(Boolean).join('.');
  __mockSocketLog.push({ key, kwargs });
  if (key in __mockSocketResponses) {
    const resp = __mockSocketResponses[key];
    // A function lets a test return a *different* response per call —
    // including a manually-controlled Promise for race-condition tests.
    if (typeof resp === 'function') {
      const value = resp(kwargs);
      if (value && typeof value.then === 'function') return value;
      return value instanceof Error ? Promise.reject(value) : Promise.resolve(value);
    }
    return resp instanceof Error ? Promise.reject(resp) : Promise.resolve(resp);
  }
  return Promise.resolve(undefined);
};

const initSockets = ({ setState, events } = {}) => {
  __mockSubscribers.push({ setState, events });
};

/**
 * Simulate a pubsub push from the backend.
 * Calls every subscriber's setState with the given topic/data, matching
 * how the real socketEvents handler in src/sockets/index.js works.
 */
const __publishMockMessage = (topic, data) => {
  __mockSubscribers.forEach(({ setState, events }) => {
    if (!events || events.includes(topic)) {
      setState((state) => ({ ...state, [topic]: data }));
    }
  });
};

module.exports = {
  socketRequest,
  initSockets,
  __mockSocketLog,
  __mockSocketResponses,
  __setMockResponse,
  __resetMockSocket,
  __publishMockMessage,
};
