import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  CardMedia,
  CircularProgress,
  Chip,
  Paper,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

import request from '../../../../utils/request';

const SpotifyContentDetail = ({ content, isSelecting, onPlay, onAssignToCard }) => {
  const { t } = useTranslation();
  const [details, setDetails] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchDetails = async () => {
      setIsLoading(true);
      try {
        const { result } = await request('spotifyGetContentDetails', { uri: content.uri });
        if (result && !result.error) {
          setDetails(result);
        } else {
          // Fall back to the search result data we already have
          setDetails(content);
        }
      } catch {
        setDetails(content);
      } finally {
        setIsLoading(false);
      }
    };

    fetchDetails();
  }, [content]);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const displayData = details || content;

  return (
    <Box sx={{ width: '100%' }}>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', gap: 2 }}>
          {displayData.image_url && (
            <CardMedia
              component="img"
              sx={{ width: 160, height: 160, borderRadius: 1, flexShrink: 0 }}
              image={displayData.image_url}
              alt={displayData.name}
            />
          )}
          <Box sx={{ flex: 1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Chip
                label={displayData.type}
                size="small"
                color="primary"
              />
            </Box>
            <Typography variant="h5" gutterBottom>
              {displayData.name}
            </Typography>
            {displayData.artist && (
              <Typography variant="body1" color="text.secondary" gutterBottom>
                {displayData.artist}
              </Typography>
            )}
            {displayData.total_tracks && (
              <Typography variant="body2" color="text.secondary">
                {displayData.total_tracks} {displayData.type === 'show' ? 'episodes' : 'tracks'}
              </Typography>
            )}
            {displayData.description && (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{
                  mt: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  display: '-webkit-box',
                  WebkitLineClamp: 4,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {displayData.description}
              </Typography>
            )}
          </Box>
        </Box>

        <Box sx={{ display: 'flex', gap: 2, mt: 2 }}>
          {isSelecting ? (
            <Button
              variant="contained"
              startIcon={<CheckCircleIcon />}
              onClick={() => onAssignToCard(displayData.uri, displayData)}
              fullWidth
            >
              {t('spotify.assign-to-card', 'Assign to Card')}
            </Button>
          ) : (
            <Button
              variant="contained"
              startIcon={<PlayArrowIcon />}
              onClick={() => onPlay(displayData.uri)}
              fullWidth
            >
              {t('spotify.play-all', 'Play All')}
            </Button>
          )}
        </Box>
      </Paper>
    </Box>
  );
};

export default SpotifyContentDetail;
