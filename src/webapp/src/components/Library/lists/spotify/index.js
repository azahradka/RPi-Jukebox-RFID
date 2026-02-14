import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  Paper,
  Tab,
  Tabs,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import SettingsIcon from '@mui/icons-material/Settings';

import SpotifySearch from './spotify-search';
import SpotifyUserLibrary from './spotify-user-library';
import SpotifyContentDetail from './spotify-content-detail';
import { buildActionData } from '../../../Cards/utils';
import request from '../../../../utils/request';

const Spotify = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [currentTab, setCurrentTab] = useState('search');
  const [selectedContent, setSelectedContent] = useState(null);
  const [authStatus, setAuthStatus] = useState('loading');

  const isSelecting = searchParams.get('isSelecting') === 'true';
  const cardId = searchParams.get('cardId');

  useEffect(() => {
    const checkAuth = async () => {
      try {
        const { result } = await request('spotifyGetAuthStatus');
        if (result && result.authenticated) {
          setAuthStatus('authenticated');
        } else {
          setAuthStatus('unauthenticated');
        }
      } catch {
        setAuthStatus('unauthenticated');
      }
    };
    checkAuth();
  }, []);

  const handleTabChange = (event, newValue) => {
    setCurrentTab(newValue);
    setSelectedContent(null);
  };

  const handleSelectContent = (item) => {
    if (item.type === 'track' || item.type === 'episode') {
      // Tracks and episodes: action immediately
      if (isSelecting) {
        handleAssignToCard(item.uri, item);
      } else {
        handlePlay(item.uri);
      }
    } else {
      // Playlists, albums, shows: drill into detail view
      setSelectedContent(item);
    }
  };

  const handlePlay = async (uri) => {
    try {
      await request('spotifyPlayContent', { uri });
    } catch (error) {
      console.error('Failed to play Spotify content:', error);
    }
  };

  const handleAssignToCard = (uri, metadata) => {
    const actionData = buildActionData('play_spotify', 'play_spotify_card', [uri]);
    const state = {
      registerCard: {
        actionData,
        cardId,
        spotifyMetadata: {
          name: metadata.name,
          artist: metadata.artist,
          image_url: metadata.image_url,
          type: metadata.type,
          uri: metadata.uri,
        },
      },
    };
    navigate('/cards/register', { state });
  };

  if (authStatus === 'loading') {
    return null;
  }

  if (authStatus === 'unauthenticated') {
    return (
      <Box sx={{ width: '100%', textAlign: 'center', py: 4 }}>
        <Typography variant="h6" color="text.secondary" gutterBottom>
          {t('spotify.not-connected', 'Spotify is not connected')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('spotify.connect-first', 'Connect your Spotify account in Settings to browse and play music.')}
        </Typography>
        <Button
          variant="contained"
          startIcon={<SettingsIcon />}
          onClick={() => navigate('/settings')}
        >
          {t('spotify.go-to-settings', 'Go to Settings')}
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%' }}>
      {!selectedContent && (
        <Paper sx={{ mb: 2 }}>
          <Tabs
            value={currentTab}
            onChange={handleTabChange}
            indicatorColor="primary"
            textColor="primary"
            centered
          >
            <Tab
              label={t('spotify.tabs.search', 'Search')}
              value="search"
            />
            <Tab
              label={t('spotify.tabs.library', 'My Library')}
              value="library"
            />
          </Tabs>
        </Paper>
      )}

      {!selectedContent && currentTab === 'search' && (
        <SpotifySearch
          isSelecting={isSelecting}
          onSelectContent={handleSelectContent}
          onPlay={handlePlay}
        />
      )}

      {!selectedContent && currentTab === 'library' && (
        <SpotifyUserLibrary
          isSelecting={isSelecting}
          onSelectContent={handleSelectContent}
          onPlay={handlePlay}
        />
      )}

      {selectedContent && (
        <Box>
          <Box sx={{ mb: 2 }}>
            <Button
              variant="text"
              onClick={() => setSelectedContent(null)}
              startIcon={<ArrowBackIcon />}
            >
              {t('spotify.back', 'Back')}
            </Button>
          </Box>

          <SpotifyContentDetail
            content={selectedContent}
            isSelecting={isSelecting}
            onPlay={handlePlay}
            onAssignToCard={handleAssignToCard}
          />
        </Box>
      )}
    </Box>
  );
};

export default Spotify;
