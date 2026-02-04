import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  createSearchParams,
  useNavigate,
} from 'react-router-dom';
import {
  Button,
  Grid,
  Typography,
  Paper,
  Box,
} from '@mui/material';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import PodcastsIcon from '@mui/icons-material/Podcasts';

import { getActionAndCommand, getArgsValues } from '../../../utils';

const SelectPlayPodcast = ({
  actionData,
  cardId,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { command } = getActionAndCommand(actionData);
  const values = getArgsValues(actionData);

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
    if (!values || values.length === 0) {
      return (
        <Typography variant="body2" color="text.secondary">
          {t('cards.controls.actions.play-podcast.not-selected', 'No podcast selected yet')}
        </Typography>
      );
    }

    if (command === 'play_podcast_series' && values[0]) {
      return (
        <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('cards.controls.actions.play-podcast.feed-url', 'Feed URL')}:
          </Typography>
          <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
            {values[0]}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            {t('cards.controls.actions.play-podcast.series-hint', 'Will play all unplayed episodes, newest first')}
          </Typography>
        </Paper>
      );
    }

    if (command === 'play_podcast_episode' && values[0]) {
      return (
        <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            {t('cards.controls.actions.play-podcast.feed-url', 'Feed URL')}:
          </Typography>
          <Typography variant="body2" sx={{ wordBreak: 'break-all', mb: 1 }}>
            {values[0]}
          </Typography>
          {values[1] && (
            <>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {t('cards.controls.actions.play-podcast.episode-guid', 'Episode ID')}:
              </Typography>
              <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                {values[1]}
              </Typography>
            </>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
            {t('cards.controls.actions.play-podcast.episode-hint', 'Will play this specific episode with resume')}
          </Typography>
        </Paper>
      );
    }

    return null;
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
