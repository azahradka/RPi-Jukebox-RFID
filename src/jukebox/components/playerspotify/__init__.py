# -*- coding: utf-8 -*-
"""
Spotify Player Plugin for Phoniebox V3

This plugin integrates Spotify streaming with Phoniebox using spotipy (Spotify Web API)
and librespot (audio streaming daemon). It coexists with the MPD player and allows
RFID cards to trigger Spotify playlists, albums, tracks, and artists.

Architecture:
- spotipy: Python library for Spotify Web API (playback control)
- librespot: Lightweight Spotify Connect daemon (audio streaming)
- OAuth 2.0 PKCE flow for secure authentication
- Thread-safe API access with automatic token refresh
- Caching for resolved content (1-hour TTL)
- Second swipe detection for card-based controls

Requirements:
- Spotify Premium account (required for playback API)
- spotipy >= 2.23.0
- pycryptodome >= 3.20.0
- librespot daemon running as systemd service

References:
- https://spotipy.readthedocs.io/
- https://github.com/librespot-org/librespot
- https://developer.spotify.com/documentation/web-api/
"""

import logging
import threading
import time
from typing import Optional, Dict, Any, List
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.exceptions import SpotifyException

import jukebox.cfghandler
import jukebox.plugs as plugs
import jukebox.publishing as publishing
from jukebox.NvManager import nv_manager
from .spotify_auth import SpotifyAuthManager
from .content_resolver import SpotifyContentResolver

logger = logging.getLogger('jb.PlayerSpotify')
cfg = jukebox.cfghandler.get_handler('jukebox')


