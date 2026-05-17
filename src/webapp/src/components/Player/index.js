import React, { useContext, useEffect, useState } from 'react';

import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import LinearProgress from '@mui/material/LinearProgress';
import Typography from '@mui/material/Typography';
import Alert from '@mui/material/Alert';

import Cover from './cover';
import Controls from './controls';
import Display from './display';
import SeekBar from './seekbar';
import Volume from './volume';

import AppSettingsContext from '../../context/appsettings/context';
import PlayerContext from '../../context/player/context';
import useSubscription from '../../hooks/useSubscription';
import request from '../../utils/request';

const Player = () => {
  const { state: { playerstatus } } = useContext(PlayerContext);
  const { file, coverart_url } = playerstatus || {};

  const [coverImage, setCoverImage] = useState(undefined);
  const [backgroundImage, setBackgroundImage] = useState('none');
  const [downloadProgress, setDownloadProgress] = useState(null);

  const {
    settings,
  } = useContext(AppSettingsContext);

  const { show_covers } = settings;

  // Subscribe to podcast download events via per-topic hooks. Phase 4
  // re-render fix: previously the whole pubsub state object was pulled in,
  // forcing this Player tree to re-render on every unrelated push.
  const downloadStarted = useSubscription('podcast.download_started');
  const downloadProgressEvent = useSubscription('podcast.download_progress');
  const downloadCompleted = useSubscription('podcast.download_completed');
  const downloadFailed = useSubscription('podcast.download_failed');

  useEffect(() => {
    if (downloadStarted) {
      setDownloadProgress({
        status: 'downloading',
        percent: 0,
        title: downloadStarted.episode_title
      });
    } else if (downloadProgressEvent) {
      setDownloadProgress(prev => ({
        ...prev,
        percent: downloadProgressEvent.percent || 0
      }));
    } else if (downloadCompleted) {
      setDownloadProgress({
        status: 'completed',
        percent: 100
      });
      // Clear after 2 seconds
      setTimeout(() => setDownloadProgress(null), 2000);
    } else if (downloadFailed) {
      setDownloadProgress({
        status: 'failed',
        error: downloadFailed.error
      });
      // Clear after 3 seconds
      setTimeout(() => setDownloadProgress(null), 3000);
    }
  }, [downloadStarted, downloadProgressEvent, downloadCompleted, downloadFailed]);

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
          {downloadProgress && (
            <Box sx={{ width: '100%', mt: 2, mb: 2 }}>
              {downloadProgress.status === 'downloading' && (
                <>
                  <Typography variant="body2" sx={{ mb: 1 }}>
                    Downloading episode for resume...
                  </Typography>
                  <LinearProgress variant="determinate" value={downloadProgress.percent} />
                  <Typography variant="caption" sx={{ mt: 0.5 }}>
                    {Math.round(downloadProgress.percent)}%
                  </Typography>
                </>
              )}
              {downloadProgress.status === 'completed' && (
                <Alert severity="success">Download complete!</Alert>
              )}
              {downloadProgress.status === 'failed' && (
                <Alert severity="warning">Download failed, streaming instead</Alert>
              )}
            </Box>
          )}
          <SeekBar />
          <Controls />
          <Volume />
        </Grid>
      </Grid>
    </Grid>
  );
};

export default Player;
