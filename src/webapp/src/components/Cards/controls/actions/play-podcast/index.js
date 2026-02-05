import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  createSearchParams,
  useNavigate,
} from 'react-router-dom';
import {
  Button,
  CardMedia,
  CircularProgress,
  Grid,
  Typography,
  Paper,
  Box,
} from '@mui/material';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import PodcastsIcon from '@mui/icons-material/Podcasts';

import { getActionAndCommand, getArgsValues } from '../../../utils';
import request from '../../../../../utils/request';

const SelectPlayPodcast = ({
  actionData,
  cardId,
  podcastMetadata,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { command } = getActionAndCommand(actionData);
  const values = getArgsValues(actionData);

  const [fetchedMetadata, setFetchedMetadata] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch podcast metadata if we have a feed_url but no metadata
  useEffect(() => {
    const feedUrl = values && values[0];

    if (feedUrl && !podcastMetadata && !fetchedMetadata && !isLoading) {
      setIsLoading(true);

      // Fetch podcast metadata from the RSS feed
      request('getPodcastInfo', { feed_url: feedUrl })
        .then(({ result, error }) => {
          if (result && result.title) {
            setFetchedMetadata(result);
          }
          setIsLoading(false);
        })
        .catch(() => {
          setIsLoading(false);
        });
    }
  }, [values, podcastMetadata, fetchedMetadata, isLoading]);

  const metadata = podcastMetadata || fetchedMetadata;

  const selectPodcast = () => {
    const searchParams = createSearchParams({
      isSelecting: true,
      cardId
    });

    navigate({
      pathname: '/library/podcasts',
      search: `?${searchParams}`,
    });
  };

  const getCommandLabel = () => {
    if (command === 'play_podcast_series') {
      return t('cards.controls.actions.play-podcast.series', 'Play Podcast Series (All Episodes)');
    } else if (command === 'play_podcast_episode') {
      return t('cards.controls.actions.play-podcast.episode', 'Play Specific Episode');
    }
    return t('cards.controls.actions.play-podcast.default', 'Play Podcast');
  };

  const renderSelectedContent = () => {
    if (isLoading) {
      return (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
          <CircularProgress size={24} />
        </Box>
      );
    }

    if (!metadata) {
      return (
        <Typography variant="body2" color="text.secondary">
          {t('cards.controls.actions.play-podcast.not-selected', 'No podcast selected yet')}
        </Typography>
      );
    }

    return (
      <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
        <Box sx={{ display: 'flex', gap: 2 }}>
          {metadata.image_url && (
            <CardMedia
              component="img"
              sx={{ width: 120, height: 120, borderRadius: 1, flexShrink: 0 }}
              image={metadata.image_url}
              alt={metadata.title}
            />
          )}
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6" gutterBottom>
              {metadata.title}
            </Typography>
            {metadata.author && (
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {metadata.author}
              </Typography>
            )}
            {metadata.description && (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mt: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  display: '-webkit-box',
                  WebkitLineClamp: 3,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {metadata.description}
              </Typography>
            )}
            {metadata.episode && (
              <Typography variant="body2" color="primary" sx={{ mt: 1, fontWeight: 500 }}>
                Episode: {metadata.episode.title}
              </Typography>
            )}
          </Box>
        </Box>
        <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
          {command === 'play_podcast_series'
            ? t('cards.controls.actions.play-podcast.series-hint', 'Will play all unplayed episodes, newest first')
            : t('cards.controls.actions.play-podcast.episode-hint', 'Will play this specific episode with resume')
          }
        </Typography>
      </Paper>
    );
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <PodcastsIcon color="primary" />
          <Typography variant="h6">
            {getCommandLabel()}
          </Typography>
        </Box>
      </Grid>

      <Grid item xs={12}>
        {renderSelectedContent()}
      </Grid>

      <Grid item xs={12} sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
        <Button
          variant="contained"
          onClick={selectPodcast}
          endIcon={<KeyboardArrowRightIcon />}
          size="large"
        >
          {values && values.length > 0
            ? t('cards.controls.actions.play-podcast.change-selection', 'Change Podcast')
            : t('cards.controls.actions.play-podcast.select-podcast', 'Select Podcast')
          }
        </Button>
      </Grid>
    </Grid>
  );
};

export default SelectPlayPodcast;
