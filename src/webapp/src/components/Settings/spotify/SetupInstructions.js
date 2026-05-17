import React from 'react';
import { Box, Link, Typography } from '@mui/material';

const DASHBOARD_URL = 'https://developer.spotify.com/dashboard';
export const REDIRECT_URI = 'http://127.0.0.1:8888/callback';

/**
 * Setup instructions rendered as a numbered list with a link to the
 * Spotify Developer Dashboard. Extracted from SettingsSpotify monolith
 * (Phase 5b); shared by the config form.
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

export default SetupInstructions;
