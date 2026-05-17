/**
 * Behavioural tests for the Spotify auth state machine.
 *
 * Phase 5b — drives the real ``useSpotifyAuth`` hook from a probe
 * component that exposes the hook's value object on a ref. No
 * parallel-implementation harness (per phase 3a pattern).
 *
 * Reversion checks:
 *   - Remove ``setAuthStatus('authenticated')`` from ``submitPastedCode``:
 *     ``submitPastedCode marks the session authenticated on success`` fails.
 *   - Skip ``onOAuthCodeConsumed()`` in the URL-callback effect:
 *     ``URL-driven OAuth completion notifies the caller for cleanup`` fails.
 *   - Remove ``setAuthStatus('unauthenticated')`` from the failure branch:
 *     ``submitPastedCode returns to awaiting-paste on backend failure`` fails.
 */

import React, { useImperativeHandle, forwardRef } from 'react';
import { act, render, waitFor } from '@testing-library/react';

import {
  __resetMockSocket,
  __setMockResponse,
  __mockSocketLog,
} from '../test-utils/mockSocket';

jest.mock('../sockets', () => require('../test-utils/mockSocket'));

const useSpotifyAuth = require('./useSpotifyAuth').default;

const extractCode = (input) => {
  if (!input) return null;
  const trimmed = input.trim();
  try {
    const url = new URL(trimmed);
    const code = url.searchParams.get('code');
    if (code) return code;
  } catch {
    /* fall-through */
  }
  if (/^[A-Za-z0-9_-]+$/.test(trimmed)) return trimmed;
  return null;
};

const HookProbe = forwardRef(({ spotifyCode, onOAuthCodeConsumed }, ref) => {
  const api = useSpotifyAuth({ extractCode, spotifyCode, onOAuthCodeConsumed });
  useImperativeHandle(ref, () => api, [api]);
  return null;
});

const mount = ({ spotifyCode = null, onOAuthCodeConsumed = () => {} } = {}) => {
  const ref = React.createRef();
  const utils = render(
    <HookProbe ref={ref} spotifyCode={spotifyCode} onOAuthCodeConsumed={onOAuthCodeConsumed} />
  );
  return { ref, ...utils };
};

describe('useSpotifyAuth — initial status load', () => {
  beforeEach(() => __resetMockSocket());

  it('resolves to authenticated when backend reports configured + authenticated', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', {
      configured: true, authenticated: true,
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('authenticated'));
  });

  it('resolves to unconfigured when no credentials are configured', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: false });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unconfigured'));
  });

  it('resolves to unauthenticated when configured but no token', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', {
      configured: true, authenticated: false,
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
  });

  it('falls back to unauthenticated when the status call rejects', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', new Error('boom'));
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
  });
});

describe('useSpotifyAuth — connect flow', () => {
  beforeEach(() => __resetMockSocket());

  it('beginConnect transitions to awaiting-paste and returns the auth URL', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));

    let url;
    await act(async () => {
      url = await ref.current.beginConnect();
    });

    expect(url).toBe('https://accounts.spotify.com/authorize?x=1');
    expect(ref.current.connectState).toBe('awaiting-paste');
  });

  it('submitPastedCode marks the session authenticated on success', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.authenticate', { success: true });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));

    let ok;
    await act(async () => {
      ok = await ref.current.submitPastedCode('http://127.0.0.1:8888/callback?code=ABCDEF');
    });

    expect(ok).toBe(true);
    expect(ref.current.authStatus).toBe('authenticated');
    expect(ref.current.connectState).toBe('idle');
    const calls = __mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.authenticate');
    expect(calls[0].kwargs).toEqual({ auth_code: 'ABCDEF' });
  });

  it('submitPastedCode rejects a malformed paste before calling the backend', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));

    let ok;
    await act(async () => {
      ok = await ref.current.submitPastedCode('   bad stuff with spaces   ');
    });

    expect(ok).toBe(false);
    expect(ref.current.error).toBe('paste-url-error');
    expect(__mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.authenticate')).toHaveLength(0);
  });

  it('submitPastedCode returns to awaiting-paste on backend failure', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', { auth_url: 'https://x' });
    __setMockResponse('player_spotify.ctrl.authenticate', { success: false });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));

    await act(async () => { await ref.current.beginConnect(); });
    expect(ref.current.connectState).toBe('awaiting-paste');

    await act(async () => {
      await ref.current.submitPastedCode('ABCDEF');
    });
    expect(ref.current.connectState).toBe('awaiting-paste');
    expect(ref.current.authStatus).toBe('unauthenticated');
    expect(ref.current.error).toBe('auth-failed');
  });

  it('cancelPaste clears error and returns connectState to idle', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', { auth_url: 'https://x' });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
    await act(async () => { await ref.current.beginConnect(); });
    expect(ref.current.connectState).toBe('awaiting-paste');

    act(() => { ref.current.cancelPaste(); });
    expect(ref.current.connectState).toBe('idle');
    expect(ref.current.error).toBe('');
  });
});

describe('useSpotifyAuth — URL-driven OAuth callback', () => {
  beforeEach(() => __resetMockSocket());

  it('URL-driven OAuth completion notifies the caller for cleanup', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.authenticate', { success: true });
    const onConsumed = jest.fn();

    const { ref } = mount({ spotifyCode: 'XYZ123', onOAuthCodeConsumed: onConsumed });
    await waitFor(() => expect(ref.current.authStatus).toBe('authenticated'));
    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it('URL-driven OAuth failure leaves state unauthenticated and surfaces error', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.authenticate', { success: false });
    const { ref } = mount({ spotifyCode: 'XYZ123' });
    await waitFor(() => expect(ref.current.error).toBe('auth-failed'));
    expect(ref.current.authStatus).toBe('unauthenticated');
    expect(ref.current.connectState).toBe('idle');
  });
});

describe('useSpotifyAuth — disconnect + saveConfig', () => {
  beforeEach(() => __resetMockSocket());

  it('disconnect transitions from authenticated to unauthenticated', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true, authenticated: true });
    __setMockResponse('player_spotify.ctrl.logout', { success: true });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('authenticated'));

    let ok;
    await act(async () => { ok = await ref.current.disconnect(); });
    expect(ok).toBe(true);
    expect(ref.current.authStatus).toBe('unauthenticated');
  });

  it('saveConfig refuses empty credentials before hitting the backend', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: false });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unconfigured'));

    let res;
    await act(async () => {
      res = await ref.current.saveConfig({ clientId: '   ', clientSecret: '' });
    });
    expect(res).toEqual({ ok: false, reason: 'config-required' });
    expect(__mockSocketLog.filter((c) => c.key === 'player_spotify.ctrl.set_spotify_config')).toHaveLength(0);
  });

  it('saveConfig moves unconfigured -> unauthenticated on success', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: false });
    __setMockResponse('player_spotify.ctrl.set_spotify_config', { success: true, configured: true });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unconfigured'));

    let res;
    await act(async () => {
      res = await ref.current.saveConfig({ clientId: 'id', clientSecret: 'secret' });
    });
    expect(res).toEqual({ ok: true });
    expect(ref.current.authStatus).toBe('unauthenticated');
    expect(ref.current.successMsg).toBe('save-config-success');
  });
});
