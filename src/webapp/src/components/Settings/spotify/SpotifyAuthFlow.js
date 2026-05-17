import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  TextField,
  Typography,
} from '@mui/material';

/**
 * Presentational driver for the Spotify OAuth flow. Renders one of three
 * sub-panels based on the state machine in ``useSpotifyAuth``:
 *
 *   - authenticated, idle    -> "Connected" + Edit/Disconnect.
 *   - unauthenticated, idle  -> "Connect Spotify" + Edit credentials.
 *   - awaiting-paste         -> paste textbox + Complete Connection.
 *
 * The ``submitting`` panel is rendered by the parent (SettingsSpotify)
 * because it sits above the form-vs-flow branch.
 *
 * Phase 5b: split from SettingsSpotify (~480 LOC monolith).
 */
const SpotifyAuthFlow = ({
  authStatus,
  connectState,
  errorKey,
  onBeginConnect,
  onSubmitPaste,
  onCancelPaste,
  onDisconnect,
  onEditConfig,
  onErrorCleared,
}) => {
  const { t } = useTranslation();
  const [pasteValue, setPasteValue] = useState('');

  // --- Connected (authenticated) ---
  if (authStatus === 'authenticated') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography>
          {t('settings.spotify.connected-hint')}
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" size="small" onClick={onEditConfig}>
            {t('settings.spotify.edit-config', 'Edit Credentials')}
          </Button>
          <Button variant="outlined" color="error" onClick={onDisconnect}>
            {t('settings.spotify.disconnect', 'Disconnect')}
          </Button>
        </Box>
      </Box>
    );
  }

  // --- Awaiting paste ---
  if (connectState === 'awaiting-paste') {
    return (
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <Typography variant="body2" color="text.secondary">
          {t('settings.spotify.paste-url-hint')}
        </Typography>
        <TextField
          fullWidth
          size="small"
          label={t('settings.spotify.paste-url-label', 'Paste callback URL here')}
          value={pasteValue}
          onChange={(e) => { setPasteValue(e.target.value); onErrorCleared(); }}
          placeholder="http://127.0.0.1:8888/callback?code=..."
          autoFocus
        />
        {errorKey && (
          <Alert severity="error" onClose={onErrorCleared}>
            {t(`settings.spotify.${errorKey}`, errorKey)}
          </Alert>
        )}
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button
            variant="outlined"
            onClick={() => { setPasteValue(''); onCancelPaste(); }}
          >
            {t('general.buttons.cancel', 'Cancel')}
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              onSubmitPaste(pasteValue).then((ok) => {
                if (ok) setPasteValue('');
              });
            }}
            disabled={!pasteValue.trim()}
          >
            {t('settings.spotify.paste-url-submit', 'Complete Connection')}
          </Button>
        </Box>
      </Box>
    );
  }

  // --- Submitting (in-flight OAuth handshake) ---
  if (connectState === 'submitting') {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, p: 2 }}>
        <CircularProgress size={24} />
        <Typography>
          {t('settings.spotify.connecting', 'Connecting to Spotify...')}
        </Typography>
      </Box>
    );
  }

  // --- Unauthenticated + idle ---
  // ``errorKey`` can leak into this branch when the awaiting-paste timer
  // auto-recovers (``connectState`` flips back to ``idle`` but the error
  // stays set so the user understands why their popup got cancelled).
  // Without the Alert below the user is silently dumped back on the
  // Connect button — defeating the whole "user not stranded" purpose.
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {errorKey && (
        <Alert severity="warning" onClose={onErrorCleared}>
          {t(`settings.spotify.${errorKey}`, errorKey)}
        </Alert>
      )}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Typography variant="body2" color="text.secondary">
          {t('settings.spotify.connect-hint')}
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" size="small" onClick={onEditConfig}>
            {t('settings.spotify.edit-config', 'Edit Credentials')}
          </Button>
          <Button
            variant="contained"
            onClick={() => {
              onBeginConnect().then((url) => {
                if (url) {
                  window.open(url, '_blank', 'noopener');
                }
              });
            }}
          >
            {t('settings.spotify.connect', 'Connect Spotify')}
          </Button>
        </Box>
      </Box>
    </Box>
  );
};

export default SpotifyAuthFlow;
