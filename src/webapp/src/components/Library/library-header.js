import React, { useState } from "react";
import {
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  Grid,
  IconButton,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import SearchIcon from '@mui/icons-material/Search';
import AlbumIcon from '@mui/icons-material/Album';
import FolderIcon from '@mui/icons-material/Folder';
import PodcastsIcon from '@mui/icons-material/Podcasts';

const LibraryHeader = ({ handleMusicFilter, musicFilter }) => {
  const { search: urlSearch } = useLocation();
  const navigate = useNavigate();
  const { '*': view } = useParams();
  const { t } = useTranslation();
  const [showSearchInput, setShowSearchInput] = useState(false);

  const getCurrentView = () => {
    if (view.startsWith('podcasts')) return 'podcasts';
    if (view.startsWith('folders')) return 'folders';
    return 'albums';
  };

  const handleViewChange = (event, newView) => {
    if (newView && newView !== getCurrentView()) {
      localStorage.setItem('libraryLastListView', newView);
      navigate(`${newView}${urlSearch}`);
    }
  };

  const iconLabel = showSearchInput
    ? t('library.header.search-hide')
    : t('library.header.search-show');

  const currentView = getCurrentView();
  const isPodcastsView = currentView === 'podcasts';

  return (
    <Grid container sx={{ marginBottom: '8px' }}>
      <Grid item
        xs={12}
        sx={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', width: '100%' }}
      >
        {/* Search is only for music (albums/folders), not podcasts */}
        {!isPodcastsView && (
          <IconButton
            aria-label={iconLabel}
            onClick={() => setShowSearchInput(!showSearchInput)}
            color={showSearchInput ? 'primary' : undefined}
            title={iconLabel}
          >
            <SearchIcon />
          </IconButton>
        )}
        {isPodcastsView && <div style={{ width: 40 }} />}

        {showSearchInput && !isPodcastsView &&
          <TextField
            id="library-search"
            label={t('library.header.search-label')}
            onChange={handleMusicFilter}
            value={musicFilter}
            variant="outlined"
            size="small"
            autoFocus
            focused
            sx={{
              width: '100%',
            }}
          />
        }
        {(!showSearchInput || isPodcastsView) &&
          <Stack
            alignItems="center"
            direction="row"
            sx={{ marginRight: '5px', flexGrow: 1, justifyContent: 'center' }}
          >
            <ToggleButtonGroup
              value={currentView}
              exclusive
              onChange={handleViewChange}
              aria-label={t('library.header.toggle-label')}
              size="small"
            >
              <ToggleButton value="albums" aria-label={t('library.header.albums')}>
                <AlbumIcon sx={{ mr: 0.5, fontSize: '1.2rem' }} />
                <Typography variant="body2">
                  {t('library.header.albums')}
                </Typography>
              </ToggleButton>
              <ToggleButton value="folders" aria-label={t('library.header.folders')}>
                <FolderIcon sx={{ mr: 0.5, fontSize: '1.2rem' }} />
                <Typography variant="body2">
                  {t('library.header.folders')}
                </Typography>
              </ToggleButton>
              <ToggleButton value="podcasts" aria-label={t('library.header.podcasts', 'Podcasts')}>
                <PodcastsIcon sx={{ mr: 0.5, fontSize: '1.2rem' }} />
                <Typography variant="body2">
                  {t('library.header.podcasts', 'Podcasts')}
                </Typography>
              </ToggleButton>
            </ToggleButtonGroup>
          </Stack>
        }
      </Grid>
    </Grid>
  );
}

export default LibraryHeader;
