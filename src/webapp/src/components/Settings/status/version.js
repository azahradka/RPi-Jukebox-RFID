import React from 'react';
import { useTranslation } from 'react-i18next';

import {
  ListItem,
  ListItemText,
  ListItemAvatar,
  Avatar,
} from '@mui/material';

import FavoriteIcon from '@mui/icons-material/Favorite';

import useSubscription from '../../../hooks/useSubscription';

const StatusVersion = () => {
  const { t } = useTranslation();

  const coreVersion = useSubscription('core.version');

  return (
    <ListItem disableGutters>
      <ListItemAvatar>
        <Avatar>
          <FavoriteIcon />
        </Avatar>
      </ListItemAvatar>
      <ListItemText
        primary={coreVersion ? `${coreVersion}` : `${t('general.loading')} ...`}
        secondary={t('settings.status.version.label')}
      />
    </ListItem>
  );
};

export default StatusVersion;
