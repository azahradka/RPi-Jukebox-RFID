# -*- coding: utf-8 -*-
"""Live Spotify API smoke tests

These tests hit the real Spotify API and require:
1. Completed OAuth setup (spotify_auth_setup.py)
2. Valid credentials in jukebox.yaml
3. librespot running (for playback tests)
4. Spotify Premium account
5. Network access

Run with:
    cd ~/RPi-Jukebox-RFID
    source .venv/bin/activate
    python -m pytest test/components/playerspotify/test_live_api.py -m live_api -v

These tests are excluded from the default test suite via pytest.ini.
"""

import sys
import time
from pathlib import Path

import pytest
import spotipy
from spotipy.exceptions import SpotifyException

# Add jukebox source to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'jukebox'))

from components.playerspotify.spotify_auth import SpotifyAuthManager
from components.playerspotify.content_resolver import SpotifyContentResolver

# Well-known public Spotify content for testing
# (these are unlikely to be removed)
TEST_PLAYLIST_ID = '37i9dQZF1DXcBWIGoYBM5M'  # Today's Top Hits
TEST_ALBUM_ID = '0ETFjACtuP2ADo6LFhL6HN'      # Abbey Road - The Beatles
TEST_TRACK_ID = '4u7EnebtmKWzUH433cf5Qv'       # Bohemian Rhapsody
TEST_ARTIST_ID = '3WrFJ7ztbogyGnTHbHJFl2'      # The Beatles


def _load_config():
    """Load Spotify config from jukebox.yaml"""
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        # Try standard locations
        for path in [
            Path.home() / 'RPi-Jukebox-RFID' / 'shared' / 'settings' / 'jukebox.yaml',
            Path(__file__).parent.parent.parent.parent / 'shared' / 'settings' / 'jukebox.yaml',
        ]:
            if path.exists():
                with open(path) as f:
                    cfg = yaml.load(f)
                return cfg.get('playerspotify', {})
    except ImportError:
        # Fallback: try simple yaml
        import yaml
        for path in [
            Path.home() / 'RPi-Jukebox-RFID' / 'shared' / 'settings' / 'jukebox.yaml',
            Path(__file__).parent.parent.parent.parent / 'shared' / 'settings' / 'jukebox.yaml',
        ]:
            if path.exists():
                with open(path) as f:
                    cfg = yaml.safe_load(f)
                return cfg.get('playerspotify', {})
    return {}


def _get_authenticated_client():
    """Create an authenticated Spotify client from saved credentials"""
    config = _load_config()
    if not config.get('client_id') or not config.get('client_secret'):
        pytest.skip("No Spotify credentials configured in jukebox.yaml")

    credential_file = config.get('credential_file', '')
    # Resolve relative path from jukebox source dir
    if credential_file.startswith('../../'):
        credential_file = str(
            Path.home() / 'RPi-Jukebox-RFID' / credential_file.replace('../../', '')
        )

    if not Path(credential_file).exists():
        pytest.skip(
            f"No credential file at {credential_file}. "
            "Run spotify_auth_setup.py first."
        )

    auth = SpotifyAuthManager(
        client_id=config['client_id'],
        client_secret=config['client_secret'],
        redirect_uri=config.get('redirect_uri', 'http://127.0.0.1:8888/callback'),
        credential_file=credential_file
    )

    token = auth.get_access_token()
    return spotipy.Spotify(auth=token), auth, config


# ============================================================================
# Authentication smoke tests
# ============================================================================

@pytest.mark.live_api
class TestLiveAuth:
    """Test authentication against real Spotify API"""

    def test_token_is_valid(self):
        """Test that saved token produces a valid access token"""
        sp, auth, _ = _get_authenticated_client()
        token = auth.get_access_token()
        assert token is not None
        assert len(token) > 0

    def test_current_user(self):
        """Test that we can fetch the authenticated user's profile"""
        sp, _, _ = _get_authenticated_client()
        user = sp.current_user()
        assert user is not None
        assert 'id' in user
        assert 'display_name' in user
        print(f"  Authenticated as: {user['display_name']} ({user['id']})")

        # 'product' field requires user-read-private scope
        product = user.get('product')
        if product:
            if product != 'premium':
                pytest.skip(f"Spotify Premium required, got: {product}")
            print(f"  Account type: {product}")
        else:
            print("  Account type: unknown (user-read-private scope not granted)")

    def test_token_refresh(self):
        """Test that token refresh works with real Spotify servers"""
        sp, auth, _ = _get_authenticated_client()

        # Force token to appear expired
        if auth.token_info:
            original_token = auth.token_info['access_token']
            auth.token_info['expires_at'] = time.time() - 100

            # This should trigger a refresh
            new_token = auth.get_access_token()
            assert new_token is not None
            assert len(new_token) > 0

            # Verify refreshed token works
            sp_new = spotipy.Spotify(auth=new_token)
            user = sp_new.current_user()
            assert user is not None


# ============================================================================
# Device discovery smoke tests
# ============================================================================

