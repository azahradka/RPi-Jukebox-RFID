# -*- coding: utf-8 -*-
"""Integration tests for Spotify player plugin

Tests interactions between components (auth, content resolver, player)
without actual network calls. Validates the full flow from RFID card
swipe to playback command, token lifecycle, and Feb 2026 API deprecations.
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from components.playerspotify.spotify_auth import SpotifyAuthManager
from components.playerspotify.content_resolver import SpotifyContentResolver


# ============================================================================
# Auth + Content Resolver integration
# ============================================================================

class TestAuthTokenLifecycle:
    """Test the full token lifecycle: save, load, expire, refresh"""

    def test_token_roundtrip_encryption(self):
        """Test token survives encrypt -> save -> load -> decrypt cycle"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            cred_file = f.name

        try:
            auth = SpotifyAuthManager(
                client_id='test_id_123',
                client_secret='test_secret_456',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )

            token = {
                'access_token': 'BQDj1x2y3z4',
                'refresh_token': 'AQBk9m8n7o6',
                'expires_at': time.time() + 3600,
                'scope': 'user-read-playback-state user-modify-playback-state',
                'token_type': 'Bearer'
            }

            # Save
            auth._save_token(token)
            assert Path(cred_file).stat().st_size > 0

            # Load in a new instance (simulating restart)
            auth2 = SpotifyAuthManager(
                client_id='test_id_123',
                client_secret='test_secret_456',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )

            assert auth2.token_info is not None
            assert auth2.token_info['access_token'] == token['access_token']
            assert auth2.token_info['refresh_token'] == token['refresh_token']
            assert not auth2.is_token_expired()
        finally:
            Path(cred_file).unlink(missing_ok=True)

    def test_wrong_credentials_cannot_decrypt(self):
        """Test that tokens encrypted with one key can't be decrypted with another"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            cred_file = f.name

        try:
            # Save with one set of credentials
            auth1 = SpotifyAuthManager(
                client_id='correct_id',
                client_secret='correct_secret',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )
            auth1._save_token({
                'access_token': 'secret_token',
                'expires_at': time.time() + 3600
            })

            # Try to load with different credentials
            auth2 = SpotifyAuthManager(
                client_id='wrong_id',
                client_secret='wrong_secret',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )

            # Should fail to decrypt, token_info should be None
            assert auth2.token_info is None
        finally:
            Path(cred_file).unlink(missing_ok=True)

    def test_expired_token_detected(self):
        """Test that expired tokens are correctly identified"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            cred_file = f.name

        try:
            auth = SpotifyAuthManager(
                client_id='test_id',
                client_secret='test_secret',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )

            # Token expired 10 minutes ago
            auth.token_info = {
                'access_token': 'old_token',
                'refresh_token': 'refresh_me',
                'expires_at': time.time() - 600
            }
            assert auth.is_token_expired() is True

            # Token expires in 30 seconds (within 60s buffer)
            auth.token_info['expires_at'] = time.time() + 30
            assert auth.is_token_expired() is True

            # Token expires in 2 hours (valid)
            auth.token_info['expires_at'] = time.time() + 7200
            assert auth.is_token_expired() is False
        finally:
            Path(cred_file).unlink(missing_ok=True)


# ============================================================================
# Content Resolver integration
# ============================================================================

