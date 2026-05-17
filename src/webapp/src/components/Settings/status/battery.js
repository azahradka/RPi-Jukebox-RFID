import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  ListItem,
  ListItemText,
  ListItemAvatar,
  Avatar,
} from '@mui/material';

import BatteryIcon from '../helpers/battery-icon';
import useSubscription from '../../../hooks/useSubscription';
import { pluginIsLoaded } from '../../../utils/utils';

const StatusBattery = () => {
  const { t } = useTranslation();

  const plugins = useSubscription('core.plugins.loaded');
  const { soc, charging } = useSubscription('batt_status') || {};

  const [batteryPluginAvaialble, setBatteryPluginAvailability] = useState(false);

  const chargingStatusLabel = () => {
    if (soc) {
      if (charging) return t('settings.status.battery.charging');
      return t('settings.status.battery.not-charging');
    }

    return t('settings.status.battery.title');
  };

  useEffect(() => {
    if (pluginIsLoaded(plugins, 'battmon')) {
      setBatteryPluginAvailability(true);
    }
  }, [plugins]);

  return (
    batteryPluginAvaialble &&
      <ListItem disableGutters>
        <ListItemAvatar>
          <Avatar>
            <BatteryIcon soc={soc} charging={charging} />
          </Avatar>
        </ListItemAvatar>
        <ListItemText
          primary={soc ? `${soc}%` : `${t('general.loading')} ...`}
          secondary={chargingStatusLabel}
        />
      </ListItem>
  );
};

export default StatusBattery;
