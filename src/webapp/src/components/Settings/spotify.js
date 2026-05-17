import React, { useCallback, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  Alert,
  Box,
  Card,
  CardContent,
  CardHeader,
  CircularProgress,
  Divider,
} from '@mui/material';

import useSpotifyAuth from '../../hooks/useSpotifyAuth';
import { extractCode } from './spotify/extractCode';
import SpotifyAuthFlow from './spotify/SpotifyAuthFlow';
import SpotifyConfigForm from './spotify/SpotifyConfigForm';
import SpotifyStatusDisplay from './spotify/SpotifyStatusDisplay';

/**
 * SettingsSpotify — top-level Settings card for the Spotify integration.
 *
 * Phase 5b refactor: the original ~480 LOC monolith has been split into:
 *
 *   - ``hooks/useSpotifyAuth``        state machine (status + connect flow)
 *   - ``spotify/SpotifyAuthFlow``     connect/disconnect/paste UI
 *   - ``spotify/SpotifyConfigForm``   credentials form
 *   - ``spotify/SpotifyStatusDisplay`` status chip
 *   - ``spotify/SetupInstructions``   dashboard setup steps
 *   - ``spotify/extractCode``         pure helper (testable, no React)
 *
 * The public API is unchanged: a default-exported component taking no
 * props. ``components/Settings/index.js`` imports it the same way.
 */
const SettingsSpotify = () => {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [showConfigForm, setShowConfigForm] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);

  // OAuth callback detection (router-driven; the hook is router-agnostic).
  const spotifyCode = searchParams.get('spotify_code');
  const onOAuthCodeConsumed = useCallback(() => {
    searchParams.delete('spotify_code');
    searchParams.delete('spotify_state');
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const {
    authStatus,
    connectState,
    error,
    successMsg,
    beginConnect,
    submitPastedCode,
    cancelPaste,
    disconnect,
    saveConfig,
    clearError,
    clearSuccess,
  } = useSpotifyAuth({
    extractCode,
    spotifyCode,
    onOAuthCodeConsumed,
  });

  // Show the config form automatically when we first detect unconfigured.
  // ``useMemo`` keeps the derived flag stable so the form doesn't remount.
  const formVisible = useMemo(() => (
    showConfigForm || authStatus === 'unconfigured'
  ), [showConfigForm, authStatus]);

  const handleSave = useCallback(async ({ clientId, clientSecret }) => {
    setSavingConfig(true);
    try {
      const res = await saveConfig({ clientId, clientSecret });
      if (res.ok) {
        setShowConfigForm(false);
      }
      return res;
    } finally {
      setSavingConfig(false);
    }
  }, [saveConfig]);

  const showLoading = authStatus === 'loading';
  const showSubmitting = connectState === 'submitting';

  return (
    <Card>
      <CardHeader
        title={t('settings.spotify.title', 'Spotify')}
        action={!showLoading ? <SpotifyStatusDisplay authStatus={authStatus} /> : null}
      />
      <Divider />
      <CardContent>
        {showLoading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
            <CircularProgress size={24} />
          </Box>
        )}

        {successMsg && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={clearSuccess}>
            {t(`settings.spotify.${successMsg}`, successMsg)}
          </Alert>
        )}

        {!showLoading && formVisible && (
          <SpotifyConfigForm
            authStatus={authStatus}
            saving={savingConfig}
            errorKey={error}
            onSave={handleSave}
            onCancel={() => setShowConfigForm(false)}
            onErrorCleared={clearError}
          />
        )}

        {!showLoading && !formVisible && (
          <SpotifyAuthFlow
            authStatus={authStatus}
            connectState={connectState}
            errorKey={showSubmitting ? '' : error}
            onBeginConnect={beginConnect}
            onSubmitPaste={submitPastedCode}
            onCancelPaste={cancelPaste}
            onDisconnect={disconnect}
            onEditConfig={() => setShowConfigForm(true)}
            onErrorCleared={clearError}
          />
        )}
      </CardContent>
    </Card>
  );
};

export default SettingsSpotify;
