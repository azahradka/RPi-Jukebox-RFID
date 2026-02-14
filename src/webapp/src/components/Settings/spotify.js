import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  CardHeader,
  Chip,
  CircularProgress,
  Divider,
  Link,
  TextField,
  Typography,
} from '@mui/material';

import request from '../../utils/request';

/**
 * Extract the OAuth authorization code from a callback URL.
 * Accepts either a full URL (http://127.0.0.1:8888/callback?code=xxx)
 * or just the code value itself.
 */
function extractCode(input) {
  const trimmed = (input || '').trim();
  if (!trimmed) return null;

  // Try parsing as a URL with a ?code= param
  try {
    const url = new URL(trimmed);
    const code = url.searchParams.get('code');
    if (code) return code;
  } catch {
    // Not a valid URL — fall through
  }

  // If it looks like a bare code (no spaces, no '?' at start), accept it
  if (/^[A-Za-z0-9_-]+$/.test(trimmed)) {
    return trimmed;
  }

  return null;
}

const DASHBOARD_URL = 'https://developer.spotify.com/dashboard';
const REDIRECT_URI = 'http://127.0.0.1:8888/callback';

/**
 * Setup instructions rendered as a numbered list with a link to the
 * Spotify Developer Dashboard.
 */
const SetupInstructions = ({ t }) => (
  <Box component="ol" sx={{ pl: 2.5, my: 1, '& li': { mb: 0.5 } }}>
    <li>
      <Typography variant="body2" component="span">
        {t('settings.spotify.setup-step-1', 'Go to the Spotify Developer Dashboard and log in.')}{' '}
        <Link href={DASHBOARD_URL} target="_blank" rel="noopener">
          developer.spotify.com/dashboard
        </Link>
      </Typography>
    </li>
    <li>
      <Typography variant="body2" component="span">
        {t('settings.spotify.setup-step-2', 'Click "Create App".')}
      </Typography>
    </li>
    <li>
      <Typography variant="body2" component="span">
        {t('settings.spotify.setup-step-3', 'Set the Redirect URI to:')}{' '}
        <Typography variant="body2" component="code"
          sx={{ bgcolor: 'action.hover', px: 0.5, borderRadius: 0.5 }}
        >
          {REDIRECT_URI}
        </Typography>
      </Typography>
    </li>
    <li>
      <Typography variant="body2" component="span">
        {t('settings.spotify.setup-step-4', 'Select "Web API" when asked which APIs you will use.')}
      </Typography>
    </li>
    <li>
      <Typography variant="body2" component="span">
        {t('settings.spotify.setup-step-5', 'Copy the Client ID and Client Secret into the fields below.')}
      </Typography>
    </li>
  </Box>
);

