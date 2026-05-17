import React, { useEffect, useState } from "react";
import { useTranslation } from 'react-i18next';

import {
  CircularProgress,
  Typography,
} from "@mui/material";

import request from '../../../../utils/request';
import { flatByAlbum } from '../../../../utils/utils';

import AlbumList from "./album-list";

const Albums = ({ musicFilter }) => {
  const { t } = useTranslation();

  const [albums, setAlbums] = useState([]);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const search = ({ albumartist, album }) => {
    if (musicFilter === '') return true;

    const lowerCaseMusicFilter = musicFilter.toLowerCase();

    return albumartist.toLowerCase().includes(lowerCaseMusicFilter) ||
      album.toLowerCase().includes(lowerCaseMusicFilter);
  };

  useEffect(() => {
    const fetchAlbumList = async () => {
      setIsLoading(true);
      // Phase 5a FU#1: dead ``error`` destructure removed; use
      // try/catch + local state so the album list page renders an
      // inline error instead of unmounting via the top-level boundary.
      try {
        const { result } = await request('albumList');
        if(result) setAlbums(result.reduce(flatByAlbum, []));
      } catch (err) {
        setError(err);
      }
      setIsLoading(false);
    }

    fetchAlbumList();
  }, []);

  return (
    <>
      {isLoading
        ? <CircularProgress />
        : <AlbumList
            albums={albums.filter(search)}
            musicFilter={musicFilter}
      />}
      {error &&
        <Typography>{t('library.loading-error')}</Typography>
      }
    </>
  );
};

export default Albums;