class TestContentResolverIntegration:
    """Test content resolver with realistic API responses"""

    def test_playlist_with_null_tracks_filtered(self):
        """Test that null/removed tracks in playlists are filtered out"""
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            'items': [
                {'track': {'uri': 'spotify:track:valid1'}},
                {'track': None},  # Removed track
                {'track': {'uri': 'spotify:track:valid2'}},
                {'track': {'uri': None}},  # Track with no URI
            ],
            'next': None
        }

        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)
        result = resolver._resolve_playlist('test_playlist')

        assert result == ['spotify:track:valid1', 'spotify:track:valid2']

    def test_album_paginated_across_multiple_pages(self):
        """Test album resolution with pagination"""
        mock_client = MagicMock()
        page1 = [{'uri': f'spotify:track:p1_{i}'} for i in range(50)]
        page2 = [{'uri': f'spotify:track:p2_{i}'} for i in range(25)]

        mock_client.album_tracks.side_effect = [
            {'items': page1, 'next': 'page2_url'},
            {'items': page2, 'next': None}
        ]

        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)
        result = resolver._resolve_album('test_album')

        assert len(result) == 75
        assert result[0] == 'spotify:track:p1_0'
        assert result[50] == 'spotify:track:p2_0'

    def test_cache_persists_across_instances(self):
        """Test that cache is loaded from disk by new instances"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_client = MagicMock()
            mock_client.playlist_items.return_value = {
                'items': [{'track': {'uri': 'spotify:track:cached'}}],
                'next': None
            }

            # First instance resolves and caches
            r1 = SpotifyContentResolver(
                sp_client=mock_client, cache_enabled=True, cache_path=tmpdir
            )
            result1 = r1.resolve_uri('spotify:playlist:test')
            assert mock_client.playlist_items.call_count == 1

            # Second instance should load from disk cache
            r2 = SpotifyContentResolver(
                sp_client=mock_client, cache_enabled=True, cache_path=tmpdir
            )
            result2 = r2.resolve_uri('spotify:playlist:test')
            # Should NOT make another API call
            assert mock_client.playlist_items.call_count == 1
            assert result1 == result2

    def test_url_to_uri_end_to_end(self):
        """Test full flow from Spotify URL to resolved tracks"""
        mock_client = MagicMock()
        mock_client.album_tracks.return_value = {
            'items': [
                {'uri': 'spotify:track:t1'},
                {'uri': 'spotify:track:t2'}
            ],
            'next': None
        }

        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)
        # Pass a URL instead of URI
        result = resolver.resolve_uri('https://open.spotify.com/album/6DEjYFkNZh67HP7R9PSZvv')

        assert len(result) == 2
        mock_client.album_tracks.assert_called_once_with('6DEjYFkNZh67HP7R9PSZvv', offset=0, limit=50)


# ============================================================================
# Feb 2026 API deprecation tests
# ============================================================================

class TestFeb2026APIDeprecations:
    """Test that deprecated Spotify API endpoints are handled correctly"""

    def test_artist_uri_returns_empty_without_api_call(self):
        """Artist top tracks endpoint was removed in Feb 2026"""
        mock_client = MagicMock()
        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)

        result = resolver.resolve_uri('spotify:artist:3WrFJ7ztbogyGnTHbHJFl2')

        assert result == []
        mock_client.artist_top_tracks.assert_not_called()

    def test_artist_url_returns_empty(self):
        """Artist URLs should also be handled as deprecated"""
        mock_client = MagicMock()
        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)

        result = resolver.resolve_uri('https://open.spotify.com/artist/06HL4z0CvFAxyc27GXpf02')

        assert result == []

    def test_artist_uri_not_cached(self):
        """Empty artist results should not be cached"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_client = MagicMock()
            resolver = SpotifyContentResolver(
                sp_client=mock_client, cache_enabled=True, cache_path=tmpdir
            )

            resolver.resolve_uri('spotify:artist:test123')

            # Should not be in cache (empty results are not cached)
            assert 'spotify:artist:test123' not in resolver.cache

    def test_playlist_items_not_playlist_tracks(self):
        """Verify we use playlist_items (new endpoint), not playlist_tracks (deprecated)"""
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            'items': [{'track': {'uri': 'spotify:track:t1'}}],
            'next': None
        }

        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)
        resolver.resolve_uri('spotify:playlist:test')

        mock_client.playlist_items.assert_called_once()
        mock_client.playlist_tracks.assert_not_called()

    def test_supported_content_types(self):
        """Test that track, playlist, and album URIs still work"""
        mock_client = MagicMock()
        mock_client.playlist_items.return_value = {
            'items': [{'track': {'uri': 'spotify:track:t1'}}], 'next': None
        }
        mock_client.album_tracks.return_value = {
            'items': [{'uri': 'spotify:track:t2'}], 'next': None
        }

        resolver = SpotifyContentResolver(sp_client=mock_client, cache_enabled=False)

        # Track - no API call needed
        assert resolver.resolve_uri('spotify:track:abc') == ['spotify:track:abc']

        # Playlist - uses playlist_items
        assert len(resolver.resolve_uri('spotify:playlist:xyz')) == 1
        mock_client.playlist_items.assert_called_once()

        # Album - uses album_tracks
        assert len(resolver.resolve_uri('spotify:album:def')) == 1
        mock_client.album_tracks.assert_called_once()

        # Artist - deprecated, returns empty
        assert resolver.resolve_uri('spotify:artist:ghi') == []


# ============================================================================
# Redirect URI compliance
# ============================================================================

