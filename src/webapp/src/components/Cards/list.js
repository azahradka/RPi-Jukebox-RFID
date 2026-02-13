import React, { forwardRef, useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { isNil, reject } from 'ramda';
import { useTranslation } from 'react-i18next';

import {
  Avatar,
  List,
  ListItem,
  ListItemAvatar,
  ListItemText,
  Typography
} from '@mui/material';

import BookmarkIcon from '@mui/icons-material/Bookmark';
import request from '../../utils/request';

const PodcastCardItem = ({ cardId, cardData, EditCardLink }) => {
  const [podcastTitle, setPodcastTitle] = useState(null);
  const { t } = useTranslation();

  useEffect(() => {
    const feedUrl = cardData.action?.args?.[0];
    if (feedUrl && (cardData.from_alias === 'play_podcast_series' || cardData.from_alias === 'play_podcast_episode')) {
      request('getPodcastInfo', { feed_url: feedUrl })
        .then(({ result }) => {
          if (result?.title) {
            setPodcastTitle(result.title);
          }
        })
        .catch(() => {
          // Ignore errors, will show feed URL
        });
    }
  }, [cardData]);

  const actionLabel = cardData.from_alias === 'play_podcast_series'
    ? t('cards.list.play-podcast-series', 'Play Podcast')
    : t('cards.list.play-podcast-episode', 'Play Episode');

  const description = podcastTitle
    ? `${actionLabel}: ${podcastTitle}`
    : `${actionLabel}: ${cardData.action?.args?.[0] || ''}`;

  return (
    <ListItem
      button
      component={EditCardLink}
      data={{ id: cardId, ...cardData }}
      key={cardId}
    >
      <ListItemAvatar>
        <Avatar>
          <BookmarkIcon />
        </Avatar>
      </ListItemAvatar>
      <ListItemText
        primary={cardId}
        secondary={description}
      />
    </ListItem>
  );
};

const CardsList = ({ cardsList }) => {
  const { t } = useTranslation();

  const ListItemLink = (cardId) => {
    const cardData = cardsList[cardId];
    const EditCardLink = forwardRef((props, ref) => {
      const { data } = props;
      const location = {
        pathname: `/cards/${data.id}/edit`,
        state: data,
      };

      return <Link ref={ref} to={location} {...props} />
    });

    // Check if this is a podcast card
    const isPodcastCard = cardData.from_alias === 'play_podcast_series' ||
                          cardData.from_alias === 'play_podcast_episode';

    if (isPodcastCard) {
      return (
        <PodcastCardItem
          key={cardId}
          cardId={cardId}
          cardData={cardData}
          EditCardLink={EditCardLink}
        />
      );
    }

    // Default card display
    const description = cardData.from_alias
      ? reject(
          isNil,
          [cardData.from_alias, cardData.action.args]
        ).join(', ')
      : cardData.func

    return (
      <ListItem
        button
        component={EditCardLink}
        data={{ id: cardId, ...cardData }}
        key={cardId}
      >
        <ListItemAvatar>
          <Avatar>
            <BookmarkIcon />
          </Avatar>
        </ListItemAvatar>
        <ListItemText
          primary={cardId}
          secondary={description}
        />
      </ListItem>
    );
  }

  return (
    cardsList && Object.keys(cardsList).length > 0
      ? <List sx={{ width: '100%' }}>
          {Object.keys(cardsList).map(ListItemLink)}
        </List>
      : <Typography>{t('cards.list.no-cards-registered')}</Typography>
  );
}

export default React.memo(CardsList);
