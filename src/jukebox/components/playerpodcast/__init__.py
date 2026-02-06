# -*- coding: utf-8 -*-
"""
Podcast Player Plugin for Phoniebox V3

This plugin integrates podcast streaming with Phoniebox using iTunes Search API
for podcast discovery and RSS feeds for episode playback. It delegates audio playback
to MPD while managing podcast-specific intelligence (feed parsing, episode ordering,
state persistence, completion tracking).

Architecture:
- iTunes Search API: Podcast discovery without authentication
- RSS feeds: Episode metadata and audio URLs via feedparser
- MPD delegation: Audio playback via playermpd plugin
- State persistence: Episode positions, completion status, subscriptions
- Smart queuing: Newest-to-oldest ordering with auto-reset

Features:
- Search/discover podcasts via iTunes API or manual RSS URL
- Play entire podcast series (auto-resume, skip completed episodes)
- Play specific episodes with resume capability
- Second swipe detection for pause/play toggle
- Automatic episode completion tracking (>90% threshold)
- Auto-reset: When all episodes completed, restart from newest

Requirements:
- feedparser >= 6.0.10
- MPD player (playermpd plugin)

References:
- https://github.com/kurtmckee/feedparser
- https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
"""

import logging
import threading
import time
import hashlib
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

import jukebox.cfghandler
import jukebox.plugs as plugs
import jukebox.publishing as publishing
from jukebox.NvManager import nv_manager

from .feed_manager import PodcastFeedManager
from .episode_queue import EpisodeQueueManager
from .state_manager import PodcastStateManager

logger = logging.getLogger('jb.PlayerPodcast')
cfg = jukebox.cfghandler.get_handler('jukebox')


