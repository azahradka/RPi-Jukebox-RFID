import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  TextField,
  Typography,
} from '@mui/material';

import request from '../../../utils/request';
import SetupInstructions from './SetupInstructions';

/**
 * Form for entering Spotify client_id / client_secret credentials.
 * Presentational + local form state only — the actual save call is
 * delegated to ``onSave`` (provided by ``SettingsSpotify``, which wires
 * it to ``useSpotifyAuth.saveConfig``).
 *
 * Loads the existing client_id (read-only) on mount via
 * ``spotifyGetConfig`` so the user sees which dashboard app is wired up.
 * The secret field is never pre-filled — the backend only stores a
 * hash/redacted copy.
 *
 * Phase 5b: split from SettingsSpotify (~480 LOC monolith).
 */
const SpotifyConfigForm = ({
  authStatus,
  saving,
  errorKey,
  onSave,
  onCancel,
  onErrorCleared,
}) => {
  const { t } = useTranslation();
  const [clientId, setClientId] = useState('');
  const [clientSecret, setClientSecret] = useState('');

  // Load existing config (only the public client_id) on mount.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const { result } = await request('spotifyGetConfig');
        if (cancelled) return;
        if (result) setClientId(result.client_id || '');
      } catch {
        /* ignore — form starts empty */
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleSave = () => {
    onSave({ clientId, clientSecret }).then((res) => {
      if (res && res.ok) setClientSecret('');
    });
  };

  return (
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
        onChange={(e) => { setClientId(e.target.value); onErrorCleared(); }}
        autoComplete="off"
      />
      <TextField
        fullWidth
        size="small"
        label={t('settings.spotify.client-secret-label', 'Client Secret')}
        value={clientSecret}
        onChange={(e) => { setClientSecret(e.target.value); onErrorCleared(); }}
        type="password"
        autoComplete="off"
        placeholder={authStatus !== 'unconfigured' ? '********' : ''}
      />

      {errorKey && (
        <Alert severity="error" onClose={onErrorCleared}>
          {t(`settings.spotify.${errorKey}`, errorKey)}
        </Alert>
      )}

      <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        {authStatus !== 'unconfigured' && (
          <Button
            variant="outlined"
            onClick={() => { setClientSecret(''); onCancel(); }}
          >
            {t('general.buttons.cancel', 'Cancel')}
          </Button>
        )}
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? <CircularProgress size={20} /> : t('settings.spotify.save-config', 'Save')}
        </Button>
      </Box>
    </Box>
  );
};

export default SpotifyConfigForm;
