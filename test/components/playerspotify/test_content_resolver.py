# -*- coding: utf-8 -*-
"""Unit tests for Spotify content resolver"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock
from components.playerspotify.content_resolver import SpotifyContentResolver


@pytest.fixture
def mock_sp_client():
    """Create mock Spotify client"""
    return MagicMock()


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def resolver(mock_sp_client, temp_cache_dir):
    """Create content resolver instance"""
    return SpotifyContentResolver(
        sp_client=mock_sp_client,
        cache_enabled=True,
        cache_path=temp_cache_dir
    )


@pytest.fixture
def resolver_no_cache(mock_sp_client):
    """Create content resolver without caching"""
    return SpotifyContentResolver(
        sp_client=mock_sp_client,
        cache_enabled=False
    )


def test_initialization(resolver, temp_cache_dir):
    """Test resolver initialization"""
    assert resolver.sp_client is not None
    assert resolver.cache_enabled is True
    assert resolver.cache_path == Path(temp_cache_dir)


def test_normalize_uri_valid(resolver):
    """Test URI normalization"""
    # Already normalized
    uri = 'spotify:track:11dFghVXANMlKmJXsNCbNl'
    assert resolver._normalize_uri(uri) == uri

    # URL format
    url = 'https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl'
    assert resolver._normalize_uri(url) == uri

    # HTTP (should work)
    http_url = 'http://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl'
    assert resolver._normalize_uri(http_url) == uri


def test_normalize_uri_invalid(resolver):
    """Test invalid URI formats"""
    with pytest.raises(ValueError):
        resolver._normalize_uri('invalid_uri')

    with pytest.raises(ValueError):
        resolver._normalize_uri('https://example.com/track/123')


def test_parse_uri_valid(resolver):
    """Test URI parsing"""
    content_type, content_id = resolver._parse_uri('spotify:track:11dFghVXANMlKmJXsNCbNl')
    assert content_type == 'track'
    assert content_id == '11dFghVXANMlKmJXsNCbNl'

    content_type, content_id = resolver._parse_uri('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M')
    assert content_type == 'playlist'
    assert content_id == '37i9dQZF1DXcBWIGoYBM5M'


def test_parse_uri_invalid(resolver):
    """Test invalid URI parsing"""
    with pytest.raises(ValueError):
        resolver._parse_uri('track:123')

    with pytest.raises(ValueError):
        resolver._parse_uri('spotify:track')


def test_resolve_track(resolver):
    """Test single track resolution"""
    track_id = '11dFghVXANMlKmJXsNCbNl'
    result = resolver._resolve_track(track_id)
    assert result == [f'spotify:track:{track_id}']


def test_resolve_playlist(resolver, mock_sp_client):
    """Test playlist resolution"""
    playlist_id = '37i9dQZF1DXcBWIGoYBM5M'

    # Mock API response
    mock_sp_client.playlist_items.return_value = {
        'items': [
            {'track': {'uri': 'spotify:track:track1'}},
            {'track': {'uri': 'spotify:track:track2'}},
            {'track': {'uri': 'spotify:track:track3'}}
        ],
        'next': None
    }

    result = resolver._resolve_playlist(playlist_id)
    assert len(result) == 3
    assert result[0] == 'spotify:track:track1'
    assert result[2] == 'spotify:track:track3'
    mock_sp_client.playlist_items.assert_called_once()


def test_resolve_playlist_paginated(resolver, mock_sp_client):
    """Test playlist resolution with pagination"""
    playlist_id = '37i9dQZF1DXcBWIGoYBM5M'

    # Mock paginated responses
    mock_sp_client.playlist_items.side_effect = [
        {
            'items': [{'track': {'uri': f'spotify:track:track{i}'}} for i in range(100)],
            'next': 'next_page_url'
        },
        {
            'items': [{'track': {'uri': f'spotify:track:track{i}'}} for i in range(100, 150)],
            'next': None
        }
    ]

    result = resolver._resolve_playlist(playlist_id)
    assert len(result) == 150
    assert mock_sp_client.playlist_items.call_count == 2


def test_resolve_album(resolver, mock_sp_client):
    """Test album resolution"""
    album_id = '6DEjYFkNZh67HP7R9PSZvv'

    mock_sp_client.album_tracks.return_value = {
        'items': [
            {'uri': 'spotify:track:track1'},
            {'uri': 'spotify:track:track2'}
        ],
        'next': None
    }

    result = resolver._resolve_album(album_id)
    assert len(result) == 2
    assert result[0] == 'spotify:track:track1'
    mock_sp_client.album_tracks.assert_called_once()


def test_resolve_artist_returns_empty(resolver, mock_sp_client):
    """Test artist resolution returns empty list (API endpoint removed Feb 2026)"""
    artist_id = '0OdUWJ0sBjDrqHygGUXeCF'

    result = resolver._resolve_artist(artist_id)
    assert result == []
    # Should NOT call the removed API endpoint
    mock_sp_client.artist_top_tracks.assert_not_called()


def test_resolve_artist_uri_returns_empty(resolver, mock_sp_client):
    """Test that resolving a spotify:artist URI returns empty list"""
    result = resolver.resolve_uri('spotify:artist:0OdUWJ0sBjDrqHygGUXeCF')
    assert result == []
    mock_sp_client.artist_top_tracks.assert_not_called()


def test_resolve_uri_track(resolver, mock_sp_client):
    """Test resolving track URI"""
    uri = 'spotify:track:11dFghVXANMlKmJXsNCbNl'
    result = resolver.resolve_uri(uri)
    assert len(result) == 1
    assert result[0] == uri


def test_resolve_uri_with_url(resolver, mock_sp_client):
    """Test resolving Spotify URL"""
    url = 'https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl'
    result = resolver.resolve_uri(url)
    assert len(result) == 1
    assert result[0] == 'spotify:track:11dFghVXANMlKmJXsNCbNl'


def test_caching(resolver, mock_sp_client):
    """Test content caching"""
    playlist_id = '37i9dQZF1DXcBWIGoYBM5M'
    uri = f'spotify:playlist:{playlist_id}'

    mock_sp_client.playlist_items.return_value = {
        'items': [
            {'track': {'uri': 'spotify:track:track1'}},
            {'track': {'uri': 'spotify:track:track2'}}
        ],
        'next': None
    }

    # First call - should hit API
    result1 = resolver.resolve_uri(uri)
    assert len(result1) == 2
    assert mock_sp_client.playlist_items.call_count == 1

    # Second call - should use cache
    result2 = resolver.resolve_uri(uri)
    assert len(result2) == 2
    assert result1 == result2
    # Still only 1 API call (cached)
    assert mock_sp_client.playlist_items.call_count == 1


def test_cache_expiration(resolver, mock_sp_client):
    """Test cache expiration"""
    uri = 'spotify:track:test123'

    # Add expired cache entry
    resolver.cache[uri] = {
        'timestamp': time.time() - 7200,  # 2 hours ago (expired)
        'track_uris': ['spotify:track:old_track']
    }

    # Should not use expired cache
    result = resolver.resolve_uri(uri)
    assert result == ['spotify:track:test123']


def test_no_cache(resolver_no_cache, mock_sp_client):
    """Test resolver without caching"""
    playlist_id = 'test_playlist'
    uri = f'spotify:playlist:{playlist_id}'

    mock_sp_client.playlist_items.return_value = {
        'items': [
            {'track': {'uri': 'spotify:track:track1'}}
        ],
        'next': None
    }

    # First call
    result1 = resolver_no_cache.resolve_uri(uri)
    assert len(result1) == 1

    # Second call - should hit API again (no cache)
    result2 = resolver_no_cache.resolve_uri(uri)
    assert len(result2) == 1
    assert mock_sp_client.playlist_items.call_count == 2


def test_show_uri_resolves_to_episode_list(resolver, mock_sp_client):
    """Phase 3c: ``show`` URIs are supported.

    The test was previously skipped because the MagicMock returned a
    truthy value for ``results.get('next')``, causing infinite
    pagination in ``_resolve_show``. Pinning the pagination cursor to
    a falsy ``next`` lets the loop terminate. The original name
    ``test_unsupported_content_type`` was renamed because the premise
    ("show is unsupported") is stale — production has supported show
    URIs since the podcast integration landed.
    """
    show_id = '12345'
    mock_sp_client.show_episodes.return_value = {
        'items': [
            {'uri': 'spotify:episode:ep1'},
            {'uri': 'spotify:episode:ep2'},
        ],
        # CRITICAL: pin to falsy. A real MagicMock returns another
        # MagicMock (truthy) for .get('next'), which would loop forever.
        'next': None,
    }
    uri = f'spotify:show:{show_id}'
    result = resolver.resolve_uri(uri)
    assert result == ['spotify:episode:ep1', 'spotify:episode:ep2']
    mock_sp_client.show_episodes.assert_called_once_with(
        show_id, offset=0, limit=50
    )


def test_show_uri_pagination_terminates_when_next_is_falsy(resolver, mock_sp_client):
    """Multi-page show — verify the loop honours ``next``-cursor termination."""
    mock_sp_client.show_episodes.side_effect = [
        {
            'items': [{'uri': f'spotify:episode:p1_{i}'} for i in range(50)],
            'next': 'page2_url',
        },
        {
            'items': [{'uri': 'spotify:episode:final'}],
            'next': None,
        },
    ]
    result = resolver.resolve_uri('spotify:show:multi_page_show')
    assert len(result) == 51
    assert result[-1] == 'spotify:episode:final'
    assert mock_sp_client.show_episodes.call_count == 2


def test_truly_unsupported_content_type_returns_empty_and_logs(resolver, caplog):
    """A genuinely unsupported URI type returns ``[]`` and logs an error.

    The Phase 3c rename of the formerly-skipped test demanded a clear
    home for the "unsupported type" branch — ``resolve_uri`` raises
    ``ValueError`` internally then catches it, returning ``[]``. This
    test pins both the empty return and the error log.
    """
    import logging
    original_parse = resolver._parse_uri
    resolver._parse_uri = lambda uri: ('unknownkind', 'abc')
    try:
        with caplog.at_level(logging.ERROR, logger='jb.SpotifyResolver'):
            result = resolver.resolve_uri('spotify:track:dontcare')
        assert result == []
        assert any('Unsupported content type' in r.getMessage()
                   for r in caplog.records)
    finally:
        resolver._parse_uri = original_parse


def test_api_error_handling(resolver, mock_sp_client):
    """Test API error handling"""
    from spotipy.exceptions import SpotifyException

    mock_sp_client.playlist_items.side_effect = SpotifyException(
        404, 'Not Found', 'Playlist not found'
    )

    result = resolver.resolve_uri('spotify:playlist:invalid_id')
    assert result == []


def test_clear_cache(resolver, temp_cache_dir):
    """Test cache clearing"""
    # Add cache entry
    resolver.cache['test_uri'] = {
        'timestamp': time.time(),
        'track_uris': ['spotify:track:test']
    }
    resolver._save_cache()

    cache_file = Path(temp_cache_dir) / 'content_cache.json'
    assert cache_file.exists()

    # Clear cache
    resolver.clear_cache()
    assert len(resolver.cache) == 0
    assert not cache_file.exists()
