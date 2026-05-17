import React from 'react';
import { useTranslation } from 'react-i18next';

import {
  ListItem,
  ListItemText,
} from '@mui/material';

import useSubscription from '../../../hooks/useSubscription';

const StatusCpuTemp = () => {
  const { t } = useTranslation();

  const hostTimerCputemp = useSubscription('host.timer.cputemp');
  const hostTemperatureCpu = useSubscription('host.temperature.cpu');

  let primaryText = t('settings.status.cpu-temp.unavailable');

  if (typeof hostTimerCputemp === 'object' && hostTimerCputemp !== null) {
    if (hostTimerCputemp?.enabled === true) {
      if (typeof hostTemperatureCpu === 'string' || hostTemperatureCpu instanceof String) {
        primaryText = `${hostTemperatureCpu}°C`;
      }
    }
    else {
      primaryText = t('settings.status.cpu-temp.not-enabled');
    }
  }

  return (
    <ListItem disableGutters>
      <ListItemText
        primary={primaryText}
        secondary={t('settings.status.cpu-temp.label')}
      />
    </ListItem>
  );
};

export default StatusCpuTemp;
