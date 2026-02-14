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
  Chip,
} from '@mui/material';
import KeyboardArrowRightIcon from '@mui/icons-material/KeyboardArrowRight';
import GraphicEqIcon from '@mui/icons-material/GraphicEq';

import { getArgsValues } from '../../../utils';
import request from '../../../../../utils/request';

const SelectPlaySpotify = ({
  actionData,
  cardId,
  spotifyMetadata,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const values = getArgsValues(actionData);

  const [fetchedMetadata, setFetchedMetadata] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  // Fetch Spotify content metadata if we have a URI but no metadata
  useEffect(() => {
    const uri = values && values[0];

    if (uri && !spotifyMetadata && !fetchedMetadata && !isLoading) {
      setIsLoading(true);

      request('spotifyGetContentDetails', { uri })
        .then(({ result }) => {
          if (result && result.name) {
            setFetchedMetadata(result);
          }
          setIsLoading(false);
        })
        .catch(() => {
          setIsLoading(false);
        });
    }
  }, [values, spotifyMetadata, fetchedMetadata, isLoading]);

  const metadata = spotifyMetadata || fetchedMetadata;

  const selectSpotifyContent = () => {
    const searchParams = createSearchParams({
      isSelecting: true,
      cardId,
    });

    navigate({
      pathname: '/library/spotify',
      search: `?${searchParams}`,
    });
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
          {t('cards.controls.actions.play-spotify.not-selected', 'No Spotify content selected yet')}
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
              alt={metadata.name}
            />
          )}
          <Box sx={{ flex: 1 }}>
            {metadata.type && (
              <Chip
                label={metadata.type}
                size="small"
                color="primary"
                sx={{ mb: 1 }}
              />
            )}
            <Typography variant="h6" gutterBottom>
              {metadata.name}
            </Typography>
            {metadata.artist && (
              <Typography variant="body2" color="text.secondary" gutterBottom>
                {metadata.artist}
              </Typography>
            )}
          </Box>
        </Box>
      </Paper>
    );
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <GraphicEqIcon color="primary" />
          <Typography variant="h6">
            {t('cards.controls.actions.play-spotify.title', 'Play Spotify Content')}
          </Typography>
        </Box>
      </Grid>

      <Grid item xs={12}>
        {renderSelectedContent()}
      </Grid>

      <Grid item xs={12} sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
        <Button
          variant="contained"
          onClick={selectSpotifyContent}
          endIcon={<KeyboardArrowRightIcon />}
          size="large"
        >
          {values && values.length > 0
            ? t('cards.controls.actions.play-spotify.change-selection', 'Change Selection')
            : t('cards.controls.actions.play-spotify.select-content', 'Select Spotify Content')
          }
        </Button>
      </Grid>
    </Grid>
  );
};

export default SelectPlaySpotify;
