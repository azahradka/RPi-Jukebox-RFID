# -*- coding: utf-8 -*-
"""Unit tests for Spotify player plugin

Note: These tests mock the Spotify API client to avoid requiring
actual Spotify credentials and network access.
"""

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def cfg_mock():
    """Mock jukebox configuration via module-level cfg object"""
    cfg_handler = MagicMock()
    cfg_handler.getn.side_effect = lambda *args, **kwargs: {
        ('playerspotify', 'client_id'): 'test_client_id',
        ('playerspotify', 'client_secret'): 'test_client_secret',
        ('playerspotify', 'redirect_uri'): 'http://127.0.0.1:8888/callback',
        ('playerspotify', 'device_name'): 'Phoniebox',
        ('playerspotify', 'credential_file'): '/tmp/test_creds.json',
        ('playerspotify', 'status_file'): '/tmp/test_status.json',
        ('playerspotify', 'cache_enabled'): True,
        ('playerspotify', 'cache_path'): '/tmp/test_cache/',
        ('playerspotify', 'second_swipe_action', 'alias'): 'toggle'
    }.get(tuple(args), kwargs.get('default'))

    return cfg_handler


@pytest.fixture
def mock_auth_manager():
    """Mock Spotify auth manager"""
    with patch('components.playerspotify.SpotifyAuthManager') as mock_auth:
        auth_instance = MagicMock()
        auth_instance.get_access_token.return_value = 'test_access_token'
        auth_instance.is_token_expired.return_value = False
        mock_auth.return_value = auth_instance
        yield auth_instance


@pytest.fixture
def mock_sp_client():
    """Mock Spotify client"""
    client = MagicMock()

    # Mock device discovery
    client.devices.return_value = {
        'devices': [
            {
                'id': 'test_device_id',
                'name': 'Phoniebox',
                'type': 'Speaker',
                'is_active': False
            }
        ]
    }

    # Mock current playback
    client.current_playback.return_value = {
        'is_playing': True,
        'progress_ms': 30000,
        'shuffle_state': False,
        'repeat_state': 'off',
        'item': {
            'name': 'Test Track',
            'uri': 'spotify:track:test123',
            'duration_ms': 180000,
            'artists': [{'name': 'Test Artist'}],
            'album': {
                'name': 'Test Album',
                'images': [{'url': 'https://example.com/image.jpg'}]
            }
        }
    }

    # Mock queue
    client.queue.return_value = {
        'queue': [
            {
                'name': 'Track 1',
                'uri': 'spotify:track:track1',
                'duration_ms': 200000,
                'artists': [{'name': 'Artist 1'}],
                'album': {'name': 'Album 1'}
            }
        ]
    }

    return client


@pytest.fixture
def mock_content_resolver():
    """Mock content resolver.

    ``play_content`` calls ``_normalize_uri`` (pass-through) and
    ``_parse_uri`` (returns ``(content_type, content_id)``) before
    deciding whether to call ``resolve_uri``. The mock must supply
    realistic return values for both so tuple-unpacking doesn't blow
    up. ``_parse_uri`` extracts the second segment of a
    ``spotify:<type>:<id>`` URI as the content_type, matching the real
    implementation closely enough for these unit tests.
    """
    def _fake_parse_uri(uri):
        parts = uri.split(':')
        if len(parts) >= 3:
            return parts[1], parts[2]
        return 'playlist', 'unknown'

    with patch('components.playerspotify.SpotifyContentResolver') as mock_resolver:
        resolver_instance = MagicMock()
        resolver_instance.resolve_uri.return_value = [
            'spotify:track:track1',
            'spotify:track:track2',
            'spotify:track:track3'
        ]
        resolver_instance._normalize_uri.side_effect = lambda uri: uri
        resolver_instance._parse_uri.side_effect = _fake_parse_uri
        mock_resolver.return_value = resolver_instance
        yield resolver_instance


