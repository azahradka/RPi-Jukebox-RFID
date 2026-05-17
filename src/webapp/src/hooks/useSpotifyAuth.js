import { useCallback, useEffect, useState } from 'react';

import request from '../utils/request';

/**
 * Maximum time (ms) the hook waits in ``awaiting-paste`` before assuming the
 * user closed the Spotify popup without completing the paste. Exposed as a
 * named export so tests can reference the exact value rather than re-deriving
 * it (and as documentation for the recovery window the UI implicitly grants).
 */
export const AWAITING_PASTE_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * State machine driving the Spotify OAuth + credentials flow.
 *
 * Phase 5b extracts the previously inline state machine from
 * ``SettingsSpotify`` (~480 LOC) so the flow can be tested independently of
 * the MUI presentation.
 *
 * States
 * ------
 *
 * ``authStatus``:
 *   - ``'loading'``         — mount; fetching ``spotifyGetAuthStatus``.
 *   - ``'unconfigured'``    — no client_id/secret on the backend.
 *   - ``'unauthenticated'`` — credentials configured but no valid token.
 *   - ``'authenticated'``   — valid token present.
 *
 * ``connectState`` (only meaningful in ``unauthenticated``):
 *   - ``'idle'``            — initial; show "Connect" button.
 *   - ``'awaiting-paste'``  — auth URL opened; waiting for user to paste
 *                              the callback URL.
 *   - ``'submitting'``      — completing the OAuth exchange.
 *
 * Transitions
 * -----------
 *
 *   mount                  -> refreshStatus() drives loading -> {un}configured/{un}authenticated.
 *   completeOAuthCallback  -> submitting; result -> authenticated | unauthenticated+error.
 *   beginConnect           -> fetch auth URL, open tab, -> awaiting-paste.
 *   submitPastedCode       -> submitting; result -> authenticated | (back to awaiting-paste)+error.
 *   cancelPaste            -> idle; clears pasted value + error.
 *   (timeout)              -> after ``AWAITING_PASTE_TIMEOUT_MS`` in
 *                              ``awaiting-paste``, the hook auto-returns to
 *                              ``idle`` with ``error = 'paste-timeout'`` so
 *                              users who closed the Spotify popup without
 *                              pasting are not stranded with no exit other
 *                              than ``cancelPaste``.
 *   disconnect             -> unauthenticated + idle.
 *   saveConfig             -> writes credentials; success -> unauthenticated; failure -> error preserved.
 *
 * Callbacks return a Promise so the presentational layer can ``await`` and
 * disable buttons during in-flight requests; throwing from a callback is
 * already handled internally and surfaced via ``error``.
 *
 * Reversion check: removing the ``completeOAuthCallback`` URL-cleanup
 * branch causes ``test_query_param_cleanup_after_oauth_success`` to fail.
 *
 * @param {object} deps
 * @param {(input: string) => string|null} deps.extractCode
 *   Pure helper to extract an auth code from the user's pasted URL or
 *   bare code. Hoisted so the hook stays independent of URL parsing.
 * @param {string|null|undefined} deps.spotifyCode
 *   OAuth ``?spotify_code=...`` value detected on the current URL by the
 *   presentational component (it owns the router). When present and
 *   truthy on first render, the hook completes the OAuth handshake.
 * @param {() => void} [deps.onOAuthCodeConsumed]
 *   Invoked after a ``spotify_code`` URL param has been processed so the
 *   presentational layer can scrub it from the URL.
 */