const SettingsSpotify = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();

  // loading | authenticated | unauthenticated | unconfigured
  const [authStatus, setAuthStatus] = useState('loading');
  // idle | awaiting-paste | submitting
  const [connectState, setConnectState] = useState('idle');
  const [pasteValue, setPasteValue] = useState('');
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // Config form state
  const [showConfigForm, setShowConfigForm] = useState(false);
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');
  const [savingConfig, setSavingConfig] = useState(false);

  // Check auth status on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const { result } = await request('spotifyGetAuthStatus');
        if (result) {
          if (!result.configured) {
            setAuthStatus('unconfigured');
            setShowConfigForm(true);
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
    };

    checkAuth();
  }, []);

  // Load existing config when showing the form
  useEffect(() => {
    if (!showConfigForm) return;

    const loadConfig = async () => {
      try {
        const { result } = await request('spotifyGetConfig');
        if (result) {
          setClientId(result.client_id || '');
          // Don't pre-fill the secret field — show masked value as placeholder
        }
      } catch {
        // Ignore — form starts empty
      }
    };

    loadConfig();
  }, [showConfigForm]);

  // Handle legacy OAuth callback: detect spotify_code in URL params
  // (supports the nginx redirect flow if someone still has it configured)
  useEffect(() => {
    const spotifyCode = searchParams.get('spotify_code');
    if (!spotifyCode) return;

    const completeAuth = async () => {
      setConnectState('submitting');
      try {
        const { result } = await request('spotifyAuthenticate', {
          auth_code: spotifyCode,
        });
        if (result && result.success) {
          setAuthStatus('authenticated');
        } else {
          console.error('Spotify auth failed:', result);
          setAuthStatus('unauthenticated');
          setError(t('settings.spotify.auth-failed'));
        }
      } catch (err) {
        console.error('Spotify auth error:', err);
        setAuthStatus('unauthenticated');
        setError(t('settings.spotify.auth-failed'));
      } finally {
        setConnectState('idle');
        searchParams.delete('spotify_code');
        searchParams.delete('spotify_state');
        setSearchParams(searchParams, { replace: true });
      }
    };

    completeAuth();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSaveConfig = async () => {
    setError('');
    setSuccessMsg('');

    if (!clientId.trim() || !clientSecret.trim()) {
      setError(t('settings.spotify.config-required'));
      return;
    }

    setSavingConfig(true);
    try {
      const { result } = await request('spotifySetConfig', {
        client_id: clientId.trim(),
        client_secret: clientSecret.trim(),
      });
      if (result && result.success) {
        setSuccessMsg(t('settings.spotify.save-config-success'));
        setShowConfigForm(false);
        setClientSecret('');
        if (result.configured) {
          setAuthStatus('unauthenticated');
        }
      } else {
        setError(result?.error || t('settings.spotify.save-config-error'));
      }
    } catch (err) {
      console.error('Failed to save config:', err);
      setError(t('settings.spotify.save-config-error'));
    } finally {
      setSavingConfig(false);
    }
  };

  const handleConnect = async () => {
    setError('');
    setSuccessMsg('');
    try {
      const { result } = await request('spotifyGetAuthUrl');
      if (result && result.auth_url) {
        // Open Spotify auth in a new tab
        window.open(result.auth_url, '_blank', 'noopener');
        // Show the paste field
        setConnectState('awaiting-paste');
      }
    } catch (err) {
      console.error('Failed to get auth URL:', err);
    }
  };

  const handlePasteSubmit = async () => {
    setError('');
    const code = extractCode(pasteValue);
    if (!code) {
      setError(t('settings.spotify.paste-url-error'));
      return;
    }

    setConnectState('submitting');
    try {
      const { result } = await request('spotifyAuthenticate', {
        auth_code: code,
      });
      if (result && result.success) {
        setAuthStatus('authenticated');
        setConnectState('idle');
        setPasteValue('');
      } else {
        console.error('Spotify auth failed:', result);
        setError(t('settings.spotify.auth-failed'));
        setConnectState('awaiting-paste');
      }
    } catch (err) {
      console.error('Spotify auth error:', err);
      setError(t('settings.spotify.auth-failed'));
      setConnectState('awaiting-paste');
    }
  };

  const handleDisconnect = async () => {
    try {
      const { result } = await request('spotifyLogout');
      if (result && result.success) {
        setAuthStatus('unauthenticated');
        setConnectState('idle');
        setPasteValue('');
        setError('');
        setSuccessMsg('');
      }
    } catch (err) {
      console.error('Logout failed:', err);
    }
  };

  const statusChip = () => {
    if (authStatus === 'authenticated') {
      return <Chip label={t('settings.spotify.connected', 'Connected')} color="success" size="small" />;
    }
    if (authStatus === 'unconfigured') {
      return <Chip label={t('settings.spotify.unconfigured', 'Not Configured')} color="warning" size="small" />;
    }
    return <Chip label={t('settings.spotify.not-connected', 'Not Connected')} color="default" size="small" />;
  };

  return (
    <Card>
      <CardHeader
        title={t('settings.spotify.title', 'Spotify')}
        action={authStatus !== 'loading' ? statusChip() : null}
      />
      <Divider />
      <CardContent>
        {authStatus === 'loading' && (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
            <CircularProgress size={24} />
          </Box>
        )}

        {connectState === 'submitting' && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, p: 2 }}>
            <CircularProgress size={24} />
            <Typography>
              {t('settings.spotify.connecting', 'Connecting to Spotify...')}
            </Typography>
          </Box>
        )}

        {/* --- Config form (shown for unconfigured, or when editing) --- */}
        {authStatus !== 'loading' && connectState !== 'submitting' && showConfigForm && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {t('settings.spotify.unconfigured-hint')}
            </Typography>

            <SetupInstructions t={t} />

            <TextField
              fullWidth
              size="small"
              label={t('settings.spotify.client-id-label', 'Client ID')}
              value={clientId}
              onChange={(e) => { setClientId(e.target.value); setError(''); }}
              autoComplete="off"
            />
            <TextField
              fullWidth
              size="small"
              label={t('settings.spotify.client-secret-label', 'Client Secret')}
              value={clientSecret}
              onChange={(e) => { setClientSecret(e.target.value); setError(''); }}
              type="password"
              autoComplete="off"
              placeholder={authStatus !== 'unconfigured' ? '********' : ''}
            />

            {error && (
              <Alert severity="error" onClose={() => setError('')}>
                {error}
              </Alert>
            )}

            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              {authStatus !== 'unconfigured' && (
                <Button
                  variant="outlined"
                  onClick={() => {
                    setShowConfigForm(false);
                    setClientSecret('');
                    setError('');
                  }}
                >
                  {t('general.buttons.cancel', 'Cancel')}
                </Button>
              )}
              <Button
                variant="contained"
                onClick={handleSaveConfig}
                disabled={savingConfig}
              >
                {savingConfig ? <CircularProgress size={20} /> : t('settings.spotify.save-config', 'Save')}
              </Button>
            </Box>
          </Box>
        )}

        {/* --- Unconfigured but form not shown (shouldn't normally happen) --- */}
        {authStatus !== 'loading' && connectState !== 'submitting'
          && authStatus === 'unconfigured' && !showConfigForm && (
          <Typography variant="body2" color="text.secondary">
            {t('settings.spotify.unconfigured-hint')}
          </Typography>
        )}

        {/* --- Success message after saving config --- */}
        {successMsg && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccessMsg('')}>
            {successMsg}
          </Alert>
        )}

        {/* --- Connected --- */}
        {connectState !== 'submitting' && authStatus === 'authenticated' && !showConfigForm && (
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography>
              {t('settings.spotify.connected-hint')}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="outlined"
                size="small"
                onClick={() => setShowConfigForm(true)}
              >
                {t('settings.spotify.edit-config', 'Edit Credentials')}
              </Button>
              <Button
                variant="outlined"
                color="error"
                onClick={handleDisconnect}
              >
                {t('settings.spotify.disconnect', 'Disconnect')}
              </Button>
            </Box>
          </Box>
        )}

        {/* --- Not connected, ready to connect --- */}
        {connectState !== 'submitting' && authStatus === 'unauthenticated'
          && connectState === 'idle' && !showConfigForm && (
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Typography variant="body2" color="text.secondary">
              {t('settings.spotify.connect-hint')}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant="outlined"
                size="small"
                onClick={() => setShowConfigForm(true)}
              >
                {t('settings.spotify.edit-config', 'Edit Credentials')}
              </Button>
              <Button
                variant="contained"
                onClick={handleConnect}
              >
                {t('settings.spotify.connect', 'Connect Spotify')}
              </Button>
            </Box>
          </Box>
        )}

        {/* --- Awaiting paste of callback URL --- */}
        {connectState === 'awaiting-paste' && authStatus === 'unauthenticated' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {t('settings.spotify.paste-url-hint')}
            </Typography>
            <TextField
              fullWidth
              size="small"
              label={t('settings.spotify.paste-url-label', 'Paste callback URL here')}
              value={pasteValue}
              onChange={(e) => { setPasteValue(e.target.value); setError(''); }}
              placeholder="http://127.0.0.1:8888/callback?code=..."
              autoFocus
            />
            {error && (
              <Alert severity="error" onClose={() => setError('')}>
                {error}
              </Alert>
            )}
            <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
              <Button
                variant="outlined"
                onClick={() => { setConnectState('idle'); setPasteValue(''); setError(''); }}
              >
                {t('general.buttons.cancel', 'Cancel')}
              </Button>
              <Button
                variant="contained"
                onClick={handlePasteSubmit}
                disabled={!pasteValue.trim()}
              >
                {t('settings.spotify.paste-url-submit', 'Complete Connection')}
              </Button>
            </Box>
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

export default SettingsSpotify;
