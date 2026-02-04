import React, { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  CardMedia,
  CircularProgress,
  Grid,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AddIcon from '@mui/icons-material/Add';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

import request from '../../../../utils/request';

const PodcastSearch = ({ isSelecting, onSelectPodcast }) => {
  const { t } = useTranslation();
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState(null);
  const [searchPerformed, setSearchPerformed] = useState(false);

  // Debounced search function
  const performSearch = useCallback(async (query) => {
    if (!query || query.trim().length < 2) {
      setSearchResults([]);
      setSearchPerformed(false);
      return;
    }

    setIsSearching(true);
    setError(null);
    setSearchPerformed(true);

    try {
      const { result, error: searchError } = await request('searchPodcasts', { query: query.trim() });

      if (searchError) {
        setError(searchError);
        setSearchResults([]);
      } else if (result) {
        setSearchResults(result || []);
      }
    } catch (err) {
      setError(err.message || 'Search failed');
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearchChange = (event) => {
    const query = event.target.value;
    setSearchQuery(query);
  };

  const handleSearchSubmit = (event) => {
    event.preventDefault();
    performSearch(searchQuery);
  };

  const handleSelectPodcast = (podcast) => {
    if (onSelectPodcast) {
      onSelectPodcast(podcast);
    }
  };

  return (
    <Box sx={{ width: '100%' }}>
      <form onSubmit={handleSearchSubmit}>
        <Box sx={{ display: 'flex', gap: 1, mb: 3 }}>
          <TextField
            fullWidth
            label={t('podcasts.search.label', 'Search Podcasts')}
            placeholder={t('podcasts.search.placeholder', 'Enter podcast name...')}
            value={searchQuery}
            onChange={handleSearchChange}
            variant="outlined"
            size="medium"
            autoFocus
          />
          <Button
            type="submit"
            variant="contained"
            startIcon={<SearchIcon />}
            disabled={isSearching || searchQuery.trim().length < 2}
            sx={{ minWidth: '120px' }}
          >
            {t('podcasts.search.button', 'Search')}
          </Button>
        </Box>
      </form>

      {isSearching && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {error && (
        <Typography color="error" sx={{ py: 2 }}>
          {t('podcasts.search.error', 'Search failed')}: {error}
        </Typography>
      )}

      {!isSearching && searchPerformed && searchResults.length === 0 && !error && (
        <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
          {t('podcasts.search.no-results', 'No podcasts found. Try a different search term.')}
        </Typography>
      )}

      {!isSearching && searchResults.length > 0 && (
        <Grid container spacing={2}>
          {searchResults.map((podcast, index) => (
            <Grid item xs={12} sm={6} md={4} key={podcast.feed_url || index}>
              <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                {podcast.image_url && (
                  <CardMedia
                    component="img"
                    height="200"
                    image={podcast.image_url}
                    alt={podcast.title}
                    sx={{ objectFit: 'cover' }}
                  />
                )}
                <CardContent sx={{ flexGrow: 1 }}>
                  <Typography variant="h6" component="div" gutterBottom noWrap>
                    {podcast.title}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" gutterBottom>
                    {podcast.author}
                  </Typography>
                  {podcast.genre && (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {podcast.genre}
                    </Typography>
                  )}
                  {podcast.episode_count > 0 && (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {t('podcasts.episode-count', '{{count}} episodes', { count: podcast.episode_count })}
                    </Typography>
                  )}
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
                    {podcast.description}
                  </Typography>
                </CardContent>
                <CardActions>
                  {isSelecting ? (
                    <Button
                      size="small"
                      variant="contained"
                      color="primary"
                      startIcon={<CheckCircleIcon />}
                      onClick={() => handleSelectPodcast(podcast)}
                      fullWidth
                    >
                      {t('podcasts.select-for-card', 'Select for Card')}
                    </Button>
                  ) : (
                    <Button
                      size="small"
                      variant="outlined"
                      startIcon={<AddIcon />}
                      onClick={() => handleSelectPodcast(podcast)}
                      fullWidth
                    >
                      {t('podcasts.view-episodes', 'View Episodes')}
                    </Button>
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
            {t('podcasts.search.welcome', 'Search for Podcasts')}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {t('podcasts.search.hint', 'Enter a podcast name to discover millions of podcasts via iTunes.')}
          </Typography>
        </Box>
      )}
    </Box>
  );
};

export default PodcastSearch;
