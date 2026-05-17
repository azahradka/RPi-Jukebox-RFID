import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  CardMedia,
  Chip,
  CircularProgress,
  Grid,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

import useSpotifySearch from '../../../../hooks/useSpotifySearch';

const TYPE_LABELS = {
  track: 'Song',
  album: 'Album',
  playlist: 'Playlist',
  show: 'Podcast',
  episode: 'Episode',
};

const TYPE_COLORS = {
  track: 'primary',
  album: 'secondary',
  playlist: 'success',
  show: 'warning',
  episode: 'info',
};

const FILTER_TYPES = ['track', 'album', 'playlist', 'show'];

/**
 * Presentational Spotify-search component (Phase 5b refactor).
 *
 * All state + RPC + debounce logic lives in ``useSpotifySearch``. This
 * component is purely presentational + minimal event wiring.
 *
 * Public API unchanged: ``isSelecting``, ``onSelectContent``, ``onPlay``.
 */
const SpotifySearch = ({ isSelecting, onSelectContent, onPlay }) => {
  const { t } = useTranslation();

  const {
    query,
    setQuery,
    searching,
    error,
    searchPerformed,
    activeFilter,
    setActiveFilter,
    filteredResults,
    results,
    submitNow,
  } = useSpotifySearch();

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    submitNow();
  };

  return (
    <Box sx={{ width: '100%' }}>
      <form onSubmit={handleSearchSubmit}>
        <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
          <TextField
            fullWidth
            label={t('spotify.search.label', 'Search Spotify')}
            placeholder={t('spotify.search.placeholder', 'Search for songs, albums, playlists...')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            variant="outlined"
            size="medium"
            autoFocus
          />
          <Button
            type="submit"
            variant="contained"
            startIcon={<SearchIcon />}
            disabled={searching || query.trim().length < 2}
            sx={{ minWidth: '120px' }}
          >
            {t('spotify.search.button', 'Search')}
          </Button>
        </Box>
      </form>

      {results.length > 0 && (
        <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
          <Chip
            label={t('spotify.filter.all', 'All')}
            variant={activeFilter === null ? 'filled' : 'outlined'}
            onClick={() => setActiveFilter(null)}
          />
          {FILTER_TYPES.map((type) => {
            const count = results.filter((i) => i.type === type).length;
            if (count === 0) return null;
            return (
              <Chip
                key={type}
                label={`${TYPE_LABELS[type]} (${count})`}
                color={TYPE_COLORS[type] || 'default'}
                variant={activeFilter === type ? 'filled' : 'outlined'}
                onClick={() => setActiveFilter(activeFilter === type ? null : type)}
              />
            );
          })}
        </Box>
      )}

      {searching && (
        <Box
          sx={{ display: 'flex', justifyContent: 'center', py: 4 }}
          data-testid="spotify-search-loading"
          aria-label={t('spotify.search.loading', 'Searching Spotify')}
        >
          <CircularProgress />
        </Box>
      )}

      {error && (
        <Typography color="error" sx={{ py: 2 }}>
          {t('spotify.search.error', 'Search failed')}: {String(error)}
        </Typography>
      )}

      {!searching && searchPerformed && filteredResults.length === 0 && !error && (
        <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
          {t('spotify.search.no-results', 'No results found. Try a different search term.')}
        </Typography>
      )}

      {!searching && filteredResults.length > 0 && (
        <Grid container spacing={2}>
          {filteredResults.map((item, index) => (
            <Grid item xs={12} sm={6} md={4} key={item.uri || index}>
              <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                {item.image_url && (
                  <CardMedia
                    component="img"
                    height="180"
                    image={item.image_url}
                    alt={item.name}
                    sx={{ objectFit: 'cover' }}
                  />
                )}
                <CardContent sx={{ flexGrow: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Chip
                      label={TYPE_LABELS[item.type] || item.type}
                      color={TYPE_COLORS[item.type] || 'default'}
                      size="small"
                    />
                  </Box>
                  <Typography variant="h6" component="div" gutterBottom noWrap>
                    {item.name}
                  </Typography>
                  {item.artist && (
                    <Typography variant="body2" color="text.secondary" gutterBottom>
                      {item.artist}
                    </Typography>
                  )}
                  {item.total_tracks && (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {item.total_tracks} {item.type === 'show' ? 'episodes' : 'tracks'}
                    </Typography>
                  )}
                  {item.description && (
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
                      {item.description}
                    </Typography>
                  )}
                </CardContent>
                <CardActions sx={{ gap: 1 }}>
                  {isSelecting ? (
                    <Button
                      size="small"
                      variant="contained"
                      color="primary"
                      startIcon={<CheckCircleIcon />}
                      onClick={() => onSelectContent(item)}
                      fullWidth
                    >
                      {t('spotify.select-for-card', 'Select for Card')}
                    </Button>
                  ) : (
                    <>
                      {(item.type === 'track' || item.type === 'episode') ? (
                        <Button
                          size="small"
                          variant="contained"
                          startIcon={<PlayArrowIcon />}
                          onClick={() => onPlay(item.uri)}
                          fullWidth
                        >
                          {t('spotify.play', 'Play')}
                        </Button>
                      ) : (
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={() => onSelectContent(item)}
                          fullWidth
                        >
                          {t('spotify.view-details', 'View Details')}
                        </Button>
                      )}
                    </>
                  )}
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {!searchPerformed && (
        <Box sx={{ textAlign: 'center', py: 4 }}>
          <SearchIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
          <Typography variant="h6" color="text.secondary" gutterBottom>
            {t('spotify.search.welcome', 'Search Spotify')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('spotify.search.hint', 'Search for songs, albums, playlists, and podcasts on Spotify.')}
          </Typography>
        </Box>
      )}
    </Box>
  );
};

export default SpotifySearch;
