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

import enum
import json
import logging
import os
import subprocess
import threading
import time
from typing import Dict, Any, List, Tuple
import spotipy
from spotipy.exceptions import SpotifyException

import jukebox.cfghandler
import jukebox.plugs as plugs
import jukebox.publishing as publishing
from jukebox.utils.atomic_io import atomic_write_json_safe
from components.player.coordinator import get_coordinator
from .spotify_auth import SpotifyAuthManager
from .content_resolver import SpotifyContentResolver
from .swipe_decision import (
    SpotifySwipeContext,
    SpotifySwipeDecision,
    decide_spotify_swipe,
)


class BackoffPolicy(enum.Enum):
    """How :meth:`PlayerSpotify._apply_error_backoff` should treat an interval.

    Phase 6 / Phase 3c FU#1: previously the 429-vs-generic distinction
    was inferred from the *magnitude* of the requested base interval
    (``base > _ERROR_BACKOFF_BASE``). A 429 with ``Retry-After: 30`` —
    i.e. exactly the floor — fell into the generic-error multiplication
    branch and slept ``30 * N`` rather than the contract-stipulated 30.
    Strictly more conservative than the API contract, but wrong; under a
    sustained 429 storm we'd back off well past what the server asked
    for. This typed enum makes the distinction explicit instead of
    magnitude-encoded.

    - ``RETRY_AFTER`` — the interval is the value the server told us to
      wait. Pass it through untouched; never multiply by the consecutive
      error count.
    - ``EXPONENTIAL`` — generic error. Multiply by the consecutive
      error count and cap at ``_ERROR_BACKOFF_MAX``.
    """
    RETRY_AFTER = 'retry_after'
    EXPONENTIAL = 'exponential'


logger = logging.getLogger('jb.PlayerSpotify')
cfg = jukebox.cfghandler.get_handler('jukebox')


# Phase 6: per-plugin config schema (see jukebox.plug_schema).
# Spotify is graceful about missing credentials (loads in unconfigured
# state and waits for the Web UI to set them), so nothing here is
# ``required``. The schema's job is to catch type mistakes — e.g.
# ``client_id: true`` from a copy-paste mishap — before the auth
# manager surfaces a less-helpful error.
plugs_config_section = ['playerspotify']
plugs_config_schema = {
    'client_id': str,
    'client_secret': str,
    'redirect_uri': str,
    'device_name': str,
    'credential_file': str,
    'status_file': str,
    'cache_enabled': bool,
    'cache_path': str,
    'second_swipe_action': {
        'type': dict,
        'schema': {
            'alias': {
                'type': str,
                'choices': ['toggle', 'play', 'skip', 'rewind',
                            'replay', 'none'],
            },
        },
    },
}


