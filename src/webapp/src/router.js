import React from 'react'
import { Route, HashRouter, Routes } from 'react-router-dom'

import Cards from './components/Cards';
import ErrorBoundary from './components/ErrorBoundary';
import Library from './components/Library';
import Navigation from './components/Navigation';
import Player from './components/Player'
import Settings from './components/Settings'

import Grid from '@mui/material/Grid';

// Phase 4: per-page error boundaries. The top-level ``ErrorBoundary`` in
// ``App.js`` (Phase 1) catches the whole app; the page-scoped boundaries
// below let a failure in one page (e.g. Library) keep the rest of the
// app — including the Navigation bar — usable. Each boundary renders a
// scoped fallback labelled by its page name.
const Router = () => {
  return (
    <HashRouter>
      <Grid
        item xs={12}
        md={6}
        sx={{
          marginBottom: '64px',
        }}
      >
        <Routes>
          <Route
            index
            element={
              <ErrorBoundary scope="Player">
                <Player />
              </ErrorBoundary>
            }
            exact
          />
          <Route
            path="library/*"
            element={
              <ErrorBoundary scope="Library">
                <Library />
              </ErrorBoundary>
            }
          />
          <Route
            path="cards/*"
            element={
              <ErrorBoundary scope="Cards">
                <Cards />
              </ErrorBoundary>
            }
          />
          <Route
            path="settings/*"
            element={
              <ErrorBoundary scope="Settings">
                <Settings />
              </ErrorBoundary>
            }
            exact
          />
        </Routes>
      </Grid>
      <Navigation />
    </HashRouter>
  );
}

export default Router;