class PlayerPodcast:
    """Podcast Player Plugin - integrates with MPD for audio playback"""

    def __init__(self):
        """Initialize Podcast player plugin"""
        self.nvm = nv_manager()

        # Load configuration
        self.status_file = cfg.getn('playerpodcast', 'status_file',
                                    default='../../shared/settings/podcast_player_status.json')
        self.feed_cache_path = cfg.getn('playerpodcast', 'feed_cache_path',
                                        default='../../shared/cache/podcasts/')
        self.feed_cache_ttl = cfg.getn('playerpodcast', 'feed_cache_ttl', default=3600)
        self.save_position_interval = cfg.getn('playerpodcast', 'save_position_interval', default=10)
        self.completion_threshold = cfg.getn('playerpodcast', 'completion_threshold', default=0.9)
        self.episode_order = cfg.getn('playerpodcast', 'episode_order', default='newest_first')
        self.coverart_cache_path = Path(cfg.getn('webapp', 'coverart_cache_path',
                                                  default='../../src/webapp/build/cover-cache')).expanduser()

        # iTunes API configuration
        itunes_enabled = cfg.getn('playerpodcast', 'itunes_api', 'enabled', default=True)
        itunes_search_limit = cfg.getn('playerpodcast', 'itunes_api', 'search_limit', default=20)

        # Initialize managers
        self.lock = threading.RLock()
        self.state_manager = PodcastStateManager(
            self.nvm,
            self.status_file,
            self.completion_threshold
        )
        self.feed_manager = PodcastFeedManager(
            cache_path=self.feed_cache_path,
            cache_ttl=self.feed_cache_ttl,
            itunes_enabled=itunes_enabled,
            itunes_search_limit=itunes_search_limit
        )
        self.queue_manager = EpisodeQueueManager(self.state_manager)

        # Playback state
        self.current_podcast_id = None
        self.current_episode_guid = None
        self.current_feed_url = None
        self.playback_active = False
        self.current_episode_metadata = None
        self.current_podcast_metadata = None

        # Second swipe action configuration
        second_swipe_option = cfg.getn('playerpodcast', 'second_swipe_action', 'alias',
                                       default='toggle')
        self.second_swipe_action_dict = {
            'toggle': self._toggle_playback,
            'next_episode': self._next_episode,
            'none': lambda: None
        }
        self.second_swipe_action = self.second_swipe_action_dict.get(
            second_swipe_option,
            self._toggle_playback
        )

        # Start position tracking thread
        self.position_thread = threading.Thread(target=self._position_tracking_loop, daemon=True)
        self.position_thread_stop = threading.Event()
        self.position_thread.start()

        # Start status publishing thread
        self.status_thread = threading.Thread(target=self._status_publisher_loop, daemon=True)
        self.status_thread_stop = threading.Event()
        self.status_thread.start()

        logger.info("Podcast player initialized")

    def _position_tracking_loop(self):
        """Background thread to track and save episode position"""
        while not self.position_thread_stop.is_set():
            try:
                if self.playback_active and self.current_episode_guid:
                    # Get current position from MPD
                    mpd_status = plugs.call('player', 'ctrl', 'playerstatus')
                    if mpd_status and mpd_status.get('state') == 'play':
                        elapsed = float(mpd_status.get('elapsed', 0))
                        duration = float(mpd_status.get('duration', 0))

                        # Save position
                        with self.lock:
                            self.state_manager.update_episode_position(
                                self.current_episode_guid,
                                elapsed,
                                duration
                            )
            except Exception as e:
                logger.debug(f"Position tracking error: {e}")

            time.sleep(self.save_position_interval)

    def _status_publisher_loop(self):
        """
        Background thread - No longer publishes status directly.

        MPD's status publisher now handles publishing and enriches with podcast
        metadata by calling our playerstatus() method when playing podcast URLs.
        This thread kept for potential future use.
        """
        while not self.status_thread_stop.is_set():
            time.sleep(1)

    def _toggle_playback(self):
        """Toggle MPD playback state"""
        try:
            plugs.call('player', 'ctrl', 'toggle')
            logger.info("Toggled podcast playback")
        except Exception as e:
            logger.error(f"Toggle failed: {e}")

    def _next_episode(self):
        """Skip to next episode"""
        try:
            plugs.call('player', 'ctrl', 'next')
            logger.info("Skipped to next episode")
        except Exception as e:
            logger.error(f"Next episode failed: {e}")

    @plugs.tag
    def get_player_type_and_version(self):
        """Return player type and version"""
        return {'player': 'Podcast', 'version': 'feedparser 6.0.10'}

    @plugs.tag
    def search_podcasts(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for podcasts using iTunes Search API

        Args:
            query: Search query string

        Returns:
            List of podcast search results
        """
        try:
            logger.info(f"Searching for podcasts: {query}")
            results = self.feed_manager.search_itunes(query)
            logger.info(f"Found {len(results)} podcasts")
            return results
        except Exception as e:
            logger.error(f"Podcast search failed: {e}")
            return []

    @plugs.tag
    def get_episodes(self, feed_url: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get episodes from a podcast feed

        Args:
            feed_url: RSS feed URL
            force_refresh: Force fresh fetch

        Returns:
            List of episode dictionaries
        """
        try:
            logger.info(f"Getting episodes for: {feed_url}")
            episodes = self.feed_manager.get_episodes(feed_url, force_refresh)
            logger.info(f"Retrieved {len(episodes)} episodes")
            return episodes
        except Exception as e:
            logger.error(f"Get episodes failed: {e}")
            return []

    @plugs.tag
    def get_podcast_info(self, feed_url: str) -> Dict[str, Any]:
        """
        Get podcast metadata from feed URL

        Args:
            feed_url: RSS feed URL

        Returns:
            Podcast metadata dict with title, author, image_url, description
        """
        try:
            logger.info(f"Getting podcast info for: {feed_url}")
            feed_data = self.feed_manager.fetch_feed(feed_url, force_refresh=False)
            if feed_data:
                # Return just the metadata, not the episodes
                return {
                    'title': feed_data.get('title', 'Unknown Podcast'),
                    'author': feed_data.get('author', ''),
                    'image_url': feed_data.get('image_url', ''),
                    'description': feed_data.get('description', ''),
                    'feed_url': feed_url,
                }
            return {}
        except Exception as e:
            logger.error(f"Get podcast info failed: {e}")
            return {}

    @plugs.tag
    def refresh_feed(self, feed_url: str) -> bool:
        """
        Force refresh of podcast feed

        Args:
            feed_url: RSS feed URL

        Returns:
            True if successful
        """
        try:
            logger.info(f"Refreshing feed: {feed_url}")
            feed_data = self.feed_manager.fetch_feed(feed_url, force_refresh=True)
            return feed_data is not None
        except Exception as e:
            logger.error(f"Feed refresh failed: {e}")
            return False

    @plugs.tag
    def play_podcast_series(self, feed_url: str):
        """
        Play entire podcast series (newest to oldest, skip completed, auto-reset)

        Args:
            feed_url: RSS feed URL
        """
        try:
            logger.info(f"Playing podcast series: {feed_url}")

            # Fetch feed
            feed_data = self.feed_manager.fetch_feed(feed_url)
            if not feed_data:
                logger.error("Failed to fetch podcast feed")
                return

            podcast_id = feed_data['podcast_id']
            episodes = feed_data['episodes']

            # Store podcast metadata for status display
            self.current_podcast_metadata = {
                'title': feed_data.get('title', 'Unknown Podcast'),
                'author': feed_data.get('author', ''),
                'image_url': feed_data.get('image_url', '')
            }

            if not episodes:
                logger.warning("No episodes found in feed")
                return

            # Add/update podcast subscription
            self.state_manager.add_podcast(
                podcast_id,
                feed_url,
                feed_data['title']
            )

            # Generate playable queue (auto-reset if all completed)
            playable_episodes, was_reset = self.queue_manager.get_playable_queue(
                episodes,
                podcast_id
            )

            if not playable_episodes:
                logger.warning("No playable episodes")
                return

            # Check for resume
            resume_info = self.queue_manager.find_resume_episode(playable_episodes)
            start_index = 0
            resume_position = 0

            if resume_info and not was_reset:
                resume_episode, resume_index = resume_info
                start_index = resume_index
                resume_position = self.state_manager.get_resume_position(resume_episode['guid'])
                logger.info(f"Resuming from episode {resume_index + 1}/{len(playable_episodes)} "
                           f"at {resume_position}s")

            # Play via MPD - start with the first (or resume) episode
            episode_to_play = playable_episodes[start_index]

            with self.lock:
                # Use MPD's play_single method to play the episode URL
                plugs.call('player', 'ctrl', 'play_single', args=(episode_to_play['url'],))

                # TODO: Implement resume position seeking
                if resume_position > 0:
                    logger.warning(f"Resume position {resume_position}s not yet implemented for podcast series")

                # TODO: Implement playlist queuing for multiple episodes
                if len(playable_episodes) > 1:
                    logger.info(f"Playing first episode of {len(playable_episodes)} episodes. "
                              "Playlist queuing not yet implemented.")

                # Update state
                self.current_podcast_id = podcast_id
                self.current_episode_guid = episode_to_play['guid']
                self.current_feed_url = feed_url
                self.playback_active = True

                # Store current episode metadata for status display
                self.current_episode_metadata = episode_to_play

                self.state_manager.update_last_played(
                    podcast_id,
                    self.current_episode_guid,
                    feed_url
                )

            logger.info(f"Started playback: {len(playable_episodes)} episodes, "
                       f"starting at index {start_index}")

        except Exception as e:
            logger.error(f"Play podcast series failed: {e}", exc_info=True)

    @plugs.tag
    def play_podcast_episode(self, feed_url: str, episode_guid: str):
        """
        Play specific podcast episode with resume

        Args:
            feed_url: RSS feed URL
            episode_guid: Episode GUID
        """
        logger.warning(f"[DEBUG] play_podcast_episode called with feed_url={feed_url}, episode_guid={episode_guid}")
        try:
            logger.info(f"Playing specific episode: {episode_guid}")

            # Fetch feed
            logger.warning(f"[DEBUG] Fetching feed from {feed_url}")
            feed_data = self.feed_manager.fetch_feed(feed_url)
            if not feed_data:
                logger.error("Failed to fetch podcast feed")
                return

            podcast_id = feed_data['podcast_id']
            episodes = feed_data['episodes']
            logger.warning(f"[DEBUG] Got {len(episodes)} episodes from feed")

            # Store podcast metadata for status display
            self.current_podcast_metadata = {
                'title': feed_data.get('title', 'Unknown Podcast'),
                'author': feed_data.get('author', ''),
                'image_url': feed_data.get('image_url', '')
            }

            # Find specific episode
            episode = self.queue_manager.get_episode_by_guid(episodes, episode_guid)
            if not episode:
                logger.error(f"Episode not found: {episode_guid}")
                return

            # Store episode metadata for status display
            self.current_episode_metadata = episode

            logger.warning(f"[DEBUG] Found episode: {episode['title']}, URL: {episode['url']}")

            # Get resume position
            resume_position = self.state_manager.get_resume_position(episode_guid)
            logger.warning(f"[DEBUG] Resume position: {resume_position}")

            # Play via MPD
            logger.warning("[DEBUG] About to play via MPD")
            with self.lock:
                # Use playermpd's play_single method to play the URL
                logger.warning(f"[DEBUG] Calling player.ctrl.play_single with URL: {episode['url']}")
                plugs.call('player', 'ctrl', 'play_single', args=(episode['url'],))
                logger.warning("[DEBUG] play_single completed")

                # TODO: Implement resume position seeking
                if resume_position > 0:
                    logger.warning(f"[DEBUG] Resume position {resume_position}s not yet implemented for podcasts")
                    # Need to implement seeking after playback starts

                # Update state
                self.current_podcast_id = podcast_id
                self.current_episode_guid = episode_guid
                self.current_feed_url = feed_url
                self.playback_active = True

                self.state_manager.update_last_played(podcast_id, episode_guid, feed_url)

            logger.warning(f"[DEBUG] Finished play_podcast_episode, episode: {episode['title']}")

        except Exception as e:
            logger.error(f"Play podcast episode failed: {e}", exc_info=True)

    @plugs.tag
    def play_card(self, uri: str):
        """
        Play podcast triggered by RFID card with second swipe detection

        Args:
            uri: Feed URL or feed_url::episode_guid for specific episodes
        """
        try:
            last_played = self.state_manager.get_last_played()
            last_uri = last_played.get('feed_url', '')

            # Parse URI (support both series and specific episodes)
            if '::' in uri:
                feed_url, episode_guid = uri.split('::', 1)
                is_specific_episode = True
            else:
                feed_url = uri
                episode_guid = None
                is_specific_episode = False

            # Second swipe detection
            if last_uri == feed_url:
                logger.info(f"Second swipe detected for: {feed_url}")
                self.second_swipe_action()
            else:
                logger.info(f"First swipe: {feed_url}")
                if is_specific_episode:
                    self.play_podcast_episode(feed_url, episode_guid)
                else:
                    self.play_podcast_series(feed_url)

        except Exception as e:
            logger.error(f"Play card failed: {e}")

    @plugs.tag
    def playerstatus(self) -> Dict[str, Any]:
        """
        Get current player status in Web UI-compatible format

        Returns:
            Dictionary with playback state compatible with Web UI Player component
        """
        try:
            # Get base MPD status
            mpd_status = plugs.call('player', 'ctrl', 'playerstatus')

            if not mpd_status or not self.playback_active:
                # Return minimal status when not playing
                return {
                    'state': 'stop',
                    'elapsed': 0,
                    'duration': 0
                }

            # Build Web UI-compatible status
            status = {
                # Playback state from MPD
                'state': mpd_status.get('state', 'stop'),
                'elapsed': float(mpd_status.get('elapsed', 0)),
                'duration': float(mpd_status.get('duration', 0)),
                'random': mpd_status.get('random', '0'),
                'repeat': mpd_status.get('repeat', '0'),
                'single': mpd_status.get('single', '0'),
            }

            # Add podcast metadata if available
            if self.current_episode_metadata and self.current_podcast_metadata:
                status.update({
                    'songid': self.current_episode_guid,  # For UI existence check
                    'title': self.current_episode_metadata.get('title', 'Unknown Episode'),
                    'artist': self.current_podcast_metadata.get('author', 'Unknown Podcast'),
                    'album': self.current_podcast_metadata.get('title', 'Unknown Podcast'),
                    'file': self.current_episode_metadata.get('url', ''),  # Audio URL for reference
                    'coverart_url': self.current_podcast_metadata.get('image_url', ''),  # Podcast artwork URL
                })

            return status

        except Exception as e:
            logger.debug(f"Playerstatus error: {e}")
            return {'state': 'stop', 'elapsed': 0, 'duration': 0}

    @plugs.tag
    def stop(self):
        """Stop podcast playback"""
        try:
            with self.lock:
                plugs.call('player', 'ctrl', 'stop')
                self.playback_active = False
                self.current_episode_metadata = None
                self.current_podcast_metadata = None
            logger.info("Stopped podcast playback")
        except Exception as e:
            logger.error(f"Stop failed: {e}")

    @plugs.tag
    def pause(self, state: int = 1):
        """
        Pause or resume playback

        Args:
            state: 1 to pause, 0 to resume
        """
        try:
            plugs.call('player', 'ctrl', 'pause', state)
        except Exception as e:
            logger.error(f"Pause failed: {e}")

    @plugs.tag
    def play(self):
        """Resume playback"""
        try:
            plugs.call('player', 'ctrl', 'play')
        except Exception as e:
            logger.error(f"Play failed: {e}")

    @plugs.tag
    def next(self):
        """Skip to next episode"""
        self._next_episode()

    @plugs.tag
    def prev(self):
        """Skip to previous episode"""
        try:
            plugs.call('player', 'ctrl', 'prev')
            logger.info("Skipped to previous episode")
        except Exception as e:
            logger.error(f"Previous episode failed: {e}")

    @plugs.tag
    def get_stats(self) -> Dict[str, Any]:
        """
        Get podcast statistics

        Returns:
            Dictionary with overall stats
        """
        return self.state_manager.get_stats()

    @plugs.tag
    def get_coverart(self, episode_url: str) -> str:
        """
        Get cached podcast cover art for a given episode URL

        Downloads and caches the podcast artwork if not already cached.
        Uses the podcast's artwork (not episode-specific, as podcasts typically
        have one artwork for the entire show).

        Args:
            episode_url: The episode audio URL (used to identify the podcast)

        Returns:
            Cached cover art filename or empty string if not available
        """
        try:
            logger.info(f"get_coverart called for URL: {episode_url}")

            # Check if we have podcast metadata
            if not self.current_podcast_metadata:
                logger.warning("No podcast metadata available")
                return ''

            # Get the podcast image URL
            image_url = self.current_podcast_metadata.get('image_url')
            if not image_url:
                logger.warning("No image_url in podcast metadata")
                return ''

            logger.info(f"Podcast image URL: {image_url}")

            # Generate cache key based on image URL
            cache_key = f"cover-{hashlib.sha256(image_url.encode()).hexdigest()}"

            # Check if already cached
            for path in self.coverart_cache_path.iterdir():
                if path.stem == cache_key:
                    logger.info(f"Found cached cover art: {path.name}")
                    return path.name

            # Download and cache the image
            logger.info(f"Downloading podcast cover art from {image_url}")
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()

            # Determine file extension from content type
            content_type = response.headers.get('content-type', '')
            if 'jpeg' in content_type or 'jpg' in content_type:
                ext = 'jpg'
            elif 'png' in content_type:
                ext = 'png'
            else:
                ext = 'jpg'  # Default to jpg

            # Save to cache
            cache_filename = f"{cache_key}.{ext}"
            cache_path = self.coverart_cache_path / cache_filename
            with cache_path.open('wb') as f:
                f.write(response.content)

            logger.info(f"Cached podcast cover art as {cache_filename}")
            return cache_filename

        except Exception as e:
            logger.error(f"Failed to get podcast cover art: {e}", exc_info=True)
            return ''

    def exit(self):
        """Cleanup on plugin shutdown"""
        logger.info("Shutting down podcast player")
        self.position_thread_stop.set()
        self.status_thread_stop.set()

        if self.position_thread.is_alive():
            self.position_thread.join(timeout=2)
        if self.status_thread.is_alive():
            self.status_thread.join(timeout=2)


# Global player instance
player_ctrl = None


@plugs.initialize
def initialize():
    """Initialize Podcast player plugin"""
    global player_ctrl
    player_ctrl = PlayerPodcast()
    plugs.register(player_ctrl, name='ctrl')
    logger.info("Podcast player plugin registered as 'playerpodcast.ctrl'")


@plugs.atexit
def atexit(**ignored_kwargs):
    """Cleanup on exit"""
    global player_ctrl
    if player_ctrl:
        return player_ctrl.exit()
