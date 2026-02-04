# -*- coding: utf-8 -*-
"""
Podcast State Manager - Playback state persistence and tracking

Handles:
- Episode playback position tracking
- Episode completion status
- Podcast subscription management
- Resume playback state
"""

import logging
from typing import Dict, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger('jb.PodcastStateManager')


class PodcastStateManager:
    """Manages podcast playback state and persistence"""

    def __init__(self, nvm, status_file: str, completion_threshold: float = 0.9):
        """
        Initialize state manager

        Args:
            nvm: NvManager instance for persistence
            status_file: Path to status JSON file
            completion_threshold: Percentage threshold for episode completion (0.0-1.0)
        """
        self.nvm = nvm
        self.status_file = status_file
        self.completion_threshold = completion_threshold

        # Load or initialize state
        self.state = self.nvm.load(status_file)
        if not self.state:
            self.state = {
                'podcasts': {},      # podcast_id -> podcast metadata
                'episodes': {},      # episode_guid -> episode state
                'last_played': {     # Last played podcast/episode for resume
                    'podcast_id': None,
                    'episode_guid': None,
                    'feed_url': None
                }
            }
            self._save()

        logger.info(f"Podcast state loaded: {len(self.state.get('podcasts', {}))} podcasts, "
                    f"{len(self.state.get('episodes', {}))} episodes tracked")

    def _save(self):
        """Save state to disk"""
        self.nvm.save(self.state, self.status_file)

    def add_podcast(self, podcast_id: str, feed_url: str, title: str):
        """
        Add or update podcast subscription

        Args:
            podcast_id: Unique podcast ID
            feed_url: RSS feed URL
            title: Podcast title
        """
        if 'podcasts' not in self.state:
            self.state['podcasts'] = {}

        self.state['podcasts'][podcast_id] = {
            'feed_url': feed_url,
            'title': title,
            'last_fetched': datetime.now(timezone.utc).isoformat(),
            'subscribed_at': self.state['podcasts'].get(podcast_id, {}).get(
                'subscribed_at', datetime.now(timezone.utc).isoformat()
            )
        }
        self._save()
        logger.info(f"Added/updated podcast: {title} ({podcast_id})")

    def remove_podcast(self, podcast_id: str):
        """
        Remove podcast subscription

        Args:
            podcast_id: Unique podcast ID
        """
        if podcast_id in self.state.get('podcasts', {}):
            del self.state['podcasts'][podcast_id]
            self._save()
            logger.info(f"Removed podcast: {podcast_id}")

    def get_podcast(self, podcast_id: str) -> Optional[Dict[str, Any]]:
        """
        Get podcast metadata

        Args:
            podcast_id: Unique podcast ID

        Returns:
            Podcast metadata or None
        """
        return self.state.get('podcasts', {}).get(podcast_id)

    def list_podcasts(self) -> Dict[str, Dict[str, Any]]:
        """
        List all subscribed podcasts

        Returns:
            Dictionary of podcast_id -> metadata
        """
        return self.state.get('podcasts', {})

    def get_episode_state(self, episode_guid: str) -> Dict[str, Any]:
        """
        Get episode playback state

        Args:
            episode_guid: Episode GUID

        Returns:
            Episode state dictionary with position, completed status
        """
        if 'episodes' not in self.state:
            self.state['episodes'] = {}

        if episode_guid not in self.state['episodes']:
            self.state['episodes'][episode_guid] = {
                'position_seconds': 0,
                'completed': False,
                'last_played': None,
                'duration_seconds': 0
            }

        return self.state['episodes'][episode_guid]

    def update_episode_position(self, episode_guid: str, position_seconds: float,
                                duration_seconds: float = 0):
        """
        Update episode playback position

        Args:
            episode_guid: Episode GUID
            position_seconds: Current position in seconds
            duration_seconds: Episode duration in seconds (optional)
        """
        if 'episodes' not in self.state:
            self.state['episodes'] = {}

        episode_state = self.get_episode_state(episode_guid)
        episode_state['position_seconds'] = position_seconds
        episode_state['last_played'] = datetime.now(timezone.utc).isoformat()

        if duration_seconds > 0:
            episode_state['duration_seconds'] = duration_seconds

            # Check for completion
            if duration_seconds > 0 and position_seconds / duration_seconds >= self.completion_threshold:
                episode_state['completed'] = True
                logger.info(f"Episode marked as completed: {episode_guid}")

        self.state['episodes'][episode_guid] = episode_state
        self._save()

    def mark_episode_completed(self, episode_guid: str, completed: bool = True):
        """
        Manually mark episode as completed or incomplete

        Args:
            episode_guid: Episode GUID
            completed: Completion status
        """
        episode_state = self.get_episode_state(episode_guid)
        episode_state['completed'] = completed
        self.state['episodes'][episode_guid] = episode_state
        self._save()
        logger.info(f"Episode {episode_guid} marked as {'completed' if completed else 'incomplete'}")

    def is_episode_completed(self, episode_guid: str) -> bool:
        """
        Check if episode is completed

        Args:
            episode_guid: Episode GUID

        Returns:
            True if completed
        """
        return self.get_episode_state(episode_guid).get('completed', False)

    def reset_podcast_episodes(self, podcast_id: str, episode_guids: list):
        """
        Reset all episodes of a podcast to unplayed state

        Args:
            podcast_id: Podcast ID
            episode_guids: List of episode GUIDs to reset
        """
        count = 0
        for episode_guid in episode_guids:
            if episode_guid in self.state.get('episodes', {}):
                self.state['episodes'][episode_guid]['completed'] = False
                self.state['episodes'][episode_guid]['position_seconds'] = 0
                count += 1

        self._save()
        logger.info(f"Reset {count} episodes for podcast {podcast_id}")

    def get_podcast_progress(self, episode_guids: list) -> Dict[str, Any]:
        """
        Get progress statistics for a podcast

        Args:
            episode_guids: List of episode GUIDs

        Returns:
            Dictionary with completed/total counts
        """
        total = len(episode_guids)
        completed = sum(1 for guid in episode_guids if self.is_episode_completed(guid))
        incomplete = total - completed

        return {
            'total': total,
            'completed': completed,
            'incomplete': incomplete,
            'all_completed': incomplete == 0
        }

    def update_last_played(self, podcast_id: str, episode_guid: str, feed_url: str):
        """
        Update last played podcast/episode for resume

        Args:
            podcast_id: Podcast ID
            episode_guid: Episode GUID
            feed_url: Feed URL
        """
        if 'last_played' not in self.state:
            self.state['last_played'] = {}

        self.state['last_played'] = {
            'podcast_id': podcast_id,
            'episode_guid': episode_guid,
            'feed_url': feed_url,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        self._save()

    def get_last_played(self) -> Dict[str, Any]:
        """
        Get last played podcast/episode

        Returns:
            Dictionary with podcast_id, episode_guid, feed_url
        """
        return self.state.get('last_played', {
            'podcast_id': None,
            'episode_guid': None,
            'feed_url': None
        })

    def get_resume_position(self, episode_guid: str) -> float:
        """
        Get resume position for an episode

        Args:
            episode_guid: Episode GUID

        Returns:
            Position in seconds
        """
        episode_state = self.get_episode_state(episode_guid)
        return episode_state.get('position_seconds', 0)

    def clear_podcast_data(self, podcast_id: str):
        """
        Clear all episode data for a podcast

        Args:
            podcast_id: Podcast ID
        """
        if 'episodes' not in self.state:
            return

        # Find and remove all episodes for this podcast
        episodes_to_remove = [
            guid for guid, state in self.state['episodes'].items()
            if state.get('podcast_id') == podcast_id
        ]

        for guid in episodes_to_remove:
            del self.state['episodes'][guid]

        self._save()
        logger.info(f"Cleared {len(episodes_to_remove)} episodes for podcast {podcast_id}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get overall statistics

        Returns:
            Dictionary with podcast and episode counts
        """
        total_episodes = len(self.state.get('episodes', {}))
        completed_episodes = sum(
            1 for ep in self.state.get('episodes', {}).values()
            if ep.get('completed', False)
        )

        return {
            'total_podcasts': len(self.state.get('podcasts', {})),
            'total_episodes_tracked': total_episodes,
            'completed_episodes': completed_episodes,
            'incomplete_episodes': total_episodes - completed_episodes
        }
