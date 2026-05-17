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

import functools
import logging
import os
import threading
import time
import hashlib
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

import jukebox.cfghandler
import jukebox.plugs as plugs
import jukebox.publishing as publishing
import components.player
from components.player.coordinator import get_coordinator

from .feed_manager import PodcastFeedManager
from .episode_queue import EpisodeQueueManager
from .state_manager import PodcastStateManager
from .episode_downloader import EpisodeDownloadManager
from .playback_state import (
    SecondSwipeDecision,
    build_queue_plan,
    decide_second_swipe,
)

logger = logging.getLogger('jb.PlayerPodcast')
cfg = jukebox.cfghandler.get_handler('jukebox')


def log_rpc_method(func):
    """Decorator to log RPC method entry/exit with timing"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"RPC CALL: {func.__name__}(args={args[1:]}, kwargs={kwargs})")
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"RPC DONE: {func.__name__} (took {elapsed:.2f}s)")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"RPC FAIL: {func.__name__} (took {elapsed:.2f}s): {e}", exc_info=True)
            raise
    return wrapper


class PlayerPodcast:
    """Podcast Player Plugin - integrates with MPD for audio playback"""

    def __init__(self):
        """Initialize Podcast player plugin"""
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

        # Episode download cache configuration
        episode_cache_cfg = cfg.getn('playerpodcast', 'episode_cache', default={})
        episode_cache_enabled = episode_cache_cfg.get('enabled', True)
        episode_cache_path = Path(episode_cache_cfg.get('cache_path',
                                                         '../../shared/cache/podcasts/episodes/')).expanduser()
        max_cache_size_mb = episode_cache_cfg.get('max_cache_size_mb', 2048)
        download_timeout = episode_cache_cfg.get('download_timeout', 300)
        min_free_space_mb = episode_cache_cfg.get('min_free_space_mb', 500)
        # Initialize episode downloader
        if episode_cache_enabled:
            self.episode_downloader = EpisodeDownloadManager(
                cache_path=episode_cache_path,
                max_cache_size_mb=max_cache_size_mb,
                download_timeout=download_timeout,
                min_free_space_mb=min_free_space_mb
            )
        else:
            self.episode_downloader = None
            logger.info("Episode cache disabled")

        # MPD symlink name for podcast cache inside music library
        self.mpd_podcast_subdir = 'podcast-cache'

        # Create symlink from MPD's music directory to episode cache
        # so MPD can access local files via relative paths
        self._setup_mpd_symlink(episode_cache_path)

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

        logger.info("Podcast player initialized")

    def _setup_mpd_symlink(self, episode_cache_path):
        """Create symlink from MPD's music directory to episode cache.

        MPD does not allow local file access via TCP connections. By symlinking
        the episode cache into MPD's music_directory, we can use relative paths
        (e.g. 'podcast-cache/ep_xxx.mp3') that MPD accepts via addid."""
        try:
            music_lib = components.player.get_music_library_path()
            if not music_lib:
                logger.warning("Could not determine MPD music library path, "
                               "local episode playback may fail")
                return

            music_lib_path = Path(os.path.expanduser(music_lib))
            symlink_path = music_lib_path / self.mpd_podcast_subdir
            cache_target = Path(episode_cache_path).resolve()

            if symlink_path.is_symlink():
                if symlink_path.resolve() == cache_target:
                    logger.debug(f"MPD symlink already correct: {symlink_path} -> {cache_target}")
                    return
                # Symlink points somewhere else, remove and recreate
                symlink_path.unlink()
            elif symlink_path.exists():
                # A regular directory exists (not a symlink) - leave it alone
                logger.warning(f"MPD podcast path exists but is not a symlink: {symlink_path}")
                return

            symlink_path.symlink_to(cache_target)
            logger.info(f"Created MPD symlink: {symlink_path} -> {cache_target}")
        except Exception as e:
            logger.warning(f"Failed to create MPD symlink: {e}")

    def _to_mpd_uri(self, local_path):
        """Convert an absolute local file path to an MPD-relative URI.

        Args:
            local_path: Absolute path to a file in the episode cache

        Returns:
            MPD-relative path like 'podcast-cache/filename.mp3'
        """
        return f"{self.mpd_podcast_subdir}/{Path(local_path).name}"

    def _position_tracking_loop(self):
        """Background thread to track and save episode position"""
        while not self.position_thread_stop.is_set():
            try:
                # Snapshot state under lock BEFORE external call
                with self.lock:
                    if not self.playback_active or not self.current_episode_guid:
                        episode_guid_snapshot = None
                    else:
                        episode_guid_snapshot = self.current_episode_guid

                if not episode_guid_snapshot:
                    time.sleep(self.save_position_interval)
                    continue

                # Make external MPD call WITHOUT holding lock (avoid blocking main thread)
                mpd_status = plugs.call('player', 'ctrl', 'playerstatus')

                if mpd_status and mpd_status.get('state') == 'play':
                    elapsed = float(mpd_status.get('elapsed', 0))
                    duration = float(mpd_status.get('duration', 0))

                    # Update state under lock
                    with self.lock:
                        # Verify episode hasn't changed during MPD call
                        if episode_guid_snapshot == self.current_episode_guid:
                            self.state_manager.update_episode_position(
                                episode_guid_snapshot,
                                elapsed,
                                duration
                            )
                        else:
                            logger.debug("Episode changed during position check, skipping save")
            except Exception as e:
                logger.debug(f"Position tracking error: {e}")

            time.sleep(self.save_position_interval)

    def _activate_podcast(self):
        """Claim the active-player slot via the coordinator.

        Triggers the outgoing backend's pause+stop (e.g. Spotify when
        coming from a music card → podcast card swipe), bounded by
        the coordinator's 5s stop timeout. Idempotent when podcast
        is already current.

        Phase 2 FU#2 decision: **podcast pins itself as the active
        backend for the duration of an episode** (option (a) from the
        meta-plan's two choices). The rationale:

        * The user-facing model is "I tapped a podcast card; the
          podcast is playing". ``coordinator.current()`` should match
          that mental model so the UI gates podcast-specific status
          rendering correctly, and the next cross-backend handoff
          pauses+stops *podcast* (saving its resume position) rather
          than MPD.
        * Podcast plays *through* MPD's wire but the user-facing
          backend is ``'podcast'``. Letting MPD's ``play_single``
          run ``_activate_mpd()`` would race the coordinator back to
          ``'mpd'``, and the next handoff (Spotify activation) would
          pause+stop *MPD* instead of *podcast* - losing the resume
          position the position-tracking thread persists.

        To keep podcast pinned, every podcast operation that drives
        MPD uses passive variants on playermpd
        (``play_single_passive`` instead of ``play_single``;
        ``pause(0)`` instead of ``play``) which do not call
        ``_activate_mpd``. The user-facing handlers ``play()`` /
        ``pause()`` / ``next()`` / ``prev()`` /
        ``_toggle_playback()`` re-pin podcast first via this method
        so any drift back to MPD self-heals on the next user
        interaction.
        """
        with get_coordinator().activate('podcast'):
            pass

    def _toggle_playback(self):
        """Toggle MPD playback state.

        Re-pins podcast as active (Phase 2 FU#2 decision) before
        delegating to MPD so the coordinator stays in sync with the
        user-facing state."""
        try:
            self._activate_podcast()
            plugs.call('player', 'ctrl', 'toggle')
            logger.info("Toggled podcast playback")
        except Exception as e:
            logger.error(f"Toggle failed: {e}")

    def _play_episode_from_queue(self, episode):
        """Play an episode, handling download/resolve and state updates.

        Shared helper for next/prev episode navigation.

        Args:
            episode: Episode dict from the feed
        """
        episode_guid = episode['guid']
        playback_url = self._resolve_playback_url(episode, resume_position=0)

        # Phase 1 follow-up #2: do NOT hold ``self.lock`` across the
        # cross-plugin call. The lock guards podcast state mutations,
        # not the MPD wire — holding it across plugs.call would block
        # every status RPC into this plugin for the duration of the
        # call and risks recursive deadlocks.
        plugs.call('player', 'ctrl', 'play_single_passive', args=(playback_url,))

        with self.lock:
            self.current_episode_guid = episode_guid
            self.playback_active = True
            self.current_episode_metadata = episode
            self.state_manager.update_last_played(
                self.current_podcast_id,
                episode_guid,
                self.current_feed_url
            )

        logger.info(f"Now playing: {episode.get('title', 'Unknown')}")

    def _get_playable_queue_for_current(self):
        """Fetch the playable episode queue for the currently active podcast.

        Returns:
            List of playable episode dicts, or empty list on failure.
        """
        with self.lock:
            feed_url = self.current_feed_url
            podcast_id = self.current_podcast_id
        if not feed_url:
            return []

        feed_data = self.feed_manager.fetch_feed(feed_url)
        if not feed_data:
            logger.warning("Failed to fetch feed for episode navigation")
            return []

        episodes = feed_data.get('episodes', [])
        if not episodes:
            return []

        playable, _ = self.queue_manager.get_playable_queue(episodes, podcast_id)
        return playable

    def _next_episode(self):
        """Skip to next episode in the podcast feed"""
        try:
            with self.lock:
                current_guid = self.current_episode_guid
            if not current_guid:
                logger.warning("next: no current episode")
                return

            playable = self._get_playable_queue_for_current()
            if not playable:
                return

            next_ep = self.queue_manager.get_next_episode(current_guid, playable)
            if not next_ep:
                logger.info("Already at last episode, nothing to skip to")
                return

            self._play_episode_from_queue(next_ep)
        except Exception as e:
            logger.error(f"Next episode failed: {e}", exc_info=True)

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

    def _resolve_playback_url(self, episode: Dict[str, Any], resume_position: float) -> str:
        """
        Resolve playback URL, always downloading episode to local cache first.

        Returns an MPD-relative path (e.g. 'podcast-cache/ep_xxx.mp3') so MPD
        can play local files reliably with seeking support. Falls back to HTTP
        streaming only if the download fails or downloader is disabled.

        Args:
            episode: Episode metadata dictionary
            resume_position: Current resume position in seconds

        Returns:
            MPD-relative path if cached/downloaded, otherwise the original stream URL
        """
        episode_guid = episode['guid']
        episode_url = episode['url']
        podcast_title = (self.current_podcast_metadata or {}).get('title', 'Unknown Podcast')

        if not self.episode_downloader:
            logger.info("Streaming from CDN (downloader disabled)")
            return episode_url

        already_cached = self.episode_downloader.is_cached(episode_guid)
        logger.info(f"Download decision: resume={resume_position}s, "
                    f"already_cached={already_cached}, will_download=True")

        try:
            local_path = self.episode_downloader.get_local_path(episode_guid)
            needs_mpd_update = False

            if not local_path:
                logger.info("Downloading episode for local playback")
                # Play waiting jingle in parallel with download
                jingle_thread = self._start_waiting_jingle()
                publishing.get_publisher().send('podcast.download_started', {
                    'episode_guid': episode_guid,
                    'episode_title': episode['title'],
                    'episode_url': episode_url
                })
                local_path = self.episode_downloader.download_episode(
                    episode_url,
                    episode_guid,
                    episode_title=episode['title'],
                    podcast_title=podcast_title
                )
                # Ensure jingle finished before starting MPD playback
                if jingle_thread:
                    jingle_thread.join()
                publishing.get_publisher().send('podcast.download_completed', {
                    'episode_guid': episode_guid,
                    'local_path': str(local_path)
                })
                needs_mpd_update = True
            else:
                logger.info(f"Using cached episode: {local_path}")

            if local_path and local_path.exists():
                mpd_uri = self._to_mpd_uri(local_path)
                if needs_mpd_update:
                    self._update_mpd_database()
                logger.info(f"Playing via MPD URI: {mpd_uri}")
                return mpd_uri
        except Exception as e:
            logger.warning(f"Download failed, falling back to stream: {e}")
            publishing.get_publisher().send('podcast.download_failed', {
                'episode_guid': episode_guid,
                'error': str(e)
            })

        return episode_url

    @staticmethod
    def _play_wav_direct(filename):
        """Play a WAV file directly via ALSA, bypassing jingle.play.

        Originally added in Phase 3b as a workaround for the plugs-lock
        starvation that ``jingle.play`` caused — holding the plugs
        module lock across the full blocking WAV playback (10-60 s
        for the waiting jingle), starving the status publisher and
        every other RPC.

        Phase 6 fixed that root cause: ``jingle.play`` now wraps the
        blocking call in
        ``jukebox.plugs.drop_module_lock_for_blocking_call()``.
        Going through ``jingle.play`` for the waiting sound would now
        be safe. We keep ``_play_wav_direct`` here anyway because:

        - It avoids the three extra RPC hops (get_volume / set_volume
          jingle / set_volume restore) the proper jingle path makes.
          The waiting jingle plays during a network download where
          start latency matters and we don't want to ride the volume
          plugin's set/restore round-trip.
        - It does not need the jingle plugin to be loaded — useful in
          stripped-down configs.

        Tests for this method live in ``test_waiting_jingle.py``;
        ``test_jingle_lock_release.py`` covers the Phase 6 fix.
        """
        try:
            import wave
            import alsaaudio
            fmt = {1: alsaaudio.PCM_FORMAT_U8, 2: alsaaudio.PCM_FORMAT_S16_LE,
                   3: alsaaudio.PCM_FORMAT_S24_3LE, 4: alsaaudio.PCM_FORMAT_S32_LE}
            with wave.open(filename, 'rb') as f:
                period_size = f.getframerate() // 8
                device = alsaaudio.PCM(
                    channels=f.getnchannels(), rate=f.getframerate(),
                    format=fmt[f.getsampwidth()], periodsize=period_size,
                    device='default')
                data = f.readframes(period_size)
                while data:
                    device.write(data)
                    data = f.readframes(period_size)
            logger.debug("Waiting jingle playback finished")
        except Exception as e:
            logger.warning(f"Could not play waiting jingle: {e}")

    def _start_waiting_jingle(self):
        """Pause MPD and start waiting jingle in a background thread.

        Returns the thread (to join later) or None if no jingle configured."""
        waiting_sound = cfg.getn('jingle', 'waiting_sound', default=None)
        if not waiting_sound:
            return None
        plugs.call_ignore_errors('player', 'ctrl', 'pause')
        thread = threading.Thread(target=self._play_wav_direct, args=(waiting_sound,),
                                  name='WaitingJingle', daemon=True)
        thread.start()
        return thread

    def _update_mpd_database(self):
        """Trigger MPD database update and wait for it to complete,
        so newly downloaded episodes are indexed before playback."""
        try:
            plugs.call('player', 'ctrl', 'update_wait')
            logger.info("MPD database update completed for new episode")
        except Exception as e:
            logger.warning(f"MPD database update failed: {e}")

    @plugs.tag
    @log_rpc_method
    def play_podcast_series(self, feed_url: str):  # noqa: C901
        """
        Play entire podcast series (newest to oldest, skip completed, auto-reset)

        Args:
            feed_url: RSS feed URL
        """
        try:
            logger.info(f"Playing podcast series: {feed_url}")

            # Second tap detection - extracted to ``playback_state.
            # decide_second_swipe`` so the decision matrix is testable
            # in isolation. We still snapshot under the lock + release
            # before the cross-plugin status RPC (Phase 1 fix #4 lock
            # discipline; see ``decide_second_swipe`` docstring).
            with self.lock:
                snap_active = self.playback_active
                snap_feed_url = self.current_feed_url
            # Only fetch MPD state if the snapshot suggests a possible
            # second swipe - otherwise we waste a wire round-trip.
            mpd_state = None
            if snap_active and snap_feed_url == feed_url:
                mpd_status = plugs.call('player', 'ctrl', 'playerstatus')
                mpd_state = mpd_status.get('state', 'stop') if mpd_status else 'stop'
            decision = decide_second_swipe(
                playback_active=snap_active,
                current_feed_url=snap_feed_url,
                incoming_feed_url=feed_url,
                mpd_state=mpd_state,
            )
            if decision is SecondSwipeDecision.INVOKE_HANDLER:
                logger.info("Second tap detected, calling second_swipe_action")
                self.second_swipe_action()
                return
            if decision is SecondSwipeDecision.CLEAR_STALE_AND_RESTART:
                logger.info("Podcast flag was active but MPD stopped, treating as first swipe")
                with self.lock:
                    self.playback_active = False
            # FRESH_START falls through to feed fetch + playback below.

            # Fetch feed
            feed_data = self.feed_manager.fetch_feed(feed_url)
            if not feed_data:
                error_msg = f"Failed to fetch podcast feed: {feed_url}"
                logger.error(error_msg)
                publishing.get_publisher().send('podcast.error', {
                    'error': 'feed_fetch_failed',
                    'feed_url': feed_url,
                    'message': error_msg
                })
                raise ValueError(error_msg)

            # Store podcast metadata for status display
            self.current_podcast_metadata = {
                'title': feed_data.get('title', 'Unknown Podcast'),
                'author': feed_data.get('author', ''),
                'image_url': feed_data.get('image_url', '')
            }

            # Build the play plan (queue + resume) via the pure seam.
            # build_queue_plan returns None if the feed is empty or the
            # filter pipeline yields no playable episodes.
            plan = build_queue_plan(
                feed_data=feed_data,
                queue_manager=self.queue_manager,
                state_manager=self.state_manager,
            )
            if plan is None:
                logger.warning("No playable episodes")
                return

            # Add/update podcast subscription now that we know we have
            # something to play (avoids polluting state on empty feeds).
            self.state_manager.add_podcast(
                plan.podcast_id,
                feed_url,
                feed_data['title'],
            )

            if plan.resume_position > 0:
                logger.info(
                    f"Resuming from episode {plan.start_index + 1}/"
                    f"{len(plan.playable_episodes)} at {plan.resume_position}s"
                )

            episode_to_play = plan.episode_to_play
            podcast_id = plan.podcast_id
            playable_episodes = plan.playable_episodes
            start_index = plan.start_index
            resume_position = plan.resume_position
            episode_guid = episode_to_play['guid']
            logger.info(f"Playing episode at index {start_index}: {episode_to_play.get('title', 'Unknown')}")

            # Resolve playback URL (cached local file or CDN stream)
            playback_url = self._resolve_playback_url(episode_to_play, resume_position)

            # Phase 2: claim the active-player slot before driving
            # playback — pauses+stops any other backend that was
            # active so its resume position is preserved.
            self._activate_podcast()

            # Phase 1 follow-up #2: cross-plugin call runs WITHOUT
            # ``self.lock``. play_single raises on failure (no return
            # value on success). Lock is reacquired below for state
            # mutations only.
            logger.info(f"Calling MPD play_single: {playback_url}")
            plugs.call('player', 'ctrl', 'play_single_passive', args=(playback_url,))
            logger.info("MPD play_single succeeded")

            # TODO: Implement playlist queuing for multiple episodes
            if len(playable_episodes) > 1:
                logger.info(f"Playing first episode of {len(playable_episodes)} episodes. "
                            "Playlist queuing not yet implemented.")

            with self.lock:
                # Update state
                self.current_podcast_id = podcast_id
                self.current_episode_guid = episode_guid
                self.current_feed_url = feed_url
                self.playback_active = True

                # Store current episode metadata for status display
                self.current_episode_metadata = episode_to_play

                self.state_manager.update_last_played(
                    podcast_id,
                    episode_guid,
                    feed_url
                )

            # Attempt to seek to resume position
            if resume_position > 0:
                # Wait for MPD to start playback
                time.sleep(1.0)
                try:
                    if playback_url.startswith('http'):
                        logger.warning("Cannot seek on HTTP stream, resume will start from beginning")
                        publishing.get_publisher().send('podcast.seek_unavailable', {
                            'episode_guid': self.current_episode_guid,
                            'resume_position': resume_position,
                            'reason': 'HTTP streams not seekable'
                        })
                    else:
                        logger.info(f"Seeking to resume position: {resume_position}s")
                        result = plugs.call('player', 'ctrl', 'seek', args=(resume_position,))
                        logger.info(f"Seek result: {result}")
                except Exception as e:
                    logger.error(f"Seek failed: {e}", exc_info=True)
                    publishing.get_publisher().send('podcast.seek_failed', {
                        'episode_guid': self.current_episode_guid,
                        'resume_position': resume_position,
                        'error': str(e)
                    })

            logger.info(f"Started playback: {len(playable_episodes)} episodes, "
                       f"starting at index {start_index}")

        except Exception as e:
            logger.error(f"Play podcast series failed: {e}", exc_info=True)

    @plugs.tag
    @log_rpc_method
    def play_podcast_episode(self, feed_url: str, episode_guid: str):  # noqa: C901
        """
        Play specific podcast episode with resume

        Args:
            feed_url: RSS feed URL
            episode_guid: Episode GUID
        """
        try:
            logger.info(f"Playing specific episode: {episode_guid}")

            # Second tap detection via the shared ``decide_second_swipe``
            # seam, matching on (feed_url, episode_guid). See
            # ``play_podcast_series`` for the rationale on the snapshot-
            # release-call pattern.
            with self.lock:
                snap_active = self.playback_active
                snap_feed_url = self.current_feed_url
                snap_guid = self.current_episode_guid
            mpd_state = None
            if (
                snap_active
                and snap_feed_url == feed_url
                and snap_guid == episode_guid
            ):
                mpd_status = plugs.call('player', 'ctrl', 'playerstatus')
                mpd_state = mpd_status.get('state', 'stop') if mpd_status else 'stop'
            decision = decide_second_swipe(
                playback_active=snap_active,
                current_feed_url=snap_feed_url,
                incoming_feed_url=feed_url,
                mpd_state=mpd_state,
                current_episode_guid=snap_guid,
                incoming_episode_guid=episode_guid,
            )
            if decision is SecondSwipeDecision.INVOKE_HANDLER:
                logger.info("Second tap detected, calling second_swipe_action")
                self.second_swipe_action()
                return
            if decision is SecondSwipeDecision.CLEAR_STALE_AND_RESTART:
                logger.info("Podcast flag was active but MPD stopped, treating as first swipe")
                with self.lock:
                    self.playback_active = False

            # Fetch feed
            feed_data = self.feed_manager.fetch_feed(feed_url)
            if not feed_data:
                logger.error("Failed to fetch podcast feed")
                return

            podcast_id = feed_data['podcast_id']
            episodes = feed_data['episodes']
            logger.debug(f"Got {len(episodes)} episodes from feed")

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

            logger.info(f"Found episode: {episode['title']}, URL: {episode['url']}")

            # Get resume position
            resume_position = self.state_manager.get_resume_position(episode_guid)
            logger.info(f"Resume position: {resume_position}s")

            # Resolve playback URL (cached local file or CDN stream)
            playback_url = self._resolve_playback_url(episode, resume_position)

            # Play via MPD
            logger.info(f"Playing episode: {episode['title']}")

            # Phase 2: claim the active-player slot before driving
            # playback — pauses+stops any other backend that was active.
            self._activate_podcast()

            # Phase 1 follow-up #2: cross-plugin call runs WITHOUT
            # ``self.lock``. Lock reacquired below for state mutations.
            plugs.call('player', 'ctrl', 'play_single_passive', args=(playback_url,))

            with self.lock:
                # Update state
                self.current_podcast_id = podcast_id
                self.current_episode_guid = episode_guid
                self.current_feed_url = feed_url
                self.playback_active = True

                self.state_manager.update_last_played(podcast_id, episode_guid, feed_url)

            # Attempt to seek to resume position
            if resume_position > 0:
                # Wait for MPD to start playback
                time.sleep(1.0)
                try:
                    if playback_url.startswith('http'):
                        logger.warning("Cannot seek on HTTP stream, resume will start from beginning")
                        publishing.get_publisher().send('podcast.seek_unavailable', {
                            'episode_guid': self.current_episode_guid,
                            'resume_position': resume_position,
                            'reason': 'HTTP streams not seekable'
                        })
                    else:
                        logger.info(f"Seeking to resume position: {resume_position}s")
                        result = plugs.call('player', 'ctrl', 'seek', args=(resume_position,))
                        logger.info(f"Seek result: {result}")
                except Exception as e:
                    logger.error(f"Seek failed: {e}", exc_info=True)
                    publishing.get_publisher().send('podcast.seek_failed', {
                        'episode_guid': self.current_episode_guid,
                        'resume_position': resume_position,
                        'error': str(e)
                    })

            logger.info(f"Finished playback start: {episode['title']}")

        except Exception as e:
            logger.error(f"Play podcast episode failed: {e}", exc_info=True)

    @plugs.tag
    @log_rpc_method
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
                logger.info(f"Second swipe detected: {feed_url} → executing {self.second_swipe_action.__name__}")
                self.second_swipe_action()
            else:
                logger.info(f"First swipe: {feed_url} (specific_episode={is_specific_episode})")
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
            # Get base MPD status (no lock needed - MPD has its own thread safety)
            mpd_status = plugs.call('player', 'ctrl', 'playerstatus')

            # Snapshot shared state under lock to avoid torn reads
            with self.lock:
                is_active = self.playback_active
                episode_meta = self.current_episode_metadata
                podcast_meta = self.current_podcast_metadata
                episode_guid = self.current_episode_guid

            if not mpd_status or not is_active:
                return {
                    'state': 'stop',
                    'elapsed': 0,
                    'duration': 0
                }

            # Build Web UI-compatible status
            status = {
                'state': mpd_status.get('state', 'stop'),
                'elapsed': float(mpd_status.get('elapsed', 0)),
                'duration': float(mpd_status.get('duration', 0)),
                'random': mpd_status.get('random', '0'),
                'repeat': mpd_status.get('repeat', '0'),
                'single': mpd_status.get('single', '0'),
            }

            if episode_meta and podcast_meta:
                status.update({
                    'songid': episode_guid,
                    'title': episode_meta.get('title', 'Unknown Episode'),
                    'artist': podcast_meta.get('author', 'Unknown Podcast'),
                    'album': podcast_meta.get('title', 'Unknown Podcast'),
                    'file': episode_meta.get('url', ''),
                    'coverart_url': podcast_meta.get('image_url', ''),
                })

            return status

        except Exception as e:
            logger.debug(f"Playerstatus error: {e}")
            return {'state': 'stop', 'elapsed': 0, 'duration': 0}

    @plugs.tag
    def stop(self):
        """Stop podcast playback"""
        try:
            # Phase 1 follow-up #2: cross-plugin call runs WITHOUT
            # ``self.lock``. State mutations are done in a second
            # critical section below.
            plugs.call('player', 'ctrl', 'stop')
            with self.lock:
                self.playback_active = False
                self.current_episode_metadata = None
                self.current_podcast_metadata = None
            logger.info("Stopped podcast playback")
        except Exception as e:
            logger.error(f"Stop failed: {e}")

    @plugs.tag
    def pause(self, state: int = 1):
        """
        Pause or resume playback. Re-pins podcast as active (Phase 2
        FU#2) so ``coordinator.current()`` stays consistent.

        Args:
            state: 1 to pause, 0 to resume
        """
        try:
            self._activate_podcast()
            plugs.call('player', 'ctrl', 'pause', args=(state,))
        except Exception as e:
            logger.error(f"Pause failed: {e}")

    @plugs.tag
    def play(self):
        """Resume playback.

        Uses MPD's passive ``pause(0)`` rather than ``play()`` because
        MPD's ``play`` is an activation event (calls ``_activate_mpd``)
        which would yank coordinator state away from podcast. Phase 2
        FU#2 decision: keep podcast pinned for the whole episode."""
        try:
            self._activate_podcast()
            plugs.call('player', 'ctrl', 'pause', args=(0,))
        except Exception as e:
            logger.error(f"Play failed: {e}")

    @plugs.tag
    def next(self):
        """Skip to next episode. ``_next_episode`` itself uses
        ``play_single_passive`` via ``_play_episode_from_queue``;
        re-pinning here is defensive against drift."""
        self._activate_podcast()
        self._next_episode()

    @plugs.tag
    def prev(self):
        """Skip to previous episode in the podcast feed. Re-pins
        podcast as active (Phase 2 FU#2)."""
        try:
            self._activate_podcast()
            with self.lock:
                current_guid = self.current_episode_guid
            if not current_guid:
                logger.warning("prev: no current episode")
                return

            playable = self._get_playable_queue_for_current()
            if not playable:
                return

            prev_ep = self.queue_manager.get_prev_episode(current_guid, playable)
            if not prev_ep:
                logger.info("Already at first episode, nothing to go back to")
                return

            self._play_episode_from_queue(prev_ep)
        except Exception as e:
            logger.error(f"Previous episode failed: {e}", exc_info=True)

    @plugs.tag
    def is_podcast_active(self) -> bool:
        """Check if the podcast player is currently driving playback.

        Used by playermpd to route next/prev commands to the podcast player
        when a podcast episode is playing. Verifies against the actual MPD
        state so the flag is cleared when another player takes over.
        """
        with self.lock:
            if not self.playback_active:
                return False

        # Verify MPD is actually playing our podcast file
        try:
            mpd_status = plugs.call('player', 'ctrl', 'playerstatus')
            current_file = mpd_status.get('file', '') if mpd_status else ''
            if current_file.startswith(self.mpd_podcast_subdir + '/'):
                return True
            # MPD is playing something else - another player took over
            with self.lock:
                self.playback_active = False
            return False
        except Exception:
            return False

    @plugs.tag
    def get_stats(self) -> Dict[str, Any]:
        """
        Get podcast statistics

        Returns:
            Dictionary with overall stats
        """
        return self.state_manager.get_stats()

    @plugs.tag
    def get_cache_stats(self):
        """
        Get episode cache statistics

        Returns:
            Dictionary with cache statistics
        """
        if self.episode_downloader:
            return self.episode_downloader.get_cache_stats()
        else:
            return {
                'episode_count': 0,
                'total_size_mb': 0,
                'max_size_mb': 0,
                'usage_percent': 0,
                'free_disk_space_mb': 0,
                'cache_path': 'N/A (cache disabled)'
            }

    @plugs.tag
    def clear_episode_cache(self):
        """Clear all downloaded episodes from cache"""
        if self.episode_downloader:
            self.episode_downloader.cleanup_cache(target_size_mb=0)
            logger.info("Episode cache cleared")
        else:
            logger.warning("Episode cache is disabled")

    @plugs.tag
    def evict_episode(self, episode_guid: str):
        """
        Remove a specific episode from cache

        Args:
            episode_guid: Episode GUID
        """
        if self.episode_downloader:
            self.episode_downloader.evict_episode(episode_guid)
        else:
            logger.warning("Episode cache is disabled")

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
        """Graceful shutdown - save state and stop threads"""
        logger.info("Shutting down podcast player...")

        # Stop background thread
        self.position_thread_stop.set()

        # Wait for thread to finish (max 5 seconds)
        if self.position_thread.is_alive():
            self.position_thread.join(timeout=5)

        # Final position save if playing.
        # Phase 1 follow-up #2: snapshot under the lock, release, then
        # do the cross-plugin call. update_episode_position writes
        # state but does not touch self.lock — safe to call from here.
        with self.lock:
            should_save = self.playback_active and self.current_episode_guid
            episode_guid = self.current_episode_guid
        if should_save:
            try:
                mpd_status = plugs.call('player', 'ctrl', 'playerstatus')
                if mpd_status:
                    elapsed = float(mpd_status.get('elapsed', 0))
                    duration = float(mpd_status.get('duration', 0))
                    self.state_manager.update_episode_position(
                        episode_guid,
                        elapsed,
                        duration
                    )
                    logger.info(f"Final position saved: {elapsed}s")
            except Exception as e:
                logger.error(f"Final position save failed: {e}")

        # Save episode cache metadata
        if self.episode_downloader:
            try:
                self.episode_downloader.save_metadata()
                logger.info("Episode cache metadata saved")
            except Exception as e:
                logger.error(f"Failed to save cache metadata: {e}")

        logger.info("Podcast player shutdown complete")


# Global player instance
player_ctrl = None


@plugs.initialize
def initialize():
    """Initialize Podcast player plugin"""
    global player_ctrl
    player_ctrl = PlayerPodcast()
    plugs.register(player_ctrl, name='ctrl')

    # Register with the player coordinator so cross-backend handoffs
    # (Spotify/MPD claiming the active slot) pause then stop the
    # podcast cleanly before the new backend takes over. pause(1)
    # delegates to MPD's pause, preserving the resume position which
    # the position-tracking thread persists to disk.
    get_coordinator().register(
        name='podcast',
        pause_fn=lambda: player_ctrl.pause(1),
        stop_fn=player_ctrl.stop,
    )

    logger.info("Podcast player plugin registered as 'playerpodcast.ctrl'")


@plugs.atexit
def atexit(**ignored_kwargs):
    """Cleanup on exit"""
    global player_ctrl
    if player_ctrl:
        return player_ctrl.exit()