const useSpotifyAuth = ({
  extractCode,
  spotifyCode = null,
  onOAuthCodeConsumed = () => {},
} = {}) => {
  const [authStatus, setAuthStatus] = useState('loading');
  const [connectState, setConnectState] = useState('idle');
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const refreshStatus = useCallback(async () => {
    try {
      const { result } = await request('spotifyGetAuthStatus');
      if (result) {
        if (!result.configured) {
          setAuthStatus('unconfigured');
        } else if (result.authenticated) {
          setAuthStatus('authenticated');
        } else {
          setAuthStatus('unauthenticated');
        }
      } else {
        setAuthStatus('unauthenticated');
      }
    } catch {
      setAuthStatus('unauthenticated');
    }
  }, []);

  // Mount: check status once.
  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  // Legacy nginx-redirect OAuth flow: a ``spotify_code`` URL param has
  // dropped us back into the UI; complete the handshake automatically.
  useEffect(() => {
    if (!spotifyCode) return undefined;
    let cancelled = false;
    const run = async () => {
      setConnectState('submitting');
      try {
        const { result } = await request('spotifyAuthenticate', { auth_code: spotifyCode });
        if (cancelled) return;
        if (result && result.success) {
          setAuthStatus('authenticated');
          setError('');
        } else {
          setAuthStatus('unauthenticated');
          setError('auth-failed');
        }
      } catch {
        if (cancelled) return;
        setAuthStatus('unauthenticated');
        setError('auth-failed');
      } finally {
        if (!cancelled) {
          setConnectState('idle');
          onOAuthCodeConsumed();
        }
      }
    };
    run();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spotifyCode]);

  // Auto-recover from a stuck ``awaiting-paste`` state: if the user closes
  // the Spotify popup without pasting the callback URL there is otherwise
  // no exit besides explicitly clicking Cancel. After
  // ``AWAITING_PASTE_TIMEOUT_MS`` we flip back to ``idle`` and surface
  // ``error = 'paste-timeout'`` so the UI can prompt for a retry.
  //
  // Reversion check: removing this effect causes
  // ``awaiting-paste auto-recovers after AWAITING_PASTE_TIMEOUT_MS`` to fail.
  useEffect(() => {
    if (connectState !== 'awaiting-paste') return undefined;
    const handle = setTimeout(() => {
      setConnectState('idle');
      setError('paste-timeout');
    }, AWAITING_PASTE_TIMEOUT_MS);
    return () => clearTimeout(handle);
  }, [connectState]);

  const beginConnect = useCallback(async () => {
    setError('');
    setSuccessMsg('');
    try {
      const { result } = await request('spotifyGetAuthUrl');
      if (result && result.auth_url) {
        // Caller is responsible for opening the URL in a new tab so the
        // hook stays free of ``window``-side effects beyond what the UI
        // already controls.
        setConnectState('awaiting-paste');
        return result.auth_url;
      }
      return null;
    } catch {
      setError('auth-url-failed');
      return null;
    }
  }, []);

  const submitPastedCode = useCallback(async (pastedValue) => {
    setError('');
    const code = extractCode ? extractCode(pastedValue) : null;
    if (!code) {
      setError('paste-url-error');
      return false;
    }
    setConnectState('submitting');
    try {
      const { result } = await request('spotifyAuthenticate', { auth_code: code });
      if (result && result.success) {
        setAuthStatus('authenticated');
        setConnectState('idle');
        return true;
      }
      setError('auth-failed');
      setConnectState('awaiting-paste');
      return false;
    } catch {
      setError('auth-failed');
      setConnectState('awaiting-paste');
      return false;
    }
  }, [extractCode]);

  const cancelPaste = useCallback(() => {
    setConnectState('idle');
    setError('');
  }, []);

  const disconnect = useCallback(async () => {
    try {
      const { result } = await request('spotifyLogout');
      if (result && result.success) {
        setAuthStatus('unauthenticated');
        setConnectState('idle');
        setError('');
        setSuccessMsg('');
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  const saveConfig = useCallback(async ({ clientId, clientSecret }) => {
    setError('');
    setSuccessMsg('');
    const id = (clientId || '').trim();
    const secret = (clientSecret || '').trim();
    if (!id || !secret) {
      setError('config-required');
      return { ok: false, reason: 'config-required' };
    }
    try {
      const { result } = await request('spotifySetConfig', {
        client_id: id,
        client_secret: secret,
      });
      if (result && result.success) {
        setSuccessMsg('save-config-success');
        if (result.configured) {
          setAuthStatus('unauthenticated');
        }
        return { ok: true };
      }
      const reason = (result && result.error) || 'save-config-error';
      setError(reason);
      return { ok: false, reason };
    } catch {
      setError('save-config-error');
      return { ok: false, reason: 'save-config-error' };
    }
  }, []);

  const clearError = useCallback(() => setError(''), []);
  const clearSuccess = useCallback(() => setSuccessMsg(''), []);

  return {
    authStatus,
    connectState,
    error,
    successMsg,
    refreshStatus,
    beginConnect,
    submitPastedCode,
    cancelPaste,
    disconnect,
    saveConfig,
    clearError,
    clearSuccess,
  };
};

export default useSpotifyAuth;
