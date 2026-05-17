import React from 'react';
import { useTranslation } from 'react-i18next';
import { Chip } from '@mui/material';

/**
 * Presentational chip showing the current Spotify auth status.
 * Extracted from SettingsSpotify (Phase 5b).
 */
const SpotifyStatusDisplay = ({ authStatus }) => {
  const { t } = useTranslation();
  if (authStatus === 'authenticated') {
    return <Chip label={t('settings.spotify.connected', 'Connected')} color="success" size="small" />;
  }
  if (authStatus === 'unconfigured') {
    return <Chip label={t('settings.spotify.unconfigured', 'Not Configured')} color="warning" size="small" />;
  }
  return <Chip label={t('settings.spotify.not-connected', 'Not Connected')} color="default" size="small" />;
};

export default SpotifyStatusDisplay;
