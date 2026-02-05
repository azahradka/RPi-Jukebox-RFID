import React, { useContext, useEffect, useState } from 'react';

import Grid from '@mui/material/Grid';

import Cover from './cover';
import Controls from './controls';
import Display from './display';
import SeekBar from './seekbar';
import Volume from './volume';

import AppSettingsContext from '../../context/appsettings/context';
import PlayerContext from '../../context/player/context';
import request from '../../utils/request';

const Player = () => {
  const { state: { playerstatus } } = useContext(PlayerContext);
  const { file, coverart_url } = playerstatus || {};

  const [coverImage, setCoverImage] = useState(undefined);
  const [backgroundImage, setBackgroundImage] = useState('none');

  const {
    settings,
  } = useContext(AppSettingsContext);

  const { show_covers } = settings;

  useEffect(() => {
    console.log('Player useEffect - file:', file, 'coverart_url:', coverart_url);
    console.log('Full playerstatus:', playerstatus);

    // If coverart_url is provided (podcasts), use it directly
    if (coverart_url) {
      console.log('Using coverart_url:', coverart_url);
      setCoverImage(coverart_url);
      setBackgroundImage([
        'linear-gradient(to bottom, rgba(18, 18, 18, 0.5), rgba(18, 18, 18, 1))',
        `url(${coverart_url})`
      ].join(','));
      return;
    }

    // Otherwise, fetch from local cache (for local music files)
    const getCoverArt = async () => {
      console.log('Fetching coverart via RPC for file:', file);
      const { result } = await request('getSingleCoverArt', { song_url: file });
      if (result) {
        setCoverImage(`/cover-cache/${result}`);
        setBackgroundImage([
          'linear-gradient(to bottom, rgba(18, 18, 18, 0.5), rgba(18, 18, 18, 1))',
          `url(/cover-cache/${result})`
        ].join(','));
      };
    }

    if (file) {
      getCoverArt();
    }
  }, [file, coverart_url]);

  return (
    <Grid
      container
      id="player"
      sx={{
        backgroundImage,
        backgroundPosition: 'center',
      }}
    >
      <Grid
        container
        sx={{
          paddingTop: '30px',
          paddingLeft: '30px',
          paddingRight: '30px',
          minHeight: 'calc(100vh - 64px - 10px)',
          backdropFilter: 'blur(25px)',
        }}
      >
        <Grid item xs={12} sm={5}>
          <Cover coverImage={coverImage} />
        </Grid>
        <Grid item xs={12} sm={7}>
          <Display />
          <SeekBar />
          <Controls />
          <Volume />
        </Grid>
      </Grid>
    </Grid>
  );
};

export default Player;
