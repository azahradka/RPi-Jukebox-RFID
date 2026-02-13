import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { format, parseISO } from 'date-fns';
import {
  Box,
  Button,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import RefreshIcon from '@mui/icons-material/Refresh';

import request from '../../../../utils/request';

const EpisodeList = ({ feedUrl, isSelecting, onSelectEpisode, podcastTitle }) => {
  const { t } = useTranslation();
  const [episodes, setEpisodes] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchEpisodes = async (forceRefresh = false) => {
    setIsLoading(true);
    setError(null);

    try {
      const { result, error: fetchError } = await request('getPodcastEpisodes', { feed_url: feedUrl, force_refresh: forceRefresh });

      if (fetchError) {
        setError(fetchError);
        setEpisodes([]);
      } else if (result) {
        setEpisodes(result || []);
      }
    } catch (err) {
      setError(err.message || 'Failed to load episodes');
      setEpisodes([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (feedUrl) {
      fetchEpisodes(false);
    }
  }, [feedUrl]);

  const handleRefresh = () => {
    fetchEpisodes(true);
  };

  const handleSelectEpisode = (episode) => {
    if (onSelectEpisode) {
      onSelectEpisode(episode);
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds || seconds === 0) return '';
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    return `${minutes}m`;
  };

  const formatDate = (dateString) => {
    if (!dateString) return '';
    try {
      return format(parseISO(dateString), 'MMM d, yyyy');
    } catch (err) {
      return dateString;
    }
  };

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ py: 2 }}>
        <Typography color="error">
          {t('podcasts.episodes.error', 'Failed to load episodes')}: {error}
        </Typography>
        <Button
          variant="outlined"
          onClick={handleRefresh}
          sx={{ mt: 2 }}
          startIcon={<RefreshIcon />}
        >
          {t('podcasts.episodes.retry', 'Retry')}
        </Button>
      </Box>
    );
  }

  if (episodes.length === 0) {
    return (
      <Box sx={{ py: 2, textAlign: 'center' }}>
        <Typography color="text.secondary">
          {t('podcasts.episodes.none', 'No episodes found in this podcast.')}
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%' }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" component="div">
          {podcastTitle || t('podcasts.episodes.title', 'Episodes')}
        </Typography>
        <Tooltip title={t('podcasts.episodes.refresh', 'Refresh Episodes')}>
          <IconButton onClick={handleRefresh} size="small">
            <RefreshIcon />
          </IconButton>
        </Tooltip>
      </Box>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {t('podcasts.episodes.count', '{{count}} episodes', { count: episodes.length })}
      </Typography>

      <Paper elevation={1}>
        <List>
          {episodes.map((episode, index) => (
            <React.Fragment key={episode.guid || index}>
              {index > 0 && <Divider />}
              <ListItem
                sx={{
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                  py: 2,
                }}
              >
                <Box sx={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <ListItemText
                    primary={
                      <Typography variant="subtitle1" component="div">
                        {episode.title}
                      </Typography>
                    }
                    secondary={
                      <Box component="span">
                        <Typography variant="body2" color="text.secondary" component="span">
                          {formatDate(episode.publish_date)}
                        </Typography>
                        {episode.duration_seconds > 0 && (
                          <Typography variant="body2" color="text.secondary" component="span" sx={{ ml: 2 }}>
                            {formatDuration(episode.duration_seconds)}
                          </Typography>
                        )}
                        {episode.author && (
                          <Typography variant="body2" color="text.secondary" component="span" sx={{ ml: 2 }}>
                            by {episode.author}
                          </Typography>
                        )}
                      </Box>
                    }
                  />
                  <Box sx={{ ml: 2, flexShrink: 0 }}>
                    {isSelecting ? (
                      <Button
                        variant="contained"
                        size="small"
                        startIcon={<CheckCircleIcon />}
                        onClick={() => handleSelectEpisode(episode)}
                      >
                        {t('podcasts.episodes.select', 'Select')}
                      </Button>
                    ) : (
                      <IconButton
                        color="primary"
                        onClick={() => handleSelectEpisode(episode)}
                        title={t('podcasts.episodes.play', 'Play Episode')}
                      >
                        <PlayArrowIcon />
                      </IconButton>
                    )}
                  </Box>
                </Box>

                {episode.description && (
                  <Typography
                    variant="body2"
                    color="text.secondary"
                    sx={{
                      mt: 1,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                    }}
                  >
                    {episode.description}
                  </Typography>
                )}
              </ListItem>
            </React.Fragment>
          ))}
        </List>
      </Paper>
    </Box>
  );
};

export default EpisodeList;
