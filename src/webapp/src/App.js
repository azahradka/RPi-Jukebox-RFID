import React, { Suspense } from 'react';

import Grid from '@mui/material/Grid';

import AppSettingsProvider from './context/appsettings';
import PubSubProvider from './context/pubsub';
import PlayerProvider from './context/player';
import Router from './router';
import ErrorBoundary from './components/ErrorBoundary';

function App() {
  return (
    <PubSubProvider>
      <PlayerProvider>
        <AppSettingsProvider>
          <Grid
            alignItems="center"
            container
            direction="row"
            id="routes"
            justifyContent="center"
          >
            <Router />
          </Grid>
        </AppSettingsProvider>
      </PlayerProvider>
    </PubSubProvider>
  );
}

// here app catches the suspense from page in case translations are not yet loaded
// and the ErrorBoundary catches any uncaught RPC errors (Phase 1, fix #7)
export default function WrappedApp() {
  return (
    <ErrorBoundary>
      <Suspense fallback="Loading ...">
        <App />
      </Suspense>
    </ErrorBoundary>
  );
}
