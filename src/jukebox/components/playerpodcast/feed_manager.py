# -*- coding: utf-8 -*-
"""
Podcast Feed Manager - RSS/Atom feed parsing and iTunes API integration

Handles:
- RSS feed parsing using feedparser
- iTunes Search API for podcast discovery
- Feed caching with configurable TTL
- Episode metadata extraction
"""

import logging
import time
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import feedparser
import requests

logger = logging.getLogger('jb.PodcastFeedManager')


class PodcastFeedManager:
    """Manages podcast feed fetching, parsing, and caching"""

    def __init__(self, cache_path: str, cache_ttl: int = 3600, itunes_enabled: bool = True,
                 itunes_search_limit: int = 20):
        """
        Initialize feed manager

        Args:
            cache_path: Path to cache directory for feed data
            cache_ttl: Cache time-to-live in seconds (default 1 hour)
            itunes_enabled: Enable iTunes Search API
            itunes_search_limit: Maximum search results from iTunes
        """
        self.cache_path = Path(cache_path).expanduser()
        self.cache_ttl = cache_ttl
        self.itunes_enabled = itunes_enabled
        self.itunes_search_limit = itunes_search_limit

        # Create cache directory
        self.cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Feed cache initialized at {self.cache_path} (TTL: {cache_ttl}s)")

    def _get_cache_file(self, feed_url: str) -> Path:
        """Get cache file path for a feed URL"""
        url_hash = hashlib.sha256(feed_url.encode()).hexdigest()[:16]
        return self.cache_path / f"feed_{url_hash}.json"

    def _is_cache_valid(self, cache_file: Path) -> bool:
        """Check if cached feed is still valid"""
        if not cache_file.exists():
            return False

        file_age = time.time() - cache_file.stat().st_mtime
        return file_age < self.cache_ttl

    def _save_to_cache(self, feed_url: str, feed_data: Dict[str, Any]):
        """Save feed data to cache"""
        cache_file = self._get_cache_file(feed_url)
        try:
            with open(cache_file, 'w') as f:
                json.dump(feed_data, f, indent=2)
            logger.debug(f"Cached feed: {feed_url}")
        except Exception as e:
            logger.warning(f"Failed to cache feed: {e}")

    def _load_from_cache(self, feed_url: str) -> Optional[Dict[str, Any]]:
        """Load feed data from cache if valid"""
        cache_file = self._get_cache_file(feed_url)
        if self._is_cache_valid(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    logger.debug(f"Using cached feed: {feed_url}")
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
        return None

    def get_podcast_id(self, feed_url: str) -> str:
        """Generate unique podcast ID from feed URL"""
        return hashlib.sha256(feed_url.encode()).hexdigest()[:16]

    def fetch_feed(self, feed_url: str, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """
        Fetch and parse podcast feed

        Args:
            feed_url: RSS feed URL
            force_refresh: Skip cache and fetch fresh data

        Returns:
            Parsed feed data with podcast and episode information
        """
        # Check cache first
        if not force_refresh:
            cached_data = self._load_from_cache(feed_url)
            if cached_data:
                return cached_data

        logger.info(f"Fetching feed: {feed_url}")
        try:
            # Parse RSS feed
            feed = feedparser.parse(feed_url)

            if feed.bozo:
                logger.warning(f"Feed parsing warning for {feed_url}: {feed.bozo_exception}")

            if not hasattr(feed, 'entries') or len(feed.entries) == 0:
                logger.error(f"No episodes found in feed: {feed_url}")
                return None

            # Extract podcast metadata
            podcast_info = {
                'podcast_id': self.get_podcast_id(feed_url),
                'feed_url': feed_url,
                'title': feed.feed.get('title', 'Unknown Podcast'),
                'description': feed.feed.get('description', ''),
                'author': feed.feed.get('author', feed.feed.get('itunes_author', '')),
                'image_url': self._extract_image_url(feed.feed),
                'language': feed.feed.get('language', 'en'),
                'last_fetched': datetime.now(timezone.utc).isoformat(),
                'episodes': []
            }

            # Extract episode metadata
            for entry in feed.entries:
                episode = self._parse_episode(entry, podcast_info['podcast_id'])
                if episode:
                    podcast_info['episodes'].append(episode)

            logger.info(f"Parsed {len(podcast_info['episodes'])} episodes from {podcast_info['title']}")

            # Cache the results
            self._save_to_cache(feed_url, podcast_info)

            return podcast_info

        except requests.RequestException as e:
            logger.error(f"Network error fetching feed {feed_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")
            return None

    def _extract_image_url(self, feed_data: Dict) -> str:
        """Extract podcast image URL from feed data"""
        # Try multiple possible locations for image
        if hasattr(feed_data, 'image'):
            if isinstance(feed_data.image, dict):
                return feed_data.image.get('href', '')

        if 'itunes_image' in feed_data:
            if isinstance(feed_data.itunes_image, dict):
                return feed_data.itunes_image.get('href', '')
            return feed_data.itunes_image

        return ''

    def _parse_episode(self, entry: Any, podcast_id: str) -> Optional[Dict[str, Any]]:  # noqa: C901
        """
        Parse episode from feed entry

        Args:
            entry: feedparser entry object
            podcast_id: Parent podcast ID

        Returns:
            Episode metadata dictionary
        """
        try:
            # Find audio enclosure (episode URL)
            audio_url = None
            duration = 0

            if hasattr(entry, 'enclosures'):
                for enclosure in entry.enclosures:
                    if enclosure.get('type', '').startswith('audio/'):
                        audio_url = enclosure.get('href', enclosure.get('url'))
                        # Try to get duration from enclosure
                        if 'length' in enclosure:
                            try:
                                duration = int(enclosure['length'])
                            except (ValueError, TypeError):
                                pass
                        break

            # Fallback to links if no enclosure found
            if not audio_url and hasattr(entry, 'links'):
                for link in entry.links:
                    if link.get('type', '').startswith('audio/'):
                        audio_url = link.get('href')
                        break

            if not audio_url:
                logger.debug(f"No audio URL found for episode: {entry.get('title', 'Unknown')}")
                return None

            # Parse publish date
            publish_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                publish_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                publish_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
            else:
                publish_date = datetime.now(timezone.utc).isoformat()

            # Extract duration from iTunes tags if not found in enclosure
            if duration == 0 and 'itunes_duration' in entry:
                duration = self._parse_duration(entry.itunes_duration)

            # Generate episode GUID
            episode_guid = entry.get('id', entry.get('guid', audio_url))

            episode = {
                'guid': episode_guid,
                'podcast_id': podcast_id,
                'title': entry.get('title', 'Untitled Episode'),
                'description': entry.get('summary', entry.get('description', '')),
                'url': audio_url,
                'publish_date': publish_date,
                'duration_seconds': duration,
                'author': entry.get('author', entry.get('itunes_author', ''))
            }

            return episode

        except Exception as e:
            logger.warning(f"Error parsing episode: {e}")
            return None

    def _parse_duration(self, duration_str: str) -> int:
        """
        Parse duration string to seconds

        Supports formats: HH:MM:SS, MM:SS, or raw seconds

        Args:
            duration_str: Duration string

        Returns:
            Duration in seconds
        """
        try:
            # Try parsing as integer first (raw seconds)
            return int(duration_str)
        except ValueError:
            pass

        # Parse time format (HH:MM:SS or MM:SS)
        try:
            parts = duration_str.split(':')
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)
        except (ValueError, AttributeError):
            logger.warning(f"Could not parse duration: {duration_str}")
            return 0

        return 0

    def search_itunes(self, query: str) -> List[Dict[str, Any]]:
        """
        Search for podcasts using iTunes Search API

        Args:
            query: Search query string

        Returns:
            List of podcast search results
        """
        if not self.itunes_enabled:
            logger.warning("iTunes Search API is disabled")
            return []

        try:
            url = "https://itunes.apple.com/search"
            params = {
                'term': query,
                'media': 'podcast',
                'entity': 'podcast',
                'limit': self.itunes_search_limit
            }

            logger.info(f"Searching iTunes for: {query}")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = []

            for item in data.get('results', []):
                result = {
                    'title': item.get('collectionName', item.get('trackName', 'Unknown')),
                    'author': item.get('artistName', ''),
                    'feed_url': item.get('feedUrl', ''),
                    'image_url': item.get('artworkUrl600', item.get('artworkUrl100', '')),
                    'genre': ', '.join(item.get('genres', [])),
                    'description': item.get('description', ''),
                    'episode_count': item.get('trackCount', 0)
                }

                # Only include results with valid feed URL
                if result['feed_url']:
                    results.append(result)

            logger.info(f"Found {len(results)} podcasts for query: {query}")
            return results

        except requests.RequestException as e:
            logger.error(f"iTunes search failed: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error in iTunes search: {e}")
            return []

    def get_episodes(self, feed_url: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Get episodes from a podcast feed

        Args:
            feed_url: RSS feed URL
            force_refresh: Force fresh fetch

        Returns:
            List of episode dictionaries
        """
        feed_data = self.fetch_feed(feed_url, force_refresh)
        if feed_data:
            return feed_data.get('episodes', [])
        return []

    def clear_cache(self):
        """Clear all cached feed data"""
        try:
            for cache_file in self.cache_path.glob('feed_*.json'):
                cache_file.unlink()
            logger.info("Feed cache cleared")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
