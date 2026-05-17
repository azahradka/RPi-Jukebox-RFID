import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';

import {
  Button,
  CardActions,
} from '@mui/material';

import CardsDeleteDialog from '../dialogs/delete';
import request from '../../../utils/request';
import {
  getActionAndCommand,
  getArgsValues
} from '../utils';

const ActionsControls = ({
  actionData,
  cardId,
}) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { '*': path } = useParams();
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  const handleRegisterCard = async () => {
    const args = getArgsValues(actionData);
    const { command: cmd_alias } = getActionAndCommand(actionData);

    const kwargs = {
      card_id: cardId.toString(),
      cmd_alias,
      overwrite: true,
      ...(args.length && { args }),
    };

    // Phase 5a FU#1: request() throws on failure; try/catch is the
    // canonical error path.
    try {
      await request('registerCard', kwargs);
    } catch (err) {
      return console.error(err);
    }

    navigate('../');
  };

  const handleDeleteCard = async () => {
    // Phase 5a FU#1: try/catch in place of the dead ``error`` shape.
    try {
      await request('deleteCard', { card_id: cardId });
    } catch (err) {
      return console.error(err);
    }

    navigate('/cards');
  };

  return (
    <>
      <CardActions
        sx={{
          marginTop: '40px',
          justifyContent: path === 'register' ? 'flex-end' : 'space-between'
        }}
      >
        {path !== 'register' &&
          <Button
            color="secondary"
            size="small"
            onClick={() => setDeleteDialogOpen(true)}
          >
            {t('general.buttons.delete')}
          </Button>
        }
        <Button
          color="primary"
          onClick={() => handleRegisterCard(cardId)}
          size="small"
        >
          {t('general.buttons.save')}
        </Button>
      </CardActions>
      <CardsDeleteDialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        doDelete={handleDeleteCard}
        cardId={cardId}
      />
    </>
  );
};

export default ActionsControls;
