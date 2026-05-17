# -*- coding: utf-8 -*-
"""
Unit tests for Podcast Feed Manager
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import the module to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'jukebox'))

from components.playerpodcast.feed_manager import PodcastFeedManager  # noqa: E402


@pytest.fixture
def temp_cache_dir():
    """Create temporary cache directory"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def feed_manager(temp_cache_dir):
    """Create PodcastFeedManager instance for testing"""
    return PodcastFeedManager(
        cache_path=temp_cache_dir,
        cache_ttl=3600,
        itunes_enabled=True,
        itunes_search_limit=5
    )


def test_init(feed_manager, temp_cache_dir):
    """Test feed manager initialization"""
    assert feed_manager.cache_path == Path(temp_cache_dir)
    assert feed_manager.cache_ttl == 3600
    assert feed_manager.itunes_enabled is True
    assert feed_manager.cache_path.exists()


def test_get_podcast_id(feed_manager):
    """Test podcast ID generation"""
    feed_url = "https://example.com/feed.xml"
    podcast_id = feed_manager.get_podcast_id(feed_url)

    assert isinstance(podcast_id, str)
    assert len(podcast_id) == 16  # SHA256 truncated to 16 chars

    # Same URL should always produce same ID
    assert podcast_id == feed_manager.get_podcast_id(feed_url)


def test_parse_duration(feed_manager):
    """Test duration parsing"""
    # Test HH:MM:SS format
    assert feed_manager._parse_duration("01:30:45") == 5445

    # Test MM:SS format
    assert feed_manager._parse_duration("30:45") == 1845

    # Test raw seconds
    assert feed_manager._parse_duration("3600") == 3600

    # Test invalid format
    assert feed_manager._parse_duration("invalid") == 0


def test_cache_operations(feed_manager, temp_cache_dir):
    """Test feed caching"""
    feed_url = "https://example.com/feed.xml"
    feed_data = {
        'podcast_id': 'test123',
        'title': 'Test Podcast',
        'episodes': []
    }

    # Save to cache
    feed_manager._save_to_cache(feed_url, feed_data)

    # Load from cache
    cached_data = feed_manager._load_from_cache(feed_url)
    assert cached_data is not None
    assert cached_data['podcast_id'] == 'test123'
    assert cached_data['title'] == 'Test Podcast'


def test_cache_expiry(feed_manager, temp_cache_dir):
    """Test cache TTL expiration"""
    feed_url = "https://example.com/feed.xml"
    feed_data = {'test': 'data'}

    # Create feed manager with very short TTL
    short_ttl_manager = PodcastFeedManager(
        cache_path=temp_cache_dir,
        cache_ttl=0  # Expires immediately
    )

    short_ttl_manager._save_to_cache(feed_url, feed_data)

    # Should be expired
    cached_data = short_ttl_manager._load_from_cache(feed_url)
    assert cached_data is None


@patch('components.playerpodcast.feed_manager.feedparser.parse')
@patch('components.playerpodcast.feed_manager.requests.get')
def test_fetch_feed_success(mock_get, mock_parse, feed_manager):
    """Test successful feed fetch and parse.

    Phase 0b loose-end #2: production ``fetch_feed`` calls
    ``requests.get(feed_url)`` first to fetch the raw bytes, then
    hands them to ``feedparser.parse``. The original test only mocked
    ``feedparser.parse`` and let the real ``requests.get`` hit the
    network (returning 404 for example.com/feed.xml in CI), so the
    test had been skipped. Both calls must be mocked.
    """
    # Mock the HTTP fetch (production path 1: requests.get).
    mock_response = Mock()
    mock_response.content = b'<rss><channel><title>Test Podcast</title></channel></rss>'
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    # Mock feedparser's parse of the fetched bytes (production path 2).
    mock_feed = MagicMock()
    mock_feed.bozo = False
    mock_feed.feed = {
        'title': 'Test Podcast',
        'description': 'A test podcast',
        'author': 'Test Author'
    }
    mock_feed.entries = [
        {
            'title': 'Episode 1',
            'id': 'ep1',
            'enclosures': [{'type': 'audio/mpeg', 'href': 'https://example.com/ep1.mp3'}],
            'published_parsed': (2024, 1, 1, 0, 0, 0, 0, 0, 0)
        }
    ]
    mock_parse.return_value = mock_feed

    feed_url = "https://example.com/feed.xml"
    result = feed_manager.fetch_feed(feed_url)

    # requests.get was called with the feed URL.
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == feed_url
    # feedparser.parse was handed the bytes from the HTTP response.
    mock_parse.assert_called_once_with(mock_response.content)

    assert result is not None
    assert result['title'] == 'Test Podcast'
    assert result['author'] == 'Test Author'
    assert len(result['episodes']) == 1
    assert result['episodes'][0]['title'] == 'Episode 1'


@patch('components.playerpodcast.feed_manager.requests.get')
def test_search_itunes_success(mock_get, feed_manager):
    """Test iTunes search"""
    # Mock iTunes API response
    mock_response = Mock()
    mock_response.json.return_value = {
        'results': [
            {
                'collectionName': 'Test Podcast',
                'artistName': 'Test Artist',
                'feedUrl': 'https://example.com/feed.xml',
                'artworkUrl600': 'https://example.com/art.jpg',
                'genres': ['Technology'],
                'trackCount': 100
            }
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    results = feed_manager.search_itunes("test query")

    assert len(results) == 1
    assert results[0]['title'] == 'Test Podcast'
    assert results[0]['author'] == 'Test Artist'
    assert results[0]['feed_url'] == 'https://example.com/feed.xml'


@patch('components.playerpodcast.feed_manager.requests.get')
def test_search_itunes_disabled(mock_get, temp_cache_dir):
    """Test iTunes search when disabled"""
    manager = PodcastFeedManager(
        cache_path=temp_cache_dir,
        itunes_enabled=False
    )

    results = manager.search_itunes("test")

    assert results == []
    mock_get.assert_not_called()


def test_extract_image_url(feed_manager):
    """Test image URL extraction"""
    # Test itunes_image dict
    feed_data = {'itunes_image': {'href': 'https://example.com/image.jpg'}}
    url = feed_manager._extract_image_url(feed_data)
    assert url == 'https://example.com/image.jpg'

    # Test itunes_image string
    feed_data = {'itunes_image': 'https://example.com/image2.jpg'}
    url = feed_manager._extract_image_url(feed_data)
    assert url == 'https://example.com/image2.jpg'

    # Test no image
    feed_data = {}
    url = feed_manager._extract_image_url(feed_data)
    assert url == ''


def test_clear_cache(feed_manager):
    """Test cache clearing"""
    feed_url = "https://example.com/feed.xml"
    feed_data = {'test': 'data'}

    # Add some cached data
    feed_manager._save_to_cache(feed_url, feed_data)
    assert feed_manager._load_from_cache(feed_url) is not None

    # Clear cache
    feed_manager.clear_cache()

    # Should be gone
    assert feed_manager._load_from_cache(feed_url) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
