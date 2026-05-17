import React, { useContext, useEffect, useState } from 'react';
import { omit } from 'ramda';
import { useTranslation } from 'react-i18next';

import PubSubContext from '../../context/pubsub/context';
import useSubscription from '../../hooks/useSubscription';
import CardsForm from './form';
import { useLocation } from 'react-router';

const CardsRegister = () => {
  const { t } = useTranslation();
  const { setState } = useContext(PubSubContext);
  const swipedCardId = useSubscription('rfid.card_id');
  const location = useLocation();
  const locationState = location.state;
  const registerCard = locationState?.registerCard;

  const [cardId, setCardId] = useState(undefined);
  const [actionData, setActionData] = useState({});

  useEffect(() => {
    setState(state => (omit(['rfid.card_id'], state)));
  }, [setState]);

  useEffect(() => {
    setCardId(swipedCardId || registerCard?.cardId);
  }, [registerCard, swipedCardId])

  useEffect(() => {
    if (locationState?.registerCard?.actionData) {
      setActionData(locationState.registerCard.actionData);
    }
  }, [locationState]);

  return (
    <CardsForm
      title={t('cards.register.register-card')}
      cardId={cardId}
      actionData={actionData}
      setActionData={setActionData}
      podcastMetadata={registerCard?.podcastMetadata}
      spotifyMetadata={registerCard?.spotifyMetadata}
    />
  );
};

export default CardsRegister;
