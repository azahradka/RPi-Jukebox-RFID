import React, { useEffect, useState } from "react";
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import {
  Box,
  CircularProgress,
  Typography,
} from "@mui/material";

import request from '../../../../utils/request';
import FolderList from "./folder-list";

import { ROOT_DIR } from '../../../../config';

const Folders = ({
  musicFilter,
  isSelecting,
  registerMusicToCard,
}) => {
  const { t } = useTranslation();
  const { dir = ROOT_DIR } = useParams();
  const [folders, setFolders] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const search = ({ name }) => {
    if (musicFilter === '') return true;

    const lowerCaseMusicFilter = musicFilter.toLowerCase();

    return name.toLowerCase().includes(lowerCaseMusicFilter);
  };

  useEffect(() => {
    const fetchFolderList = async () => {
      setIsLoading(true);
      setError(null);
      // Phase 4: opt into the legacy ``swallow`` shape so we can render
      // an inline error in the folder list instead of letting the
      // top-level error boundary blow the whole app away on a transient
      // backend hiccup.
      const { result, error: fetchErr } = await request(
        'folderList',
        { folder: decodeURIComponent(dir) },
        { swallow: true },
      );
      setIsLoading(false);

      if (result) setFolders(result);
      if (fetchErr) setError(fetchErr);
    }

    fetchFolderList();
  }, [dir]);

  const filteredFolders = folders.filter(search);

  // Phase 4: a labelled loading state so the spinner is discoverable
  // and tests can assert on it without coupling to MUI internals.
  if (isLoading) {
    return (
      <Box
        sx={{ display: 'flex', justifyContent: 'center', py: 4 }}
        data-testid="folder-list-loading"
        aria-label={t('library.loading', 'Loading')}
      >
        <CircularProgress />
      </Box>
    );
  }
  if (error) return <Typography data-testid="folder-list-error">{t('library.loading-error')}</Typography>;
  if (musicFilter && !filteredFolders.length) {
    return <Typography>{t('library.folders.no-music')}</Typography>;
  }

  return (
    <FolderList
      dir={dir}
      folders={filteredFolders}
      isSelecting={isSelecting}
      registerMusicToCard={registerMusicToCard}
    />
  );
};

export default Folders;
