/**
 * @jest-environment node
 */

const {
  socketRequest,
  initSockets,
  __mockSocketLog,
  __setMockResponse,
  __resetMockSocket,
  __publishMockMessage,
} = require('./mockSocket');

describe('mockSocket', () => {
  beforeEach(() => {
    __resetMockSocket();
  });

  test('socketRequest resolves undefined when no response is configured', async () => {
    const result = await socketRequest('foo', 'bar', 'baz', {});
    expect(result).toBeUndefined();
    expect(__mockSocketLog).toEqual([{ key: 'foo.bar.baz', kwargs: {} }]);
  });

  test('__setMockResponse routes a configured value through', async () => {
    __setMockResponse('player.ctrl.play', { ok: true });
    const result = await socketRequest('player', 'ctrl', 'play', { card: '123' });
    expect(result).toEqual({ ok: true });
  });

  test('Error response rejects', async () => {
    __setMockResponse('thing.fail', new Error('boom'));
    await expect(socketRequest('thing', 'fail')).rejects.toThrow('boom');
  });

  test('initSockets registers a subscriber and __publishMockMessage delivers to it', () => {
    const setState = jest.fn();
    initSockets({ setState, events: ['playerstatus'] });

    __publishMockMessage('playerstatus', { state: 'play' });
    // setState is called with an updater; invoke it to inspect
    const updater = setState.mock.calls[0][0];
    expect(updater({})).toEqual({ playerstatus: { state: 'play' } });
  });

  test('__publishMockMessage ignores topics outside the subscriber list', () => {
    const setState = jest.fn();
    initSockets({ setState, events: ['volume'] });
    __publishMockMessage('playerstatus', { state: 'play' });
    expect(setState).not.toHaveBeenCalled();
  });
});
