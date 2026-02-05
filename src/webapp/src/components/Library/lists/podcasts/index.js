import React, { useState } from 'react';
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

import PodcastSearch from './podcast-search';
import EpisodeList from './episode-list';
import { buildActionData } from '../../../Cards/utils';

const Podcasts = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [currentTab, setCurrentTab] = useState('search');
  const [selectedPodcast, setSelectedPodcast] = useState(null);

  const isSelecting = searchParams.get('isSelecting') === 'true';
  const cardId = searchParams.get('cardId');

  const handleTabChange = (event, newValue) => {
    setCurrentTab(newValue);
    setSelectedPodcast(null);
  };

  const handleSelectPodcast = (podcast) => {
    if (isSelecting) {
      // User is registering a card - show episode selection
      setSelectedPodcast(podcast);
    } else {
      // Normal browsing - show episodes
      setSelectedPodcast(podcast);
    }
  };

  const handleSelectEpisode = (episode) => {
    if (isSelecting && selectedPodcast) {
      // Register specific episode to card
      const actionData = buildActionData(
        'play_podcast',
        'play_podcast_episode',
        [selectedPodcast.feed_url, episode.guid]
      );

      const state = {
        registerCard: {
          actionData,
          cardId,
          podcastMetadata: {
            title: selectedPodcast.title,
            author: selectedPodcast.author,
            image_url: selectedPodcast.image_url,
            feed_url: selectedPodcast.feed_url,
            episode: {
              title: episode.title,
              guid: episode.guid,
            },
          },
        },
      };

      console.log('Navigating with episode actionData:', actionData);
      navigate('/cards/register', { state });
    } else {
      // Play episode now (future enhancement - would call RPC to play)
      console.log('Play episode:', episode);
    }
  };

  const handleSelectSeries = () => {
    if (isSelecting && selectedPodcast) {
      // Register entire series to card
      const actionData = buildActionData(
        'play_podcast',
        'play_podcast_series',
        [selectedPodcast.feed_url]
      );

      const state = {
        registerCard: {
          actionData,
          cardId,
          podcastMetadata: {
            title: selectedPodcast.title,
            author: selectedPodcast.author,
            image_url: selectedPodcast.image_url,
            description: selectedPodcast.description,
            feed_url: selectedPodcast.feed_url,
          },
        },
      };

      console.log('Navigating to /cards/register with state:', state);
      console.log('Selected podcast:', selectedPodcast);
      console.log('Built actionData:', actionData);
      navigate('/cards/register', { state });
    } else {
      console.log('Cannot select series:', { isSelecting, selectedPodcast });
    }
  };

  return (
    <Box sx={{ width: '100%' }}>
      {!selectedPodcast && (
        <Paper sx={{ mb: 2 }}>
          <Tabs
            value={currentTab}
            onChange={handleTabChange}
            indicatorColor="primary"
            textColor="primary"
            centered
          >
            <Tab
              label={t('podcasts.tabs.search', 'Search')}
              value="search"
            />
            <Tab
              label={t('podcasts.tabs.subscriptions', 'My Podcasts')}
              value="subscriptions"
              disabled
            />
          </Tabs>
        </Paper>
      )}

      {!selectedPodcast && currentTab === 'search' && (
        <PodcastSearch
          isSelecting={isSelecting}
          onSelectPodcast={handleSelectPodcast}
        />
      )}

      {!selectedPodcast && currentTab === 'subscriptions' && (
        <Box sx={{ py: 4, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            {t('podcasts.subscriptions.coming-soon', 'Podcast subscriptions coming soon!')}
          </Typography>
        </Box>
      )}

      {selectedPodcast && (
        <Box>
          <Box sx={{ mb: 2 }}>
            <Button
              variant="text"
              onClick={() => setSelectedPodcast(null)}
              startIcon={<ArrowBackIcon />}
            >
              {t('podcasts.back', 'Back to Search')}
            </Button>
          </Box>

          {isSelecting && (
            <Paper sx={{ p: 2, mb: 2 }}>
              <Typography variant="h6" gutterBottom>
                {selectedPodcast.title}
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t('podcasts.register.prompt', 'Choose what to play when this card is tapped:')}
              </Typography>
              <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
                <Button
                  variant="contained"
                  onClick={handleSelectSeries}
                  fullWidth
                >
                  {t('podcasts.register.entire-series', 'Entire Series (All Episodes)')}
                </Button>
                <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {t('podcasts.register.or', 'or')}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {t('podcasts.register.select-episode', 'Select a specific episode below')}
                </Typography>
              </Box>
            </Paper>
          )}

          <EpisodeList
            feedUrl={selectedPodcast.feed_url}
            podcastTitle={selectedPodcast.title}
            isSelecting={isSelecting}
            onSelectEpisode={handleSelectEpisode}
          />
        </Box>
      )}
    </Box>
  );
};

export default Podcasts;
