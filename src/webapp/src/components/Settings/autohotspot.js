import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Card,
  CardContent,
  CardHeader,
  Divider,
  FormGroup,
  FormControlLabel,
  Grid,
  Link,
} from '@mui/material';

import { SwitchWithLoader } from '../general';

import request from '../../utils/request';

const helpUrl = 'https://github.com/MiczFlor/RPi-Jukebox-RFID/blob/future3/main/documentation/builders/autohotspot.md';

const SettingsAutoHotpot = () => {
  const { t } = useTranslation();
  const [autohotspotStatus, setAutohotspotStatus] = useState('not-installed');
  const [isLoading, setIsLoading] = useState(true);

  const getAutohotspotStatus = async () => {
    // Phase 5a FU#1: request() throws on failure (Phase 1). The
    // legacy ``error`` destructure was a no-op. We still treat the
    // in-band 'error' string from the backend as a soft failure
    // (autohotspot not installed / partial config).
    try {
      const { result } = await request('getAutohotspotStatus', {}, { swallow: true });
      if (result && result !== 'error') setAutohotspotStatus(result);
      else if (result === 'error') console.error(`getAutohotspotStatus returned 'error'`);
    } catch (err) {
      console.error('getAutohotspotStatus failed:', err);
    }
  }

  const toggleAutoHotspot = async () => {
    const status = autohotspotStatus === 'active' ? 'inactive' : 'active';
    const action = autohotspotStatus === 'active' ? 'stop' : 'start';

    setIsLoading(true);
    setAutohotspotStatus(status);
    try {
      const { result } = await request(`${action}Autohotspot`, {}, { swallow: true });
      if (result === 'error') {
        console.error(`An error occured while performing '${action}AutoHotspot'`);
        await getAutohotspotStatus();
      }
    } catch (err) {
      console.error(`'${action}Autohotspot' failed:`, err);
      await getAutohotspotStatus();
    }

    setIsLoading(false);
  }

  useEffect(() => {
    const fetchAutohotspotStatus = async () => {
      setIsLoading(true);
      await getAutohotspotStatus();
      setIsLoading(false);
    }

    fetchAutohotspotStatus();
  }, []);

  return (
    <Card>
      <CardHeader
        title={t('settings.autohotspot.title')}
        subheader={
          autohotspotStatus === 'not-installed' &&
          <>
            {`⚠️ ${t('settings.autohotspot.not-installed')}`}
            <Link
              href={helpUrl}
              target="_blank"
              rel="noreferrer"
              sx={{
                marginLeft: '10px'
              }}
            >
              {t('settings.autohotspot.why')}
            </Link>
          </>
        }
      />
      <Divider />
      <CardContent>
        <Grid container direction="column">
          <Grid item>
            <FormGroup>
              <FormControlLabel
                sx={{
                  justifyContent: 'space-between',
                  marginLeft: '0',
                }}
                control={
                  <SwitchWithLoader
                    isLoading={isLoading}
                    checked={autohotspotStatus === 'active'}
                    disabled={autohotspotStatus === 'not-installed'}
                    onChange={() => toggleAutoHotspot()}
                  />
                }
                label={t('settings.autohotspot.control-label')}
                labelPlacement="start"
              />
            </FormGroup>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  );
};

export default SettingsAutoHotpot;
