/**
 * Tests for ``request`` — Phase 1, fix #7.
 *
 * The legacy ``catch`` branch returned ``{ error }`` which let every
 * caller silently swallow RPC failures. The new behaviour:
 *
 *   - successful responses still return ``{ result }``,
 *   - any failure (rejected promise from the socket or an in-band
 *     ``{ error }`` payload) now throws so the App.js error boundary
 *     can catch it,
 *   - ``{ swallow: true }`` opts back into the legacy shape for
 *     callers that genuinely want to handle the error inline.
 */

jest.mock('../sockets', () => require('../test-utils/mockSocket'));
jest.mock('../commands', () => ({
  __esModule: true,
  default: {
    fakeGet: { _package: 'pkg', plugin: 'plg', method: 'get' },
    fakeSet: { _package: 'pkg', plugin: 'plg', method: 'set' },
  },
}));

import request from './request';
import {
  __resetMockSocket,
  __setMockResponse,
} from '../test-utils/mockSocket';

describe('request (Phase 1: throw on error)', () => {
  beforeEach(() => {
    __resetMockSocket();
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    console.error.mockRestore();
  });

  it('returns { result } on success', async () => {
    __setMockResponse('pkg.plg.get', 'hello');
    const out = await request('fakeGet');
    expect(out).toEqual({ result: 'hello' });
  });

  it('throws when the socket promise rejects', async () => {
    __setMockResponse('pkg.plg.get', new Error('socket broken'));
    await expect(request('fakeGet')).rejects.toThrow('socket broken');
  });

  it('throws when the response payload carries an in-band error', async () => {
    __setMockResponse('pkg.plg.get', { error: 'plugin blew up' });
    await expect(request('fakeGet')).rejects.toThrow('plugin blew up');
  });

  it('throws when the command is not registered', async () => {
    await expect(request('nope')).rejects.toThrow(
      "'nope' does not exist in command object"
    );
  });

  it('preserves legacy shape with { swallow: true }', async () => {
    __setMockResponse('pkg.plg.get', new Error('boom'));
    const out = await request('fakeGet', {}, { swallow: true });
    expect(out.error).toBeInstanceOf(Error);
    expect(out.error.message).toBe('boom');
  });

  it('attaches command + rpcError on the thrown Error', async () => {
    __setMockResponse('pkg.plg.set', { error: { code: 'spotify_429' } });
    try {
      await request('fakeSet');
      throw new Error('should have thrown');
    } catch (e) {
      expect(e.command).toBe('fakeSet');
      expect(e.rpcError).toEqual({ code: 'spotify_429' });
    }
  });
});