@pytest.fixture
def player(cfg_mock, mock_auth_manager, mock_sp_client, mock_content_resolver):
    """Create PlayerSpotify instance with mocked dependencies"""
    with patch('components.playerspotify.cfg', cfg_mock):
        with patch('components.playerspotify.spotipy.Spotify', return_value=mock_sp_client):
            with patch('components.playerspotify.publishing.get_publisher'):
                with patch('components.playerspotify.os.path.exists', return_value=False):
                    from components.playerspotify import PlayerSpotify

                    # Create player
                    player = PlayerSpotify()

                    # Stop background thread to avoid cleanup issues
                    player.status_thread_stop.set()
                    if player.status_thread.is_alive():
                        player.status_thread.join(timeout=1)

                    yield player


def test_player_initialization(player):
    """Test player initialization"""
    assert player.client_id == 'test_client_id'
    assert player.device_name == 'Phoniebox'
    assert player.player_status['device_id'] == 'test_device_id'


def test_get_player_type_and_version(player):
    """Test player type and version"""
    result = player.get_player_type_and_version()
    assert result['player'] == 'Spotify'
    assert 'spotipy' in result['version']


def test_play(player, mock_sp_client):
    """Test play method"""
    player.play()
    mock_sp_client.start_playback.assert_called_once()
    assert player.player_status['state'] == 'playing'


def test_pause(player, mock_sp_client):
    """Test pause method"""
    player.pause(state=1)
    mock_sp_client.pause_playback.assert_called_once()
    assert player.player_status['state'] == 'paused'


def test_pause_resume(player, mock_sp_client):
    """Test pause with state=0 (resume)"""
    player.pause(state=0)
    mock_sp_client.start_playback.assert_called_once()
    assert player.player_status['state'] == 'playing'


def test_stop(player, mock_sp_client):
    """Test stop method"""
    player.stop()
    mock_sp_client.pause_playback.assert_called_once()
    mock_sp_client.seek_track.assert_called_once_with(0, device_id='test_device_id')
    assert player.player_status['state'] == 'stopped'
    assert player.player_status['position_ms'] == 0


def test_toggle_playing_to_paused(player, mock_sp_client):
    """Test toggle from playing to paused"""
    # Set up as playing
    mock_sp_client.current_playback.return_value['is_playing'] = True

    player.toggle()
    mock_sp_client.pause_playback.assert_called_once()


def test_toggle_paused_to_playing(player, mock_sp_client):
    """Test toggle from paused to playing"""
    # Set up as paused
    mock_sp_client.current_playback.return_value['is_playing'] = False

    player.toggle()
    mock_sp_client.start_playback.assert_called_once()


def test_next_track(player, mock_sp_client):
    """Test next track method"""
    player.next()
    mock_sp_client.next_track.assert_called_once_with(device_id='test_device_id')


def test_prev_track(player, mock_sp_client):
    """Test previous track method"""
    player.prev()
    mock_sp_client.previous_track.assert_called_once_with(device_id='test_device_id')


def test_seek(player, mock_sp_client):
    """Test seek method"""
    player.seek(30)  # 30 seconds
    mock_sp_client.seek_track.assert_called_once_with(30000, device_id='test_device_id')
    assert player.player_status['position_ms'] == 30000


def test_rewind(player, mock_sp_client):
    """Test rewind method"""
    player.rewind()
    mock_sp_client.seek_track.assert_called_once_with(0, device_id='test_device_id')


def test_shuffle_toggle(player, mock_sp_client):
    """Test shuffle toggle"""
    player.player_status['shuffle'] = False
    player.shuffle('toggle')
    mock_sp_client.shuffle.assert_called_once_with(True, device_id='test_device_id')
    assert player.player_status['shuffle'] is True


def test_shuffle_on(player, mock_sp_client):
    """Test shuffle on"""
    player.shuffle('on')
    mock_sp_client.shuffle.assert_called_once_with(True, device_id='test_device_id')
    assert player.player_status['shuffle'] is True


def test_shuffle_off(player, mock_sp_client):
    """Test shuffle off"""
    player.shuffle('off')
    mock_sp_client.shuffle.assert_called_once_with(False, device_id='test_device_id')
    assert player.player_status['shuffle'] is False


def test_repeat_toggle(player, mock_sp_client):
    """Test repeat toggle"""
    player.player_status['repeat'] = 'off'
    player.repeat('toggle')
    mock_sp_client.repeat.assert_called_once_with('context', device_id='test_device_id')
    assert player.player_status['repeat'] == 'context'


