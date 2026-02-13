# -*- coding: utf-8 -*-
"""
Podcast Episode Queue Manager

Handles:
- Episode ordering (newest to oldest)
- Filtering completed episodes
- Auto-reset when all episodes completed
- Queue generation for MPD playback
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

logger = logging.getLogger('jb.PodcastEpisodeQueue')


class EpisodeQueueManager:
    """Manages podcast episode ordering and queue generation"""

    def __init__(self, state_manager):
        """
        Initialize episode queue manager

        Args:
            state_manager: PodcastStateManager instance
        """
        self.state_manager = state_manager

    def sort_episodes_newest_first(self, episodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort episodes by publish date (newest first)

        Args:
            episodes: List of episode dictionaries

        Returns:
            Sorted list of episodes
        """
        def parse_date(episode):
            try:
                date_str = episode.get('publish_date', '')
                if date_str:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return datetime.min
            except (ValueError, TypeError):
                return datetime.min

        sorted_episodes = sorted(episodes, key=parse_date, reverse=True)
        logger.debug(f"Sorted {len(sorted_episodes)} episodes by publish date (newest first)")
        return sorted_episodes

    def filter_incomplete_episodes(self, episodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out completed episodes

        Args:
            episodes: List of episode dictionaries

        Returns:
            List of incomplete episodes
        """
        incomplete = [
            ep for ep in episodes
            if not self.state_manager.is_episode_completed(ep['guid'])
        ]
        logger.debug(f"Filtered to {len(incomplete)} incomplete episodes (from {len(episodes)} total)")
        return incomplete

    def get_playable_queue(self, episodes: List[Dict[str, Any]], podcast_id: str) -> Tuple[List[Dict[str, Any]], bool]:
        """
        Get queue of playable episodes with auto-reset logic

        Args:
            episodes: List of all episodes
            podcast_id: Podcast ID

        Returns:
            Tuple of (queue of playable episodes, was_reset flag)
        """
        # Sort episodes newest first
        sorted_episodes = self.sort_episodes_newest_first(episodes)

        # Check if all episodes are completed
        progress = self.state_manager.get_podcast_progress([ep['guid'] for ep in sorted_episodes])

        was_reset = False
        if progress['all_completed'] and progress['total'] > 0:
            logger.info(f"All {progress['total']} episodes completed for podcast {podcast_id}. "
                       "Resetting all to unplayed.")
            self.state_manager.reset_podcast_episodes(
                podcast_id,
                [ep['guid'] for ep in sorted_episodes]
            )
            was_reset = True
            # After reset, all episodes are playable
            playable = sorted_episodes
        else:
            # Filter to incomplete episodes only
            playable = self.filter_incomplete_episodes(sorted_episodes)

        logger.info(f"Playable queue: {len(playable)}/{len(sorted_episodes)} episodes "
                   f"(filtered {len(sorted_episodes) - len(playable)} completed, reset: {was_reset})")
        return playable, was_reset

    def find_resume_episode(self, episodes: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], int]]:
        """
        Find the last played incomplete episode for resume

        Args:
            episodes: List of episodes (should be pre-sorted and filtered)

        Returns:
            Tuple of (episode, index) or None
        """
        last_played = self.state_manager.get_last_played()
        last_episode_guid = last_played.get('episode_guid')

        if not last_episode_guid:
            return None

        # Find the episode in the queue
        for idx, episode in enumerate(episodes):
            if episode['guid'] == last_episode_guid:
                # Check if it's still incomplete
                if not self.state_manager.is_episode_completed(last_episode_guid):
                    logger.info(f"Found resume episode: {episode['title']} at index {idx}")
                    return episode, idx

        logger.debug("No resume episode found in current queue")
        return None

    def generate_mpd_playlist(self, episodes: List[Dict[str, Any]]) -> List[str]:
        """
        Generate list of episode URLs for MPD playback

        Args:
            episodes: List of episode dictionaries

        Returns:
            List of episode URLs
        """
        playlist = [ep['url'] for ep in episodes if ep.get('url')]
        logger.debug(f"Generated MPD playlist with {len(playlist)} URLs")
        return playlist

    def get_episode_by_guid(self, episodes: List[Dict[str, Any]], episode_guid: str) -> Optional[Dict[str, Any]]:
        """
        Find episode by GUID

        Args:
            episodes: List of episode dictionaries
            episode_guid: Episode GUID to find

        Returns:
            Episode dictionary or None
        """
        for episode in episodes:
            if episode['guid'] == episode_guid:
                return episode
        return None

    def get_next_episode(self, current_episode_guid: str, episodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Get next episode in queue after current episode

        Args:
            current_episode_guid: Current episode GUID
            episodes: List of episodes (should be sorted)

        Returns:
            Next episode or None
        """
        try:
            current_idx = next(
                idx for idx, ep in enumerate(episodes)
                if ep['guid'] == current_episode_guid
            )
            if current_idx < len(episodes) - 1:
                next_ep = episodes[current_idx + 1]
                logger.debug(f"Next episode: {next_ep['title']}")
                return next_ep
        except StopIteration:
            pass

        logger.debug("No next episode in queue")
        return None

    def get_prev_episode(self, current_episode_guid: str, episodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Get previous episode in queue before current episode

        Args:
            current_episode_guid: Current episode GUID
            episodes: List of episodes (should be sorted)

        Returns:
            Previous episode or None
        """
        try:
            current_idx = next(
                idx for idx, ep in enumerate(episodes)
                if ep['guid'] == current_episode_guid
            )
            if current_idx > 0:
                prev_ep = episodes[current_idx - 1]
                logger.debug(f"Previous episode: {prev_ep['title']}")
                return prev_ep
        except StopIteration:
            pass

        logger.debug("No previous episode in queue")
        return None

    def get_queue_info(self, episodes: List[Dict[str, Any]], podcast_id: str) -> Dict[str, Any]:
        """
        Get comprehensive queue information

        Args:
            episodes: List of all episodes
            podcast_id: Podcast ID

        Returns:
            Dictionary with queue statistics
        """
        sorted_episodes = self.sort_episodes_newest_first(episodes)
        progress = self.state_manager.get_podcast_progress([ep['guid'] for ep in sorted_episodes])
        playable, was_reset = self.get_playable_queue(episodes, podcast_id)

        return {
            'total_episodes': len(sorted_episodes),
            'completed': progress['completed'],
            'incomplete': progress['incomplete'],
            'playable_count': len(playable),
            'all_completed': progress['all_completed'],
            'was_reset': was_reset,
            'newest_episode': sorted_episodes[0] if sorted_episodes else None,
            'oldest_episode': sorted_episodes[-1] if sorted_episodes else None
        }