class TestRedirectURICompliance:
    """Test that redirect URI meets Spotify's Feb 2026 security requirements"""

    def test_default_redirect_uses_loopback_ip(self):
        """Redirect URI must use 127.0.0.1 (not localhost or hostname)"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            cred_file = f.name

        try:
            auth = SpotifyAuthManager(
                client_id='test',
                client_secret='test',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )
            assert '127.0.0.1' in auth.redirect_uri
            assert 'localhost' not in auth.redirect_uri
            assert 'phoniebox.local' not in auth.redirect_uri
        finally:
            Path(cred_file).unlink(missing_ok=True)

    def test_redirect_uri_includes_port(self):
        """Spotify requires explicit port for loopback redirect URIs"""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            cred_file = f.name

        try:
            auth = SpotifyAuthManager(
                client_id='test',
                client_secret='test',
                redirect_uri='http://127.0.0.1:8888/callback',
                credential_file=cred_file
            )
            assert ':8888' in auth.redirect_uri
        finally:
            Path(cred_file).unlink(missing_ok=True)


# ============================================================================
# Player + Content Resolver integration
# ============================================================================

class TestPlayerContentResolverFlow:
    """Test the full flow from play_card to content resolution"""

    @pytest.fixture
    def cfg_mock(self):
        cfg = MagicMock()
        cfg.getn.side_effect = lambda *args, **kwargs: {
            ('playerspotify', 'client_id'): 'int_test_id',
            ('playerspotify', 'client_secret'): 'int_test_secret',
            ('playerspotify', 'redirect_uri'): 'http://127.0.0.1:8888/callback',
            ('playerspotify', 'device_name'): 'Phoniebox',
            ('playerspotify', 'credential_file'): '/tmp/int_test_creds.json',
            ('playerspotify', 'status_file'): '/tmp/int_test_status.json',
            ('playerspotify', 'cache_enabled'): False,
            ('playerspotify', 'cache_path'): '/tmp/int_test_cache/',
            ('playerspotify', 'second_swipe_action', 'alias'): 'toggle'
        }.get(tuple(args), kwargs.get('default'))
        return cfg

    @pytest.fixture
    def sp_client(self):
        client = MagicMock()
        client.devices.return_value = {
            'devices': [{'id': 'dev123', 'name': 'Phoniebox', 'type': 'Speaker', 'is_active': False}]
        }
        client.current_playback.return_value = {
            'is_playing': True, 'progress_ms': 0, 'shuffle_state': False, 'repeat_state': 'off',
            'item': {
                'name': 'Song', 'uri': 'spotify:track:x', 'duration_ms': 200000,
                'artists': [{'name': 'Artist'}],
                'album': {'name': 'Album', 'images': [{'url': 'http://img'}]}
            }
        }
        client.playlist_items.return_value = {
            'items': [
                {'track': {'uri': 'spotify:track:t1'}},
                {'track': {'uri': 'spotify:track:t2'}},
            ],
            'next': None
        }
        return client

    def test_play_card_resolves_and_starts_playback(self, cfg_mock, sp_client):
        """Test full flow: play_card -> resolve playlist -> start_playback"""
        with patch('components.playerspotify.cfg', cfg_mock), \
             patch('components.playerspotify.SpotifyAuthManager') as mock_auth, \
             patch('components.playerspotify.spotipy.Spotify', return_value=sp_client), \
             patch('components.playerspotify.publishing.get_publisher'), \
             patch('components.playerspotify.os.path.exists', return_value=False):

            mock_auth.return_value.get_access_token.return_value = 'token'
            mock_auth.return_value.is_token_expired.return_value = False

            from components.playerspotify import PlayerSpotify
            player = PlayerSpotify()
            player.status_thread_stop.set()
            player.status_thread.join(timeout=1)

            # First swipe - should resolve and play
            player.play_card('spotify:playlist:test_pl')

            sp_client.playlist_items.assert_called_once()
            sp_client.start_playback.assert_called_once_with(
                device_id='dev123',
                uris=['spotify:track:t1', 'spotify:track:t2']
            )
            assert player.player_status['state'] == 'playing'
            assert player.player_status['last_played_uri'] == 'spotify:playlist:test_pl'

    def test_second_swipe_toggles(self, cfg_mock, sp_client):
        """Test that second swipe of same card toggles playback"""
        with patch('components.playerspotify.cfg', cfg_mock), \
             patch('components.playerspotify.SpotifyAuthManager') as mock_auth, \
             patch('components.playerspotify.spotipy.Spotify', return_value=sp_client), \
             patch('components.playerspotify.publishing.get_publisher'), \
             patch('components.playerspotify.os.path.exists', return_value=False):

            mock_auth.return_value.get_access_token.return_value = 'token'
            mock_auth.return_value.is_token_expired.return_value = False

            from components.playerspotify import PlayerSpotify
            player = PlayerSpotify()
            player.status_thread_stop.set()
            player.status_thread.join(timeout=1)

            uri = 'spotify:playlist:test_pl'

            # First swipe
            player.play_card(uri)
            assert player.player_status['state'] == 'playing'

            # Second swipe - should toggle (pause since currently playing)
            sp_client.current_playback.return_value['is_playing'] = True
            player.play_card(uri)
            sp_client.pause_playback.assert_called()
