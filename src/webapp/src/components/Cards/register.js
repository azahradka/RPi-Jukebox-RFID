import React, { useContext, useEffect, useState } from 'react';
import { omit } from 'ramda';
import { useTranslation } from 'react-i18next';

import PubSubContext from '../../context/pubsub/context';
import CardsForm from './form';
import { useLocation } from 'react-router';

const CardsRegister = () => {
  const { t } = useTranslation();
  const {
    state: { 'rfid.card_id': swipedCardId },
    setState
  } = useContext(PubSubContext);
  const location = useLocation();
  const locationState = location.state;
  const registerCard = locationState?.registerCard;

  console.log('CardsRegister render - locationState:', locationState);
  console.log('CardsRegister render - registerCard:', registerCard);

  const [cardId, setCardId] = useState(undefined);
  const [actionData, setActionData] = useState({});

  useEffect(() => {
    setState(state => (omit(['rfid.card_id'], state)));
  }, [setState]);

  useEffect(() => {
    setCardId(swipedCardId || registerCard?.cardId);
  }, [registerCard, swipedCardId])

  useEffect(() => {
    console.log('useEffect triggered - locationState:', locationState);
    if (locationState?.registerCard?.actionData) {
      console.log('Setting actionData:', locationState.registerCard.actionData);
      setActionData(locationState.registerCard.actionData);
    } else {
      console.log('No actionData in locationState');
    }
  }, [locationState]);

  return (
    <CardsForm
      title={t('cards.register.register-card')}
      cardId={cardId}
      actionData={actionData}
      setActionData={setActionData}
      podcastMetadata={registerCard?.podcastMetadata}
    />
  );
};

export default CardsRegister;