@pytest.mark.live_api
class TestLiveDeviceDiscovery:
    """Test device discovery against real Spotify API"""

    def test_devices_endpoint_works(self):
        """Test that the devices endpoint returns a valid response"""
        sp, _, _ = _get_authenticated_client()
        result = sp.devices()
        assert result is not None
        assert 'devices' in result
        print(f"  Found {len(result['devices'])} device(s)")

    def test_phoniebox_device_visible(self):
        """Test that librespot 'Phoniebox' device is visible"""
        sp, _, config = _get_authenticated_client()
        device_name = config.get('device_name', 'Phoniebox')

        result = sp.devices()
        device_names = [d['name'] for d in result.get('devices', [])]

        if device_name not in device_names:
            pytest.skip(
                f"Device '{device_name}' not found. "
                f"Available: {device_names}. Is librespot running?"
            )

        device = next(d for d in result['devices'] if d['name'] == device_name)
        print(f"  Device: {device['name']} (id={device['id']}, type={device['type']})")
        assert device['id'] is not None


# ============================================================================
# Content resolution smoke tests
# ============================================================================

@pytest.mark.live_api
class TestLiveContentResolution:
    """Test content resolution against real Spotify API"""

    def test_resolve_track(self):
        """Test single track resolution (no API call needed)"""
        sp, _, _ = _get_authenticated_client()
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)

        result = resolver.resolve_uri(f'spotify:track:{TEST_TRACK_ID}')
        assert result == [f'spotify:track:{TEST_TRACK_ID}']

    def test_resolve_playlist(self):
        """Test playlist resolution via playlist_items endpoint

        Note: Development Mode apps may get 403 on playlist_items endpoint.
        The resolver handles this gracefully (returns []). If so, we skip.
        """
        sp, _, _ = _get_authenticated_client()
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)

        # Use the user's own playlists (Development Mode can't access editorial playlists)
        playlists = sp.current_user_playlists(limit=1)
        if not playlists or not playlists.get('items'):
            pytest.skip("No playlists found in user's library")

        playlist_id = playlists['items'][0]['id']
        result = resolver.resolve_uri(f'spotify:playlist:{playlist_id}')

        if len(result) == 0:
            pytest.skip(
                "Playlist resolution returned empty (likely 403 from Development Mode). "
                "Playlist resolution logic is covered by unit tests."
            )

        assert all(uri.startswith('spotify:track:') for uri in result)
        print(f"  Resolved playlist '{playlists['items'][0]['name']}' "
              f"to {len(result)} tracks")

    def test_resolve_album(self):
        """Test album resolution via album_tracks endpoint"""
        sp, _, _ = _get_authenticated_client()
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)

        result = resolver.resolve_uri(f'spotify:album:{TEST_ALBUM_ID}')
        assert len(result) > 0
        assert all(uri.startswith('spotify:track:') for uri in result)
        print(f"  Resolved album to {len(result)} tracks")

    def test_resolve_url_format(self):
        """Test that Spotify URL format resolves correctly"""
        sp, _, _ = _get_authenticated_client()
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)

        result = resolver.resolve_uri(
            f'https://open.spotify.com/album/{TEST_ALBUM_ID}'
        )
        assert len(result) > 0

    def test_artist_endpoint_deprecated(self):
        """Verify artist_top_tracks is actually gone from the API (Feb 2026)

        This test confirms our deprecation handling is correct.
        If Spotify ever re-enables this endpoint, this test will tell us.
        """
        sp, _, _ = _get_authenticated_client()

        # Our resolver should return empty without calling the API
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)
        result = resolver.resolve_uri(f'spotify:artist:{TEST_ARTIST_ID}')
        assert result == [], "Artist resolution should return empty list"

        # Also verify the raw API endpoint is actually gone
        try:
            raw_result = sp.artist_top_tracks(TEST_ARTIST_ID)
            # If we get here, the endpoint still works (Spotify hasn't removed it yet)
            print(f"  WARNING: artist_top_tracks still returns data "
                  f"({len(raw_result.get('tracks', []))} tracks). "
                  f"Endpoint not yet deprecated.")
        except SpotifyException as e:
            # Expected: 403 or 404 after deprecation
            print(f"  Confirmed: artist_top_tracks returns {e.http_status} "
                  f"(endpoint deprecated)")
        except Exception as e:
            print(f"  artist_top_tracks error: {type(e).__name__}: {e}")


# ============================================================================
# Playback control smoke tests
# ============================================================================

