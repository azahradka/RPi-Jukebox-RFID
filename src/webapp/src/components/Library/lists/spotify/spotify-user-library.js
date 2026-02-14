import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  CircularProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  Avatar,
  Chip,
  Typography,
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

import request from '../../../../utils/request';

const SpotifyUserLibrary = ({ isSelecting, onSelectContent, onPlay }) => {
  const { t } = useTranslation();
  const [playlists, setPlaylists] = useState([]);
  const [albums, setAlbums] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchLibrary = async () => {
      setIsLoading(true);
      setError(null);

      try {
        const [playlistRes, albumRes] = await Promise.all([
          request('spotifyGetUserPlaylists', { limit: 50, offset: 0 }),
          request('spotifyGetUserAlbums', { limit: 50, offset: 0 }),
        ]);

        if (playlistRes.result && playlistRes.result.items) {
          setPlaylists(playlistRes.result.items);
        }
        if (albumRes.result && albumRes.result.items) {
          setAlbums(albumRes.result.items);
        }
      } catch (err) {
        setError(err.message || 'Failed to load library');
      } finally {
        setIsLoading(false);
      }
    };

    fetchLibrary();
  }, []);

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Typography color="error" sx={{ py: 2 }}>
        {String(error)}
      </Typography>
    );
  }

  const renderItem = (item) => (
    <ListItem
      key={item.uri}
      disablePadding
      secondaryAction={
        isSelecting ? (
          <Button
            size="small"
            variant="contained"
            startIcon={<CheckCircleIcon />}
            onClick={(e) => { e.stopPropagation(); onSelectContent(item); }}
          >
            {t('spotify.select', 'Select')}
          </Button>
        ) : (
          <Button
            size="small"
            variant="outlined"
            startIcon={<PlayArrowIcon />}
            onClick={(e) => { e.stopPropagation(); onPlay(item.uri); }}
          >
            {t('spotify.play', 'Play')}
          </Button>
        )
      }
    >
      <ListItemButton onClick={() => onSelectContent(item)}>
        <ListItemAvatar>
          <Avatar
            variant="rounded"
            src={item.image_url}
            alt={item.name}
            sx={{ width: 56, height: 56, mr: 2 }}
          />
        </ListItemAvatar>
        <ListItemText
          primary={item.name}
          secondary={
            <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Chip
                label={item.type === 'playlist' ? 'Playlist' : 'Album'}
                size="small"
                color={item.type === 'playlist' ? 'success' : 'secondary'}
              />
              {item.artist && <span>{item.artist}</span>}
              {item.total_tracks && <span>{item.total_tracks} tracks</span>}
            </Box>
          }
          primaryTypographyProps={{ noWrap: true }}
        />
      </ListItemButton>
    </ListItem>
  );

  return (
    <Box sx={{ width: '100%' }}>
      {playlists.length === 0 && albums.length === 0 && (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <Typography variant="body1" color="text.secondary">
            {t('spotify.library.empty', 'Your Spotify library is empty.')}
          </Typography>
        </Box>
      )}

      {playlists.length > 0 && (
        <>
          <Typography variant="h6" sx={{ mt: 1, mb: 1 }}>
            {t('spotify.library.playlists', 'Playlists')}
          </Typography>
          <List>{playlists.map(renderItem)}</List>
        </>
      )}

      {albums.length > 0 && (
        <>
          <Typography variant="h6" sx={{ mt: 2, mb: 1 }}>
            {t('spotify.library.albums', 'Saved Albums')}
          </Typography>
          <List>{albums.map(renderItem)}</List>
        </>
      )}
    </Box>
  );
};

export default SpotifyUserLibrary;