def test_repeat_modes(player, mock_sp_client):
    """Test repeat mode cycling"""
    # off -> context
    player.player_status['repeat'] = 'off'
    player.repeat('toggle')
    assert player.player_status['repeat'] == 'context'

    # context -> track
    player.repeat('toggle')
    assert player.player_status['repeat'] == 'track'

    # track -> off
    player.repeat('toggle')
    assert player.player_status['repeat'] == 'off'


def test_play_content(player, mock_sp_client, mock_content_resolver):
    """Test play content method"""
    uri = 'spotify:playlist:test123'
    player.play_content(uri)

    # Should resolve URI
    mock_content_resolver.resolve_uri.assert_called_once_with(uri)

    # Should start playback
    mock_sp_client.start_playback.assert_called_once()

    # Should update status
    assert player.player_status['state'] == 'playing'
    assert player.player_status['last_played_uri'] == uri


def test_play_card_first_swipe(player, mock_sp_client, mock_content_resolver):
    """Test play card on first swipe"""
    uri = 'spotify:playlist:test123'
    player.player_status['last_played_uri'] = 'different_uri'

    player.play_card(uri)

    # Should play content
    mock_content_resolver.resolve_uri.assert_called_once_with(uri)
    mock_sp_client.start_playback.assert_called_once()


def test_play_card_second_swipe(player, mock_sp_client):
    """Test play card on second swipe (toggle)"""
    uri = 'spotify:playlist:test123'
    player.player_status['last_played_uri'] = uri

    # Set up as playing
    mock_sp_client.current_playback.return_value['is_playing'] = True

    player.play_card(uri)

    # Should toggle (pause)
    mock_sp_client.pause_playback.assert_called_once()


def test_playerstatus(player, mock_sp_client):
    """Test player status retrieval"""
    status = player.playerstatus()

    assert status['state'] == 'playing'
    assert status['current_track']['name'] == 'Test Track'
    assert status['current_track']['artist'] == 'Test Artist'
    assert status['position_ms'] == 30000


def test_playlistinfo(player, mock_sp_client):
    """Test playlist info retrieval"""
    playlist = player.playlistinfo()

    assert len(playlist) == 1
    assert playlist[0]['name'] == 'Track 1'
    assert playlist[0]['uri'] == 'spotify:track:track1'


def test_get_current_song(player, mock_sp_client):
    """Test get current song"""
    song = player.get_current_song(None)

    assert song['name'] == 'Test Track'
    assert song['artist'] == 'Test Artist'


def test_replay(player, mock_sp_client, mock_content_resolver):
    """Test replay method"""
    player.player_status['last_played_uri'] = 'spotify:playlist:test123'

    player.replay()

    # Should replay last URI
    mock_content_resolver.resolve_uri.assert_called_once_with('spotify:playlist:test123')
    mock_sp_client.start_playback.assert_called_once()


def test_replay_if_stopped(player, mock_sp_client, mock_content_resolver):
    """Test replay if stopped"""
    player.player_status['last_played_uri'] = 'spotify:playlist:test123'

    # Set up as stopped
    mock_sp_client.current_playback.return_value = None
    player.player_status['state'] = 'stopped'

    player.replay_if_stopped()

    # Should replay
    mock_content_resolver.resolve_uri.assert_called_once()


def test_device_not_found(player, mock_sp_client):
    """Test behavior when device not found"""
    # Simulate no devices
    mock_sp_client.devices.return_value = {'devices': []}
    player.player_status['device_id'] = None

    # Should handle gracefully
    player.play()
    # Should not crash, just log error


def test_play_content_artist_uri_fails(player, mock_sp_client, mock_content_resolver):
    """Test that artist URIs return empty (API endpoint removed Feb 2026)"""
    mock_content_resolver.resolve_uri.return_value = []

    player.play_content('spotify:artist:0OdUWJ0sBjDrqHygGUXeCF')

    # Should not start playback since resolve returns empty
    mock_sp_client.start_playback.assert_not_called()
