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
 *   - Remove the ``awaiting-paste`` timeout effect:
 *     ``awaiting-paste auto-recovers after AWAITING_PASTE_TIMEOUT_MS`` fails
 *     (state stays in ``awaiting-paste`` past the 5-minute mark).
 */

import React, { useImperativeHandle, forwardRef } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import SpotifyAuthFlow from '../components/Settings/spotify/SpotifyAuthFlow';
import {
  __resetMockSocket,
  __setMockResponse,
  __mockSocketLog,
} from '../test-utils/mockSocket';

jest.mock('../sockets', () => require('../test-utils/mockSocket'));

const useSpotifyAuthModule = require('./useSpotifyAuth');
const useSpotifyAuth = useSpotifyAuthModule.default;
const { AWAITING_PASTE_TIMEOUT_MS } = useSpotifyAuthModule;

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

describe('useSpotifyAuth — awaiting-paste timeout', () => {
  beforeEach(() => {
    __resetMockSocket();
    jest.useFakeTimers();
  });

  afterEach(() => {
    // Drain any pending timers, then hand control back to real timers so
    // subsequent suites (and Jest internals) are not poisoned.
    act(() => { jest.runOnlyPendingTimers(); });
    jest.useRealTimers();
  });

  // Helper: drive the hook to ``awaiting-paste`` using real production
  // transitions — never a parallel-implementation harness (phase 3a pattern).
  const driveToAwaitingPaste = async (ref) => {
    let url;
    await act(async () => {
      url = await ref.current.beginConnect();
    });
    expect(url).toBe('https://accounts.spotify.com/authorize?x=1');
    expect(ref.current.connectState).toBe('awaiting-paste');
  };

  it('exposes a 5-minute timeout constant', () => {
    expect(AWAITING_PASTE_TIMEOUT_MS).toBe(5 * 60 * 1000);
  });

  it('awaiting-paste auto-recovers after AWAITING_PASTE_TIMEOUT_MS', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
    await driveToAwaitingPaste(ref);

    act(() => { jest.advanceTimersByTime(AWAITING_PASTE_TIMEOUT_MS); });

    expect(ref.current.connectState).toBe('idle');
    expect(ref.current.error).toBe('paste-timeout');
    // Session was never authenticated — the popup was closed without paste.
    expect(ref.current.authStatus).toBe('unauthenticated');
  });

  it('does not fire the timeout before AWAITING_PASTE_TIMEOUT_MS elapses', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
    await driveToAwaitingPaste(ref);

    act(() => { jest.advanceTimersByTime(AWAITING_PASTE_TIMEOUT_MS - 1000); });

    expect(ref.current.connectState).toBe('awaiting-paste');
    expect(ref.current.error).toBe('');
  });

  it('cancelPaste before the timeout cancels the pending timer', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
    await driveToAwaitingPaste(ref);

    act(() => { ref.current.cancelPaste(); });
    expect(ref.current.connectState).toBe('idle');
    expect(ref.current.error).toBe('');

    // Advance past the original timeout — the cancelled timer must not flip
    // the (now-stale) ``idle`` state into a ``paste-timeout`` error.
    act(() => { jest.advanceTimersByTime(AWAITING_PASTE_TIMEOUT_MS + 1000); });
    expect(ref.current.connectState).toBe('idle');
    expect(ref.current.error).toBe('');
  });

  it('successful submitPastedCode cancels the pending timer', async () => {
    __setMockResponse('player_spotify.ctrl.get_auth_status', { configured: true });
    __setMockResponse('player_spotify.ctrl.get_auth_url', {
      auth_url: 'https://accounts.spotify.com/authorize?x=1',
    });
    __setMockResponse('player_spotify.ctrl.authenticate', { success: true });
    const { ref } = mount();
    await waitFor(() => expect(ref.current.authStatus).toBe('unauthenticated'));
    await driveToAwaitingPaste(ref);

    await act(async () => {
      await ref.current.submitPastedCode('ABCDEF');
    });
    expect(ref.current.authStatus).toBe('authenticated');

    // The timer would otherwise fire and clobber ``error`` with
    // ``'paste-timeout'``. After cleanup it must not.
    act(() => { jest.advanceTimersByTime(AWAITING_PASTE_TIMEOUT_MS + 1000); });
    expect(ref.current.authStatus).toBe('authenticated');
    expect(ref.current.error).toBe('');
  });
});

describe('SpotifyAuthFlow — post-timeout error visibility', () => {
  // Integration check covering the seam between the hook and the
  // presentational component: when the 5-minute awaiting-paste timer
  // auto-recovers, ``connectState`` flips back to ``idle`` but
  // ``errorKey`` stays set to ``'paste-timeout'``. The UI must surface
  // that error inside the idle (unauthenticated) branch — otherwise the
  // user is silently dumped on the "Connect Spotify" button with no
  // indication that anything went wrong.
  //
  // Reversion check: drop the ``{errorKey && <Alert ... />}`` block from
  // the idle branch of ``SpotifyAuthFlow.js`` and this test fails
  // because the alert text can no longer be found in the DOM.
  it('renders timeout error in the idle branch after auto-recovery', () => {
    render(
      <SpotifyAuthFlow
        authStatus="unauthenticated"
        connectState="idle"
        errorKey="paste-timeout"
        onBeginConnect={() => Promise.resolve(null)}
        onSubmitPaste={() => Promise.resolve(false)}
        onCancelPaste={() => {}}
        onDisconnect={() => {}}
        onEditConfig={() => {}}
        onErrorCleared={() => {}}
      />
    );
    // The Alert renders via ``t(`settings.spotify.${errorKey}`, errorKey)``.
    // Without an i18next backend loaded in tests the default value
    // (the raw key) is returned, so we assert on ``paste-timeout`` text.
    const alert = screen.getByRole('alert');
    expect(alert).toBeInTheDocument();
    expect(alert).toHaveTextContent('paste-timeout');
    // The Connect button must still be present so the user can retry.
    expect(screen.getByRole('button', { name: /Connect Spotify/i })).toBeInTheDocument();
  });
});