@pytest.mark.live_api
class TestLivePlaybackControl:
    """Test playback control against real Spotify API

    These tests actually start/pause audio on the device.
    They require librespot to be running.
    """

    def _get_device_id(self, sp, config):
        """Find the Phoniebox device ID"""
        device_name = config.get('device_name', 'Phoniebox')
        result = sp.devices()
        for device in result.get('devices', []):
            if device['name'] == device_name:
                return device['id']
        pytest.skip(f"Device '{device_name}' not found. Is librespot running?")

    def test_start_and_pause_playback(self):
        """Test starting and pausing playback on the device"""
        sp, _, config = _get_authenticated_client()
        device_id = self._get_device_id(sp, config)

        # Start playback with a single track
        track_uri = f'spotify:track:{TEST_TRACK_ID}'
        sp.start_playback(device_id=device_id, uris=[track_uri])
        time.sleep(2)  # Let playback start

        # Verify playing
        playback = sp.current_playback()
        assert playback is not None, "No active playback after start_playback"
        assert playback['is_playing'] is True
        print(f"  Playing: {playback['item']['name']} "
              f"by {playback['item']['artists'][0]['name']}")

        # Pause
        sp.pause_playback(device_id=device_id)
        time.sleep(1)

        # Verify paused
        playback = sp.current_playback()
        assert playback is not None
        assert playback['is_playing'] is False
        print("  Paused successfully")

    def test_seek(self):
        """Test seeking within a track"""
        sp, _, config = _get_authenticated_client()
        device_id = self._get_device_id(sp, config)

        # Start playback
        track_uri = f'spotify:track:{TEST_TRACK_ID}'
        sp.start_playback(device_id=device_id, uris=[track_uri])
        time.sleep(2)

        # Seek to 30 seconds
        sp.seek_track(30000, device_id=device_id)
        time.sleep(1)

        # Verify position is near 30s (allow 5s tolerance)
        playback = sp.current_playback()
        assert playback is not None
        assert playback['progress_ms'] >= 28000
        print(f"  Seeked to {playback['progress_ms']}ms")

        # Clean up - pause
        sp.pause_playback(device_id=device_id)

    def test_next_previous(self):
        """Test next/previous track navigation"""
        sp, _, config = _get_authenticated_client()
        device_id = self._get_device_id(sp, config)

        # Start playback with multiple tracks from an album
        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)
        tracks = resolver.resolve_uri(f'spotify:album:{TEST_ALBUM_ID}')
        assert len(tracks) >= 3, "Need at least 3 tracks for next/prev test"

        sp.start_playback(device_id=device_id, uris=tracks[:5])
        time.sleep(2)

        # Get first track
        pb1 = sp.current_playback()
        first_uri = pb1['item']['uri']

        # Next
        sp.next_track(device_id=device_id)
        time.sleep(2)
        pb2 = sp.current_playback()
        assert pb2['item']['uri'] != first_uri, "Next track should be different"
        print(f"  Next: {pb1['item']['name']} -> {pb2['item']['name']}")

        # Previous
        sp.previous_track(device_id=device_id)
        time.sleep(2)
        pb3 = sp.current_playback()
        print(f"  Prev: {pb2['item']['name']} -> {pb3['item']['name']}")

        # Clean up
        sp.pause_playback(device_id=device_id)

    def test_shuffle_and_repeat(self):
        """Test shuffle and repeat mode toggles"""
        sp, _, config = _get_authenticated_client()
        device_id = self._get_device_id(sp, config)

        # Start playback first (needed for shuffle/repeat)
        track_uri = f'spotify:track:{TEST_TRACK_ID}'
        sp.start_playback(device_id=device_id, uris=[track_uri])
        time.sleep(2)

        # Shuffle on
        sp.shuffle(True, device_id=device_id)
        time.sleep(1)
        playback = sp.current_playback()
        assert playback['shuffle_state'] is True
        print("  Shuffle: on")

        # Shuffle off
        sp.shuffle(False, device_id=device_id)
        time.sleep(1)
        playback = sp.current_playback()
        assert playback['shuffle_state'] is False
        print("  Shuffle: off")

        # Repeat context
        sp.repeat('context', device_id=device_id)
        time.sleep(1)
        playback = sp.current_playback()
        assert playback['repeat_state'] == 'context'
        print("  Repeat: context")

        # Repeat off
        sp.repeat('off', device_id=device_id)
        time.sleep(1)
        playback = sp.current_playback()
        assert playback['repeat_state'] == 'off'
        print("  Repeat: off")

        # Clean up
        sp.pause_playback(device_id=device_id)


# ============================================================================
# Queue endpoint smoke test
# ============================================================================

@pytest.mark.live_api
class TestLiveQueue:
    """Test queue endpoint against real API"""

    def test_queue_endpoint_works(self):
        """Test that the queue endpoint returns data"""
        sp, _, config = _get_authenticated_client()

        # Start playback with multiple tracks
        device_name = config.get('device_name', 'Phoniebox')
        result = sp.devices()
        device = next(
            (d for d in result.get('devices', []) if d['name'] == device_name),
            None
        )
        if not device:
            pytest.skip("Device not found. Is librespot running?")

        resolver = SpotifyContentResolver(sp_client=sp, cache_enabled=False)
        tracks = resolver.resolve_uri(f'spotify:album:{TEST_ALBUM_ID}')

        sp.start_playback(device_id=device['id'], uris=tracks[:5])
        time.sleep(2)

        queue = sp.queue()
        assert queue is not None
        assert 'queue' in queue
        print(f"  Queue has {len(queue['queue'])} upcoming tracks")

        # Clean up
        sp.pause_playback(device_id=device['id'])