class PlayerSpotify:
    """Spotify Player Plugin - mirrors playermpd interface"""

    def __init__(self):
        """Initialize Spotify player plugin"""
        self.nvm = nv_manager()

        # Load configuration
        self.client_id = cfg.getn('playerspotify', 'client_id', default='')
        self.client_secret = cfg.getn('playerspotify', 'client_secret', default='')
        self.redirect_uri = cfg.getn('playerspotify', 'redirect_uri',
                                     default='http://localhost:8888/callback')
        self.device_name = cfg.getn('playerspotify', 'device_name', default='Phoniebox')
        self.credential_file = cfg.getn('playerspotify', 'credential_file',
                                        default='../../shared/settings/spotify_credentials.json')
        self.status_file = cfg.getn('playerspotify', 'status_file',
                                    default='../../shared/settings/spotify_player_status.json')

        # Validate credentials
        if not self.client_id or not self.client_secret:
            logger.error("Spotify client_id and client_secret must be configured in jukebox.yaml")
            raise ValueError("Missing Spotify credentials in configuration")

        # Initialize authentication manager
        self.auth_manager = SpotifyAuthManager(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            credential_file=self.credential_file
        )

        # Initialize Spotify client with thread-safe lock
        self.lock = threading.RLock()
        self.sp_client = None
        self._initialize_client()

        # Initialize content resolver with caching
        cache_enabled = cfg.getn('playerspotify', 'cache_enabled', default=True)
        cache_path = cfg.getn('playerspotify', 'cache_path',
                             default='../../shared/cache/spotify/')
        artist_track_limit = cfg.getn('playerspotify', 'artist_track_limit', default=20)

        self.content_resolver = SpotifyContentResolver(
            sp_client=self.sp_client,
            cache_enabled=cache_enabled,
            cache_path=cache_path,
            artist_track_limit=artist_track_limit,
            lock=self.lock
        )

        # Load player status from disk
        self.player_status = self.nvm.load(self.status_file)
        if not self.player_status:
            self.player_status = {
                'state': 'stopped',  # stopped, playing, paused
                'last_played_uri': None,
                'current_track': None,
                'current_queue': [],
                'position_ms': 0,
                'device_id': None,
                'shuffle': False,
                'repeat': 'off'  # off, track, context
            }

        # Second swipe action configuration
        second_swipe_option = cfg.getn('playerspotify', 'second_swipe_action', 'alias',
                                       default='toggle')
        self.second_swipe_action_dict = {
            'toggle': self.toggle,
            'play': self.play,
            'skip': self.next,
            'rewind': self.rewind,
            'replay': self.replay,
            'none': lambda: None
        }
        self.second_swipe_action = self.second_swipe_action_dict.get(
            second_swipe_option,
            self.toggle
        )

        # Discover Spotify Connect device
        self._discover_device()

        # Start status publishing thread
        self.status_thread = threading.Thread(target=self._status_publisher_loop, daemon=True)
        self.status_thread_stop = threading.Event()
        self.status_thread.start()

        logger.info(f"Spotify player initialized (device: {self.device_name})")

    def _initialize_client(self):
        """Initialize Spotify client with authentication"""
        try:
            token = self.auth_manager.get_access_token()
            self.sp_client = spotipy.Spotify(auth=token)
            logger.info("Spotify client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {e}")
            raise

    def _discover_device(self):
        """Discover librespot device by name"""
        try:
            with self.lock:
                devices = self.sp_client.devices()
                if devices and 'devices' in devices:
                    for device in devices['devices']:
                        if device['name'] == self.device_name:
                            self.player_status['device_id'] = device['id']
                            logger.info(f"Found Spotify device: {self.device_name} ({device['id']})")
                            return
                    logger.warning(f"Spotify device '{self.device_name}' not found. "
                                 f"Make sure librespot is running.")
                else:
                    logger.warning("No Spotify devices available")
        except Exception as e:
            logger.error(f"Device discovery failed: {e}")

    def _ensure_device(self):
        """Ensure device is available, rediscover if needed"""
        if not self.player_status.get('device_id'):
            self._discover_device()
        return self.player_status.get('device_id') is not None

    def _refresh_token_if_needed(self):
        """Check and refresh token if expired"""
        try:
            if self.auth_manager.is_token_expired():
                logger.debug("Token expired, refreshing...")
                token = self.auth_manager.get_access_token()
                self.sp_client.set_auth(token)
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")

    def _save_status(self):
        """Save player status to disk"""
        self.nvm.save(self.player_status, self.status_file)

    def _status_publisher_loop(self):
        """Background thread to publish player status every 1 second"""
        while not self.status_thread_stop.is_set():
            try:
                status = self.playerstatus()
                publishing.get_publisher().send('playerstatus', status)
            except Exception as e:
                logger.debug(f"Status publishing error: {e}")
            time.sleep(1)

    @plugs.tag
    def get_player_type_and_version(self):
        """Return player type and version"""
        return {'player': 'Spotify', 'version': 'spotipy 2.23.0'}

    @plugs.tag
    def play(self):
        """Resume playback"""
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                logger.error("No Spotify device available")
                return

            with self.lock:
                device_id = self.player_status['device_id']
                # Resume current playback
                self.sp_client.start_playback(device_id=device_id)
                self.player_status['state'] = 'playing'
                self._save_status()
                logger.info("Playback resumed")
        except SpotifyException as e:
            logger.error(f"Play failed: {e}")

    @plugs.tag
    def stop(self):
        """Stop playback"""
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                self.sp_client.pause_playback(device_id=device_id)
                self.sp_client.seek_track(0, device_id=device_id)
                self.player_status['state'] = 'stopped'
                self.player_status['position_ms'] = 0
                self._save_status()
                logger.info("Playback stopped")
        except SpotifyException as e:
            logger.error(f"Stop failed: {e}")

    @plugs.tag
    def pause(self, state: int = 1):
        """
        Pause or resume playback

        Args:
            state: 1 to pause, 0 to resume
        """
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                if state == 1:
                    self.sp_client.pause_playback(device_id=device_id)
                    self.player_status['state'] = 'paused'
                    logger.info("Playback paused")
                else:
                    self.sp_client.start_playback(device_id=device_id)
                    self.player_status['state'] = 'playing'
                    logger.info("Playback resumed")
                self._save_status()
        except SpotifyException as e:
            logger.error(f"Pause failed: {e}")

    @plugs.tag
    def toggle(self):
        """Toggle pause/play state"""
        try:
            status = self.playerstatus()
            if status.get('state') == 'playing':
                self.pause(state=1)
            else:
                self.play()
        except Exception as e:
            logger.error(f"Toggle failed: {e}")

    @plugs.tag
    def next(self):
        """Skip to next track"""
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                self.sp_client.next_track(device_id=device_id)
                logger.info("Skipped to next track")
        except SpotifyException as e:
            logger.error(f"Next track failed: {e}")

    @plugs.tag
    def prev(self):
        """Skip to previous track"""
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                self.sp_client.previous_track(device_id=device_id)
                logger.info("Skipped to previous track")
        except SpotifyException as e:
            logger.error(f"Previous track failed: {e}")

    @plugs.tag
    def seek(self, new_time):
        """
        Seek to position in current track

        Args:
            new_time: Position in seconds
        """
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            position_ms = int(new_time * 1000)
            with self.lock:
                device_id = self.player_status['device_id']
                self.sp_client.seek_track(position_ms, device_id=device_id)
                self.player_status['position_ms'] = position_ms
                self._save_status()
                logger.info(f"Seeked to {new_time}s")
        except SpotifyException as e:
            logger.error(f"Seek failed: {e}")

    @plugs.tag
    def rewind(self):
        """Restart current track from beginning"""
        self.seek(0)

    @plugs.tag
    def replay(self):
        """Replay last played content"""
        try:
            last_uri = self.player_status.get('last_played_uri')
            if last_uri:
                logger.info(f"Replaying last content: {last_uri}")
                self.play_content(last_uri)
            else:
                logger.warning("No previous content to replay")
        except Exception as e:
            logger.error(f"Replay failed: {e}")

    @plugs.tag
    def replay_if_stopped(self):
        """Replay if player is stopped"""
        status = self.playerstatus()
        if status.get('state') == 'stopped':
            self.replay()

    @plugs.tag
    def shuffle(self, option='toggle'):
        """
        Control shuffle mode

        Args:
            option: 'toggle', 'on', 'off'
        """
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                current_shuffle = self.player_status.get('shuffle', False)

                if option == 'toggle':
                    new_shuffle = not current_shuffle
                elif option == 'on':
                    new_shuffle = True
                elif option == 'off':
                    new_shuffle = False
                else:
                    logger.error(f"Invalid shuffle option: {option}")
                    return

                self.sp_client.shuffle(new_shuffle, device_id=device_id)
                self.player_status['shuffle'] = new_shuffle
                self._save_status()
                logger.info(f"Shuffle: {new_shuffle}")
        except SpotifyException as e:
            logger.error(f"Shuffle failed: {e}")

    @plugs.tag
    def repeat(self, option='toggle'):
        """
        Control repeat mode

        Args:
            option: 'toggle', 'track', 'context', 'off'
        """
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                return

            with self.lock:
                device_id = self.player_status['device_id']
                current_repeat = self.player_status.get('repeat', 'off')

                if option == 'toggle':
                    # Cycle: off -> context -> track -> off
                    repeat_cycle = {'off': 'context', 'context': 'track', 'track': 'off'}
                    new_repeat = repeat_cycle.get(current_repeat, 'off')
                elif option in ['track', 'context', 'off']:
                    new_repeat = option
                else:
                    logger.error(f"Invalid repeat option: {option}")
                    return

                self.sp_client.repeat(new_repeat, device_id=device_id)
                self.player_status['repeat'] = new_repeat
                self._save_status()
                logger.info(f"Repeat: {new_repeat}")
        except SpotifyException as e:
            logger.error(f"Repeat failed: {e}")

    @plugs.tag
    def play_content(self, uri: str):
        """
        Play Spotify content by URI

        Args:
            uri: Spotify URI (spotify:track:*, spotify:playlist:*, spotify:album:*, spotify:artist:*)
        """
        try:
            self._refresh_token_if_needed()
            if not self._ensure_device():
                logger.error("No Spotify device available")
                return

            logger.info(f"Playing content: {uri}")

            # Resolve URI to track URIs
            track_uris = self.content_resolver.resolve_uri(uri)
            if not track_uris:
                logger.error(f"Failed to resolve URI: {uri}")
                return

            with self.lock:
                device_id = self.player_status['device_id']

                # Start playback
                if uri.startswith('spotify:track:'):
                    # Single track
                    self.sp_client.start_playback(device_id=device_id, uris=track_uris)
                else:
                    # Playlist, album, or artist
                    self.sp_client.start_playback(device_id=device_id, uris=track_uris)

                self.player_status['state'] = 'playing'
                self.player_status['last_played_uri'] = uri
                self.player_status['current_queue'] = track_uris
                self._save_status()

                logger.info(f"Started playback of {len(track_uris)} tracks")
        except SpotifyException as e:
            logger.error(f"Play content failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in play_content: {e}")

    @plugs.tag
    def play_card(self, uri: str):
        """
        Play content triggered by RFID card with second swipe detection

        Args:
            uri: Spotify URI
        """
        try:
            last_uri = self.player_status.get('last_played_uri')

            # Second swipe detection
            if last_uri == uri:
                logger.info(f"Second swipe detected for: {uri}")
                self.second_swipe_action()
            else:
                logger.info(f"First swipe: {uri}")
                self.play_content(uri)
        except Exception as e:
            logger.error(f"Play card failed: {e}")

    @plugs.tag
    def playerstatus(self) -> Dict[str, Any]:
        """
        Get current player status

        Returns:
            Dictionary with current playback state
        """
        try:
            self._refresh_token_if_needed()

            with self.lock:
                # Get current playback from Spotify API
                current = self.sp_client.current_playback()

                if current and current.get('item'):
                    track = current['item']
                    self.player_status['state'] = 'playing' if current['is_playing'] else 'paused'
                    self.player_status['position_ms'] = current.get('progress_ms', 0)
                    self.player_status['shuffle'] = current.get('shuffle_state', False)
                    self.player_status['repeat'] = current.get('repeat_state', 'off')
                    self.player_status['current_track'] = {
                        'name': track['name'],
                        'artist': ', '.join([a['name'] for a in track['artists']]),
                        'album': track['album']['name'],
                        'duration_ms': track['duration_ms'],
                        'uri': track['uri'],
                        'artwork_url': track['album']['images'][0]['url'] if track['album']['images'] else None
                    }
                else:
                    # No active playback
                    if self.player_status.get('state') != 'stopped':
                        self.player_status['state'] = 'stopped'

                return self.player_status.copy()
        except Exception as e:
            logger.debug(f"Playerstatus error: {e}")
            return self.player_status.copy()

    @plugs.tag
    def playlistinfo(self) -> List[Dict[str, Any]]:
        """
        Get current queue information

        Returns:
            List of tracks in current queue
        """
        try:
            self._refresh_token_if_needed()

            with self.lock:
                queue = self.sp_client.queue()
                if queue and 'queue' in queue:
                    playlist = []
                    for track in queue['queue']:
                        playlist.append({
                            'name': track['name'],
                            'artist': ', '.join([a['name'] for a in track['artists']]),
                            'album': track['album']['name'],
                            'duration_ms': track['duration_ms'],
                            'uri': track['uri']
                        })
                    return playlist
                else:
                    return []
        except Exception as e:
            logger.debug(f"Playlistinfo error: {e}")
            return []

    @plugs.tag
    def get_current_song(self, param) -> Dict[str, Any]:
        """
        Get current song metadata

        Args:
            param: Parameter (currently unused, for interface compatibility)

        Returns:
            Current track information
        """
        status = self.playerstatus()
        return status.get('current_track', {})

    def exit(self):
        """Cleanup on plugin shutdown"""
        logger.info("Shutting down Spotify player")
        self.status_thread_stop.set()
        if self.status_thread.is_alive():
            self.status_thread.join(timeout=2)
        self._save_status()


# Global player instance
player_ctrl = None


@plugs.initialize
def initialize():
    """Initialize Spotify player plugin"""
    global player_ctrl
    player_ctrl = PlayerSpotify()
    plugs.register(player_ctrl, name='ctrl')
    logger.info("Spotify player plugin registered as 'playerspotify.ctrl'")


@plugs.atexit
def atexit(**ignored_kwargs):
    """Cleanup on exit"""
    global player_ctrl
    if player_ctrl:
        return player_ctrl.exit()