class PlayerSpotify:
    """Spotify Player Plugin - mirrors playermpd interface"""

    def __init__(self):
        """Initialize Spotify player plugin

        Loads gracefully even without credentials so the web UI
        can call get_auth_status / get_auth_url before the user
        has configured anything.
        """
        # Load configuration
        self.client_id = cfg.getn('playerspotify', 'client_id', default='')
        self.client_secret = cfg.getn('playerspotify', 'client_secret', default='')
        self.redirect_uri = cfg.getn('playerspotify', 'redirect_uri',
                                     default='http://127.0.0.1:8888/callback')
        self.device_name = cfg.getn('playerspotify', 'device_name', default='Phoniebox')
        self.credential_file = cfg.getn('playerspotify', 'credential_file',
                                        default='../../shared/settings/spotify_credentials.json')
        self.status_file = cfg.getn('playerspotify', 'status_file',
                                    default='../../shared/settings/spotify_player_status.json')

        # Thread-safe lock for API access
        self.lock = threading.RLock()
        self.sp_client = None
        self.auth_manager = None

        # Graceful init: load even when credentials are missing
        self._configured = bool(self.client_id and self.client_secret)
        if not self._configured:
            logger.warning("Spotify client_id / client_secret not configured. "
                           "Plugin loaded in unconfigured state — "
                           "use the web UI Settings page to connect.")
        else:
            # Initialize authentication manager
            self.auth_manager = SpotifyAuthManager(
                client_id=self.client_id,
                client_secret=self.client_secret,
                redirect_uri=self.redirect_uri,
                credential_file=self.credential_file
            )
            # Try to initialise the API client (may fail if not yet authed)
            try:
                self._initialize_client()
            except Exception:
                logger.warning("Spotify client not authenticated yet — "
                               "use the web UI Settings page to connect.")

        # Initialize content resolver with caching
        cache_enabled = cfg.getn('playerspotify', 'cache_enabled', default=True)
        cache_path = cfg.getn('playerspotify', 'cache_path',
                              default='../../shared/cache/spotify/')

        self.content_resolver = SpotifyContentResolver(
            sp_client=self.sp_client,
            cache_enabled=cache_enabled,
            cache_path=cache_path,
            lock=self.lock
        )

        # Load player status from disk
        self.player_status = self._load_state()
        if not self.player_status:
            self.player_status = {
                'state': 'stopped',  # stopped, playing, paused
                'last_played_uri': None,
                # Phase 3c: track card-driven activations separately from
                # in-app starts so play_card can distinguish a fresh swipe
                # of a URI that was started via the web UI from a real
                # second swipe. ``last_card_uri`` is None on cold start
                # and only ever set by play_card.
                'last_card_uri': None,
                'current_track': None,
                'current_queue': [],
                'position_ms': 0,
                'device_id': None,
                'shuffle': False,
                'repeat': 'off'  # off, track, context
            }
        # Ensure the field exists for state files saved before Phase 3c
        # (older installs persisted player_status without last_card_uri).
        self.player_status.setdefault('last_card_uri', None)

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

        # Device discovery happens lazily in the status thread — never
        # block the MainThread with Spotify API calls during init.
        self.status_thread = threading.Thread(target=self._status_publisher_loop, daemon=True)
        self.status_thread_stop = threading.Event()
        self.status_thread.start()

        logger.info(f"Spotify player initialized (device: {self.device_name}, "
                     f"configured: {self._configured}, "
                     f"authenticated: {self.sp_client is not None})")

    def _initialize_client(self):
        """Initialize Spotify client with authentication"""
        try:
            token = self.auth_manager.get_access_token()
            self.sp_client = spotipy.Spotify(
                auth=token,
                requests_timeout=10,
                retries=0,
            )
            logger.info("Spotify client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Spotify client: {e}")
            raise

    def _require_client(self):
        """Raise if the Spotify client is not available"""
        if not self.sp_client:
            raise SpotifyException(
                http_status=401, code=-1,
                msg="Spotify not authenticated. Connect via Settings."
            )

    def _activate(self):
        """Claim the active-player slot via the coordinator.

        The coordinator runs the outgoing backend's pause-then-stop
        (so MPD's playback is stopped, or podcast's resume position is
        preserved), bounded by a 5s timeout. Idempotent when Spotify
        is already current.
        """
        with get_coordinator().activate('spotify'):
            pass

    def _discover_device(self):
        """Discover librespot device by name.

        Safe to call from any thread.  Never blocks longer than the
        spotipy ``requests_timeout`` (10 s).
        """
        if not self.sp_client:
            return
        try:
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
        """Ensure device is available, rediscover if needed.

        Single-attempt discovery. For first-activation paths (cold
        ``play_card``), use :meth:`_ensure_device_for_activation` so the
        caller gets a bounded retry and a clear error on timeout.
        """
        if not self.player_status.get('device_id'):
            self._discover_device()
        return self.player_status.get('device_id') is not None

    def _ensure_device_for_activation(self, timeout: float = 5.0):
        """Block up to ``timeout`` seconds for a librespot device to appear.

        Called from ``play_card`` (and other first-activation entry points)
        so the user-visible action either lands on a real device within
        5 s or raises a recognisable error. The status thread's lazy
        discovery path stays in place for steady-state polling, but it's
        no longer the *only* route to populate ``device_id`` — a cold
        ``play_card`` after a librespot restart used to silently no-op
        because ``_ensure_device`` returned False and ``play_content`` bailed.

        Returns ``True`` if a device id is present (already or newly found),
        ``False`` if the timeout expired with no device.
        """
        if self.player_status.get('device_id'):
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        # Probe at modest intervals so a restarted librespot has a chance to
        # register. spotipy.devices() has its own 10s request timeout but
        # usually returns within ~200ms.
        attempt_interval = 0.5
        while True:
            self._discover_device()
            if self.player_status.get('device_id'):
                return True
            if time.monotonic() >= deadline:
                logger.error(
                    f"Spotify device '{self.device_name}' did not appear within "
                    f"{timeout:.1f}s. Is librespot running?"
                )
                return False
            time.sleep(attempt_interval)

    def _restart_librespot_with_token(self):
        """Restart librespot with the current access token.

        This registers the device with the Spotify account so the
        Web API can see it.  librespot caches its own credentials
        after the first connection, so subsequent restarts don't
        need the token.
        """
        if not self.auth_manager:
            return
        try:
            token = self.auth_manager.get_access_token()
            env_dir = os.path.expanduser('~/.cache/librespot')
            os.makedirs(env_dir, exist_ok=True)
            env_file = os.path.join(env_dir, 'env')
            with open(env_file, 'w') as f:
                f.write(f'SPOTIFY_ACCESS_TOKEN={token}\n')
            os.chmod(env_file, 0o600)

            subprocess.run(
                ['systemctl', '--user', 'stop', 'librespot'],
                timeout=10, check=False)
            subprocess.run(
                ['systemctl', '--user', 'start', 'librespot'],
                timeout=10, check=False)

            # Give librespot a moment to connect
            time.sleep(3)
            logger.info("Restarted librespot with access token")
        except Exception as e:
            logger.error(f"Failed to restart librespot: {e}")

    def _refresh_token_if_needed(self):
        """Check and refresh token if expired"""
        if not self.auth_manager or not self.sp_client:
            return
        try:
            if self.auth_manager.is_token_expired():
                logger.debug("Token expired, refreshing...")
                token = self.auth_manager.get_access_token()
                self.sp_client.set_auth(token)
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")

    def _load_state(self):
        """Load player status from JSON file"""
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load player status: {e}")
                return {}
        return {}

    def _save_status(self):
        """Save player status to JSON file atomically (write-tmp + fsync + rename)."""
        atomic_write_json_safe(self.status_file, self.player_status)

    def _to_mpd_status(self):
        """Convert Spotify status to MPD-compatible format for the web UI.

        The web UI Player components expect MPD-style fields (state='play',
        top-level title/artist/album, elapsed/duration in seconds, etc.).
        """
        status = self.player_status
        track = status.get('current_track') or {}
        state_map = {'playing': 'play', 'paused': 'pause', 'stopped': 'stop'}
        repeat_val = status.get('repeat', 'off')

        mpd_status = {
            'state': state_map.get(status.get('state', 'stopped'), 'stop'),
            'title': track.get('name', ''),
            'artist': track.get('artist', ''),
            'album': track.get('album', ''),
            'file': track.get('uri', ''),
            'coverart_url': track.get('artwork_url'),
            'elapsed': str(status.get('position_ms', 0) / 1000),
            'duration': str(track.get('duration_ms', 0) / 1000),
            'random': '1' if status.get('shuffle') else '0',
            'repeat': '1' if repeat_val in ('track', 'context') else '0',
            'single': '1' if repeat_val == 'track' else '0',
            # songid must be truthy when a track is active
            'songid': track.get('uri', ''),
            'player_type': 'spotify',
        }
        return mpd_status

    @staticmethod
    def _get_retry_after(exc):
        """Extract Retry-After seconds from a SpotifyException, default 30."""
        if exc.headers:
            try:
                return max(int(exc.headers.get('Retry-After', 30)), 30)
            except (ValueError, TypeError):
                pass
        return 30

    #: Adaptive-polling intervals (seconds). Documented here so the
    #: status-publisher tests can pin them as the public contract of
    #: the loop's pacing — changing these is a behaviour change.
    _POLL_INTERVAL_PLAYING = 1.0
    _POLL_INTERVAL_IDLE = 5.0
    _POLL_INTERVAL_NO_CLIENT = 10.0
    _ERROR_BACKOFF_BASE = 30.0
    _ERROR_BACKOFF_MAX = 300.0
    _RATE_LIMIT_MIN_BACKOFF = 30.0

    def _status_publisher_loop(self):
        """Background thread to publish player status.

        Phase 3c: split into four sub-methods (``_fetch_status``,
        ``_transform_status``, ``_publish_status``,
        ``_handle_status_error_with_backoff``) so each is unit-testable
        in isolation. The loop is now just the dispatch/scheduling skeleton.

        Adaptive polling (intervals constants above):
        - playing:                  ~1 s
        - paused / stopped:         ~5 s
        - no spotipy client yet:    ~10 s (slow heartbeat for publish gating)
        - on API error:             back off 30 → 300 s, double on each
        - on HTTP 429:              honour ``Retry-After`` (min 30 s)

        Note (Phase 1 FU#3): the prior implementation kicked off a
        one-shot ``_discover_device`` here as a "lazy first probe".
        Phase 1's ``_ensure_device_for_activation`` already does a
        bounded device search at activation time, which is the only
        path that actually needs a device id (``play_content`` /
        ``play_card``). The status loop merely *reads* a cached id
        for publishing — it doesn't need one to fetch current
        playback. Removing the lazy probe drops a duplicative API
        call per process lifetime without changing observable
        behaviour.
        """
        consecutive_errors = 0
        # Phase 6 / Phase 3c FU#1: success cycles use EXPONENTIAL as
        # the carrier policy (effectively unused — interval is the
        # raw poll cadence). On error cycles, _poll_status_once
        # returns the policy from _handle_status_error_with_backoff.
        policy = BackoffPolicy.EXPONENTIAL

        while not self.status_thread_stop.is_set():
            interval, success, policy = self._poll_status_once()
            if success:
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                interval = self._apply_error_backoff(
                    interval, consecutive_errors, policy)
            self.status_thread_stop.wait(timeout=interval)

    def _is_active(self):
        """Return True if Spotify is the active player."""
        return get_coordinator().current() == 'spotify'

    # ------------------------------------------------------------------
    # status_publisher_loop sub-methods (Phase 3c)
    # ------------------------------------------------------------------

    def _fetch_status(self):
        """Pull current playback from Spotify into ``self.player_status``.

        Raises :class:`SpotifyException` (and other exceptions) so the
        caller can apply error-handling / backoff. Returns nothing.
        """
        self._fetch_and_update_status()

    def _transform_status(self):
        """Convert the cached ``player_status`` into MPD-format dict.

        Pure function on ``self.player_status`` — no I/O. Separated so
        tests can call it without spinning up the network mocks.
        """
        return self._to_mpd_status()

    def _publish_status(self, mpd_status):
        """Send a publish message *iff* Spotify is the active player.

        Gating here avoids cross-talk with playermpd: when MPD owns
        the slot, its publisher's playerstatus is canonical. Spotify
        keeps its cached state up to date (so a future re-activation
        knows what to resume) but doesn't pollute the UI's status
        stream.
        """
        if self._is_active():
            publishing.get_publisher().send('playerstatus', mpd_status)

    def _publish_cleanup_status(self):
        """Push a final cleared-state snapshot during coordinator handoff.

        Phase 5a (project_phase_3c_followups.md #2). Invoked by the
        :class:`PlayerCoordinator` AFTER pause + stop and BEFORE the
        active-backend slot is swapped to the incoming backend. The
        snapshot is constructed from the current cached
        ``player_status`` but with every field that would let the UI
        keep showing this backend's track cleared (state='stop',
        title/artist/album/file='', elapsed='0', etc.) so the UI is
        guaranteed a clean baseline if the incoming backend is slow
        to produce its own first publish (the canonical case is a
        Spotify 429 storm where the status loop's adaptive backoff
        could otherwise leave the UI stuck on a stale track).

        Skips publishing entirely if the publisher is unavailable
        (during shutdown). Bypasses ``_is_active()`` because the
        coordinator's ordering guarantee (cleanup before slot swap)
        means we ARE still active at this moment; the gate would
        approve anyway, but a direct send removes the implicit
        timing dependency.
        """
        cleanup_status = {
            'state': 'stop',
            'title': '',
            'artist': '',
            'album': '',
            'file': '',
            'coverart_url': None,
            'elapsed': '0',
            'duration': '0',
            'random': '0',
            'repeat': '0',
            'single': '0',
            'songid': '',
            'player_type': 'spotify',
        }
        try:
            publisher = publishing.get_publisher()
        except Exception:
            return  # No publisher available (e.g. during early shutdown).
        if publisher is None:
            return
        publisher.send('playerstatus', cleanup_status)

    def _handle_status_error_with_backoff(self, exc) -> Tuple[float, BackoffPolicy]:
        """Choose the next-poll interval after an exception.

        Phase 6 / Phase 3c FU#1: returns a ``(interval, policy)``
        tuple instead of a bare interval. The policy is the typed
        :class:`BackoffPolicy` value the loop uses to decide whether to
        apply the consecutive-error multiplier. Magnitude-encoded
        distinction (``base > _ERROR_BACKOFF_BASE``) was fragile — a
        429 with ``Retry-After: 30`` (exactly the floor) was
        indistinguishable from a generic error wanting the base
        interval and got multiplied.

        For HTTP 429 we honour ``Retry-After`` and return
        :class:`BackoffPolicy.RETRY_AFTER` so the loop passes the
        interval through untouched. For all other errors we return
        :attr:`_ERROR_BACKOFF_BASE` with
        :class:`BackoffPolicy.EXPONENTIAL` so the loop multiplies by
        the consecutive-error count.
        """
        if isinstance(exc, SpotifyException) and exc.http_status == 429:
            interval = self._get_retry_after(exc)
            logger.warning(f"Spotify rate-limited, backing off {interval}s")
            return interval, BackoffPolicy.RETRY_AFTER
        logger.debug(f"Status poll error: {exc}")
        return self._ERROR_BACKOFF_BASE, BackoffPolicy.EXPONENTIAL

    def _apply_error_backoff(self, base_interval, consecutive_errors,
                             policy: BackoffPolicy = BackoffPolicy.EXPONENTIAL):
        """Apply the consecutive-error backoff curve.

        Phase 6 / Phase 3c FU#1: ``policy`` is now an explicit typed
        :class:`BackoffPolicy`. The previous magnitude-based heuristic
        ``base_interval > _ERROR_BACKOFF_BASE`` mis-routed a 429 with
        ``Retry-After: 30`` (exactly the floor) into the multiplication
        branch — a 5th consecutive 429-at-floor would sleep 150 s, not
        the server-requested 30 s.

        - :attr:`BackoffPolicy.RETRY_AFTER` — pass ``base_interval``
          through unchanged.
        - :attr:`BackoffPolicy.EXPONENTIAL` — multiply by
          ``consecutive_errors`` and cap at ``_ERROR_BACKOFF_MAX``.
        """
        if policy is BackoffPolicy.RETRY_AFTER:
            return base_interval
        return min(self._ERROR_BACKOFF_BASE * consecutive_errors,
                   self._ERROR_BACKOFF_MAX)

    def _poll_status_once(self):
        """Run one status-poll cycle.

        Returns ``(interval, success, policy)``:
        - ``interval`` is the next-sleep duration in seconds.
        - ``success`` is True if the API call succeeded (or no
          client is configured — that's a "no work" success).
        - ``policy`` is the :class:`BackoffPolicy` the loop applies
          on error cycles. Success cycles return EXPONENTIAL as a
          carrier value (the loop ignores ``policy`` when success).

        Phase 6 / Phase 3c FU#1: the third tuple element makes the
        429-vs-generic distinction explicit so the loop can pin a
        429 with ``Retry-After: 30`` (exactly the error-base floor)
        from being multiplied by the consecutive-error count.
        """
        if not self.sp_client:
            # No authenticated client → publish whatever cached
            # status we have so the UI knows we're idle.
            self._publish_status(self._transform_status())
            return self._POLL_INTERVAL_NO_CLIENT, True, BackoffPolicy.EXPONENTIAL

        try:
            self._fetch_status()
        except Exception as exc:
            # Still publish cached status so the UI doesn't go
            # stale during the error window.
            self._publish_status(self._transform_status())
            interval, policy = self._handle_status_error_with_backoff(exc)
            return interval, False, policy

        self._publish_status(self._transform_status())
        active = self.player_status.get('state') == 'playing'
        interval = (self._POLL_INTERVAL_PLAYING if active
                    else self._POLL_INTERVAL_IDLE)
        return interval, True, BackoffPolicy.EXPONENTIAL

    @plugs.tag
    def get_player_type_and_version(self):
        """Return player type and version"""
        return {'player': 'Spotify', 'version': 'spotipy 2.23.0'}

    # ------------------------------------------------------------------
    # Auth methods (safe to call even when not yet configured)
    # ------------------------------------------------------------------

    @plugs.tag
    def get_spotify_config(self) -> Dict[str, Any]:
        """Return current Spotify client configuration

        The client_secret is masked for display (only last 4 chars shown).

        Returns:
            Dictionary with ``client_id``, ``client_secret_masked``,
            ``redirect_uri``, and ``configured`` fields.
        """
        masked = ''
        if self.client_secret and len(self.client_secret) > 4:
            masked = '*' * 8 + self.client_secret[-4:]
        elif self.client_secret:
            masked = '*' * len(self.client_secret)
        return {
            'client_id': self.client_id,
            'client_secret_masked': masked,
            'redirect_uri': self.redirect_uri,
            'configured': self._configured,
        }

    @plugs.tag
    def set_spotify_config(self, client_id: str, client_secret: str) -> Dict[str, Any]:
        """Save Spotify client credentials and reinitialize the auth manager

        Persists client_id and client_secret to jukebox.yaml and
        reinitializes the authentication manager so the user can
        proceed to the OAuth connect flow without restarting the daemon.

        Args:
            client_id: Spotify application client ID
            client_secret: Spotify application client secret

        Returns:
            Dictionary with ``success`` and ``configured`` fields.
        """
        try:
            client_id = (client_id or '').strip()
            client_secret = (client_secret or '').strip()

            # Persist to jukebox.yaml
            cfg.setn('playerspotify', 'client_id', value=client_id)
            cfg.setn('playerspotify', 'client_secret', value=client_secret)
            cfg.save(only_if_changed=True)

            # Update instance state
            self.client_id = client_id
            self.client_secret = client_secret
            self._configured = bool(client_id and client_secret)

            # Reinitialize auth manager if we now have credentials
            if self._configured:
                self.auth_manager = SpotifyAuthManager(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    redirect_uri=self.redirect_uri,
                    credential_file=self.credential_file
                )
                # Clear existing client — user must go through OAuth flow
                self.sp_client = None
                self.content_resolver.sp_client = None
                logger.info("Spotify credentials saved, auth manager reinitialized")
            else:
                self.auth_manager = None
                self.sp_client = None
                self.content_resolver.sp_client = None
                logger.info("Spotify credentials cleared")

            return {'success': True, 'configured': self._configured}
        except Exception as e:
            logger.error(f"Failed to save Spotify config: {e}")
            return {'success': False, 'error': str(e)}

    @plugs.tag
    def get_auth_status(self) -> Dict[str, Any]:
        """Return current authentication status

        Returns:
            Dictionary with ``authenticated``, ``has_token``, ``configured``,
            and ``redirect_uri`` fields.
        """
        has_token = (self.auth_manager is not None
                     and self.auth_manager.token_info is not None)
        return {
            'configured': self._configured,
            'authenticated': self.sp_client is not None,
            'has_token': has_token,
            'redirect_uri': self.redirect_uri,
        }

    @plugs.tag
    def get_auth_url(self) -> Dict[str, Any]:
        """Return the Spotify OAuth authorization URL

        Returns:
            Dictionary with ``auth_url`` field.
        """
        if not self._configured or self.auth_manager is None:
            return {'error': 'Spotify client_id / client_secret not configured'}
        return {'auth_url': self.auth_manager.get_auth_url()}

    @plugs.tag
    def authenticate(self, auth_code: str) -> Dict[str, Any]:
        """Complete OAuth flow with the authorization code from the redirect

        Args:
            auth_code: The ``code`` query parameter from the OAuth redirect.

        Returns:
            Dictionary with ``success`` field.
        """
        if not self._configured or self.auth_manager is None:
            return {'success': False, 'error': 'Not configured'}
        try:
            self.auth_manager.authenticate(auth_code)
            token = self.auth_manager.get_access_token()
            self.sp_client = spotipy.Spotify(
                auth=token,
                requests_timeout=10,
                retries=0,
            )
            self.content_resolver.sp_client = self.sp_client
            # Register librespot with the account so it appears as a device
            self._restart_librespot_with_token()
            self._discover_device()
            logger.info("Spotify authenticated via web UI")
            return {'success': True}
        except Exception as e:
            logger.error(f"Web UI authentication failed: {e}")
            return {'success': False, 'error': str(e)}

    @plugs.tag
    def logout(self) -> Dict[str, Any]:
        """Clear stored token and disconnect the Spotify client

        Returns:
            Dictionary with ``success`` field.
        """
        try:
            if self.auth_manager:
                self.auth_manager.clear_token()
            self.sp_client = None
            self.content_resolver.sp_client = None
            logger.info("Spotify logged out via web UI")
            return {'success': True}
        except Exception as e:
            logger.error(f"Logout failed: {e}")
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Search & library methods
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_search_item(item: Dict, type_key: str) -> Dict[str, Any]:
        """Extract consistent metadata from different Spotify result shapes"""
        result = {
            'name': item.get('name', ''),
            'uri': item.get('uri', ''),
            'type': type_key,
        }
        # Image
        images = item.get('images') or item.get('album', {}).get('images') or []
        result['image_url'] = images[0]['url'] if images else None
        # Artist(s)
        artists = item.get('artists', [])
        result['artist'] = ', '.join(a['name'] for a in artists) if artists else ''
        # Owner (playlists)
        owner = item.get('owner')
        if owner and not result['artist']:
            result['artist'] = owner.get('display_name', '')
        # Description (playlists / shows)
        result['description'] = item.get('description', '')
        # Track/episode count
        total = (item.get('tracks', {}) or {}).get('total')
        if total is None:
            total = (item.get('total_tracks')
                     or (item.get('episodes', {}) or {}).get('total'))
        result['total_tracks'] = total
        return result

    @plugs.tag
    def search(self, query: str, content_type: str = 'playlist,album,track',
               limit: int = 10) -> Dict[str, Any]:
        """Search the Spotify catalogue

        Args:
            query: Search query string
            content_type: Comma-separated list of types (track, album, playlist, show)
            limit: Maximum results per type (max 10 for dev-mode apps)

        Returns:
            Dictionary with ``items`` list of normalised results.
        """
        self._require_client()
        self._refresh_token_if_needed()
        limit = min(limit, 10)
        try:
            raw = self.sp_client.search(q=query, type=content_type, limit=limit)
            if not raw:
                return {'items': [], 'error': 'Empty response from Spotify'}

            items: List[Dict] = []
            for type_key in content_type.split(','):
                type_key = type_key.strip()
                plural = type_key + 's'
                for item in ((raw.get(plural) or {}).get('items') or []):
                    if item is None:
                        continue
                    items.append(self._normalize_search_item(item, type_key))
            return {'items': items}
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return {'items': [], 'error': str(e)}

    @plugs.tag
    def get_user_playlists(self, limit: int = 50,
                           offset: int = 0) -> Dict[str, Any]:
        """Get the authenticated user's playlists

        Args:
            limit: Maximum number of playlists
            offset: Pagination offset

        Returns:
            Dictionary with ``items`` and ``total``.
        """
        self._require_client()
        self._refresh_token_if_needed()
        try:
            raw = self.sp_client.current_user_playlists(limit=limit, offset=offset)
            items = [self._normalize_search_item(p, 'playlist')
                     for p in raw.get('items', [])]
            return {'items': items, 'total': raw.get('total', 0)}
        except SpotifyException as e:
            logger.error(f"get_user_playlists failed: {e}")
            return {'items': [], 'total': 0, 'error': str(e)}

    @plugs.tag
    def get_user_albums(self, limit: int = 50,
                        offset: int = 0) -> Dict[str, Any]:
        """Get the authenticated user's saved albums

        Args:
            limit: Maximum number of albums
            offset: Pagination offset

        Returns:
            Dictionary with ``items`` and ``total``.
        """
        self._require_client()
        self._refresh_token_if_needed()
        try:
            raw = self.sp_client.current_user_saved_albums(limit=limit, offset=offset)
            items = [self._normalize_search_item(a['album'], 'album')
                     for a in raw.get('items', [])]
            return {'items': items, 'total': raw.get('total', 0)}
        except SpotifyException as e:
            logger.error(f"get_user_albums failed: {e}")
            return {'items': [], 'total': 0, 'error': str(e)}

    @plugs.tag
    def get_content_details(self, uri: str) -> Dict[str, Any]:
        """Get full metadata for a Spotify URI

        Used by the card-registration component to display content info.

        Args:
            uri: Spotify URI (playlist, album, track, show, episode)

        Returns:
            Dictionary with ``name``, ``image_url``, ``type``, etc.
        """
        self._require_client()
        self._refresh_token_if_needed()
        try:
            uri = self.content_resolver._normalize_uri(uri)
            content_type, content_id = self.content_resolver._parse_uri(uri)

            if content_type == 'playlist':
                data = self.sp_client.playlist(content_id)
            elif content_type == 'album':
                data = self.sp_client.album(content_id)
            elif content_type == 'track':
                data = self.sp_client.track(content_id)
            elif content_type == 'show':
                data = self.sp_client.show(content_id)
            elif content_type == 'episode':
                data = self.sp_client.episode(content_id)
            else:
                return {'error': f'Unsupported type: {content_type}'}

            result = self._normalize_search_item(data, content_type)
            return result
        except SpotifyException as e:
            logger.error(f"get_content_details failed: {e}")
            return {'error': str(e)}
        except ValueError as e:
            return {'error': str(e)}

    # ------------------------------------------------------------------
    # Playback methods
    # ------------------------------------------------------------------

    @plugs.tag
    def play(self):
        """Resume playback"""
        try:
            self._require_client()
            self._refresh_token_if_needed()
            if not self._ensure_device():
                logger.error("No Spotify device available")
                return

            self._activate()
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
            self._require_client()
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
            self._require_client()
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
            self._require_client()
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
            self._require_client()
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
            self._require_client()
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
            uri: Spotify URI (spotify:track:*, spotify:playlist:*, spotify:album:*,
                 spotify:show:*, spotify:episode:*)
        """
        try:
            self._require_client()
            self._refresh_token_if_needed()
            # Activation paths must block briefly (up to 5 s) for librespot to
            # register the device — otherwise a cold ``play_card`` after a
            # restart silently no-ops because the status-thread lazy probe
            # hasn't run yet.
            if not self._ensure_device_for_activation(timeout=5.0):
                raise SpotifyException(
                    http_status=503, code=-1,
                    msg=f"Spotify device '{self.device_name}' not available "
                        "(timed out waiting for librespot)"
                )

            logger.info(f"Playing content: {uri}")

            self._activate()
            normalized = self.content_resolver._normalize_uri(uri)
            content_type, _ = self.content_resolver._parse_uri(normalized)

            with self.lock:
                device_id = self.player_status['device_id']

                if content_type in ('show', 'episode'):
                    # Shows/episodes: use context_uri so Spotify handles
                    # episode ordering and resume natively
                    self.sp_client.start_playback(
                        device_id=device_id, context_uri=normalized)
                elif content_type == 'track':
                    self.sp_client.start_playback(
                        device_id=device_id, uris=[normalized])
                else:
                    # playlist, album — resolve to track URIs
                    track_uris = self.content_resolver.resolve_uri(uri)
                    if not track_uris:
                        logger.error(f"Failed to resolve URI: {uri}")
                        return
                    self.sp_client.start_playback(
                        device_id=device_id, uris=track_uris)

                self.player_status['state'] = 'playing'
                self.player_status['last_played_uri'] = uri
                self._save_status()

                logger.info(f"Started playback of {uri}")
        except SpotifyException as e:
            logger.error(f"Play content failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error in play_content: {e}")

    @plugs.tag
    def play_card(self, uri: str):
        """
        Play content triggered by RFID card with second swipe detection

        Uses :func:`decide_spotify_swipe` (Phase 3c) so the rule is
        observable in isolation. A swipe is treated as a SECOND_TOGGLE
        only when (a) the URI matches the last played, (b) Spotify is
        the active backend, and (c) the *previous* activation of this
        URI also came from a card swipe. That third condition prevents
        the common bug where the user started a URI from the web UI
        and the first physical card swipe was misread as a second
        swipe (and paused playback).

        Args:
            uri: Spotify URI
        """
        try:
            ctx = SpotifySwipeContext(
                incoming_uri=uri,
                last_played_uri=self.player_status.get('last_played_uri'),
                last_card_uri=self.player_status.get('last_card_uri'),
                coordinator_current=get_coordinator().current(),
            )
            decision = decide_spotify_swipe(ctx)

            # Either branch counts as the new most-recent card swipe.
            # Stamp it BEFORE dispatch so a re-entrant call (toggle ->
            # pause -> play) observes the up-to-date card pointer.
            self.player_status['last_card_uri'] = uri

            if decision is SpotifySwipeDecision.SECOND_TOGGLE:
                logger.info(f"Second swipe detected for: {uri}")
                self.second_swipe_action()
            else:
                logger.info(f"First swipe: {uri}")
                self.play_content(uri)
        except Exception as e:
            logger.error(f"Play card failed: {e}")

    def _fetch_and_update_status(self):
        """Fetch current playback from the Spotify API and update cached status.

        Lets exceptions (including SpotifyException 429) propagate so callers
        can decide how to handle them.
        """
        self._refresh_token_if_needed()
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

    @plugs.tag
    def playerstatus(self) -> Dict[str, Any]:
        """
        Get current player status

        Returns:
            Dictionary with current playback state
        """
        if not self.sp_client:
            return self.player_status.copy()
        try:
            self._fetch_and_update_status()
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
        if not self.sp_client:
            return []
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


def initialize():
    """Initialize Spotify player plugin.

    Item 3: the ``@plugs.initialize`` decorator is applied inside
    :func:`init_plugin`.
    """
    global player_ctrl
    player_ctrl = PlayerSpotify()
    plugs.register(player_ctrl, name='ctrl')

    # Register with the player coordinator so cross-backend handoffs
    # (MPD/podcast claiming the active slot) pause then stop Spotify
    # cleanly before the new backend takes over. pause(1) leaves the
    # Spotify-side cursor in place, preserving resume position; stop
    # is bounded by the coordinator's 5s timeout so a slow Spotify
    # API hiccup cannot stall the handoff.
    #
    # publish_cleanup_fn (Phase 5a, project_phase_3c_followups.md #2):
    # invoked after pause+stop but before the slot is reassigned so
    # the UI sees a cleared playerstatus snapshot. Critical during
    # Spotify 429 storms where the status loop's adaptive backoff
    # would otherwise leave the UI stuck on a stale Spotify track for
    # tens of seconds after the user swiped an MPD/podcast card.
    get_coordinator().register(
        name='spotify',
        pause_fn=lambda: player_ctrl.pause(1),
        stop_fn=player_ctrl.stop,
        publish_cleanup_fn=player_ctrl._publish_cleanup_status,
    )

    logger.info("Spotify player plugin registered as 'playerspotify.ctrl'")


def atexit(**ignored_kwargs):
    """Cleanup on exit. Registered via :func:`init_plugin`."""
    global player_ctrl
    if player_ctrl:
        return player_ctrl.exit()


def init_plugin():
    """Register initializer and atexit with plugs (Item 3)."""
    plugs.initialize(initialize)
    plugs.atexit(atexit)
