# -*- coding: utf-8 -*-
"""
Spotify Content Resolver

Resolves Spotify URIs (playlist, album, artist, track) to lists of track URIs
with caching to minimize API calls and improve performance.

Supported URI Types:
- spotify:track:ID - Single track
- spotify:playlist:ID - Playlist (all tracks)
- spotify:album:ID - Album (all tracks)
- spotify:artist:ID - Artist's top tracks (configurable limit)

Caching:
- 1-hour TTL for resolved content
- Disk-based cache for persistence across restarts
- Configurable cache path

URI Format:
- Standard: spotify:track:11dFghVXANMlKmJXsNCbNl
- URL format also supported: https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl

References:
- https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids
"""

import re
import json
import logging
import time
import threading
from pathlib import Path
from typing import List, Optional, Dict, Any
from spotipy.exceptions import SpotifyException

logger = logging.getLogger('jb.SpotifyResolver')

# Cache TTL in seconds (1 hour)
CACHE_TTL = 3600


class SpotifyContentResolver:
    """Resolves Spotify URIs to track lists with caching"""

    def __init__(self, sp_client, cache_enabled: bool = True, cache_path: str = None,
                 artist_track_limit: int = 20, lock: threading.RLock = None):
        """
        Initialize content resolver

        Args:
            sp_client: Spotify client instance (spotipy.Spotify)
            cache_enabled: Enable disk-based caching
            cache_path: Path to cache directory
            artist_track_limit: Max tracks to fetch for artist URIs
            lock: Thread lock for API access
        """
        self.sp_client = sp_client
        self.cache_enabled = cache_enabled
        self.artist_track_limit = artist_track_limit
        self.lock = lock or threading.RLock()

        # Initialize cache
        self.cache: Dict[str, Dict[str, Any]] = {}

        if cache_enabled and cache_path:
            self.cache_path = Path(cache_path).expanduser()
            self.cache_path.mkdir(parents=True, exist_ok=True)
            self.cache_file = self.cache_path / 'content_cache.json'
            self._load_cache()
        else:
            self.cache_path = None
            self.cache_file = None

    def _load_cache(self):
        """Load cache from disk"""
        if not self.cache_file or not self.cache_file.exists():
            return

        try:
            with open(self.cache_file, 'r') as f:
                self.cache = json.load(f)
            logger.debug(f"Loaded cache with {len(self.cache)} entries")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            self.cache = {}

    def _save_cache(self):
        """Save cache to disk"""
        if not self.cache_file:
            return

        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
            logger.debug(f"Saved cache with {len(self.cache)} entries")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

    def _is_cache_valid(self, uri: str) -> bool:
        """
        Check if cached entry is still valid

        Args:
            uri: Spotify URI

        Returns:
            True if cache entry exists and is not expired
        """
        if uri not in self.cache:
            return False

        cached_time = self.cache[uri].get('timestamp', 0)
        return (time.time() - cached_time) < CACHE_TTL

    def _cache_content(self, uri: str, track_uris: List[str]):
        """
        Cache resolved content

        Args:
            uri: Spotify URI
            track_uris: List of resolved track URIs
        """
        if not self.cache_enabled:
            return

        self.cache[uri] = {
            'timestamp': time.time(),
            'track_uris': track_uris
        }
        self._save_cache()

    def _get_cached_content(self, uri: str) -> Optional[List[str]]:
        """
        Get cached content if valid

        Args:
            uri: Spotify URI

        Returns:
            List of track URIs or None if not cached/expired
        """
        if not self.cache_enabled or not self._is_cache_valid(uri):
            return None

        return self.cache[uri].get('track_uris')

    def _normalize_uri(self, uri: str) -> str:
        """
        Normalize Spotify URI format

        Converts URLs to URI format:
        https://open.spotify.com/track/ID -> spotify:track:ID

        Args:
            uri: Spotify URI or URL

        Returns:
            Normalized spotify:type:id format
        """
        # Already in correct format
        if uri.startswith('spotify:'):
            return uri

        # Convert URL to URI
        url_pattern = r'https?://open\.spotify\.com/(\w+)/([a-zA-Z0-9]+)'
        match = re.match(url_pattern, uri)
        if match:
            content_type, content_id = match.groups()
            return f"spotify:{content_type}:{content_id}"

        # Invalid format
        raise ValueError(f"Invalid Spotify URI format: {uri}")

    def _parse_uri(self, uri: str) -> tuple:
        """
        Parse Spotify URI into type and ID

        Args:
            uri: Spotify URI (spotify:type:id)

        Returns:
            Tuple of (content_type, content_id)
        """
        parts = uri.split(':')
        if len(parts) != 3 or parts[0] != 'spotify':
            raise ValueError(f"Invalid Spotify URI: {uri}")

        return parts[1], parts[2]

    def _resolve_track(self, track_id: str) -> List[str]:
        """
        Resolve single track URI

        Args:
            track_id: Spotify track ID

        Returns:
            List containing single track URI
        """
        return [f"spotify:track:{track_id}"]

    def _resolve_playlist(self, playlist_id: str) -> List[str]:
        """
        Resolve playlist to track URIs

        Args:
            playlist_id: Spotify playlist ID

        Returns:
            List of track URIs in playlist
        """
        try:
            track_uris = []
            offset = 0
            limit = 100

            with self.lock:
                while True:
                    results = self.sp_client.playlist_items(
                        playlist_id,
                        offset=offset,
                        limit=limit,
                        fields='items(track(uri)),next'
                    )

                    for item in results['items']:
                        if item['track'] and item['track']['uri']:
                            track_uris.append(item['track']['uri'])

                    # Check if there are more tracks
                    if not results['next']:
                        break
                    offset += limit

            logger.info(f"Resolved playlist {playlist_id} to {len(track_uris)} tracks")
            return track_uris
        except SpotifyException as e:
            logger.error(f"Failed to resolve playlist {playlist_id}: {e}")
            return []

    def _resolve_album(self, album_id: str) -> List[str]:
        """
        Resolve album to track URIs

        Args:
            album_id: Spotify album ID

        Returns:
            List of track URIs in album
        """
        try:
            track_uris = []
            offset = 0
            limit = 50

            with self.lock:
                while True:
                    results = self.sp_client.album_tracks(album_id, offset=offset, limit=limit)

                    for track in results['items']:
                        if track['uri']:
                            track_uris.append(track['uri'])

                    # Check if there are more tracks
                    if not results['next']:
                        break
                    offset += limit

            logger.info(f"Resolved album {album_id} to {len(track_uris)} tracks")
            return track_uris
        except SpotifyException as e:
            logger.error(f"Failed to resolve album {album_id}: {e}")
            return []

    def _resolve_artist(self, artist_id: str) -> List[str]:
        """
        Resolve artist to top track URIs

        Args:
            artist_id: Spotify artist ID

        Returns:
            List of artist's top track URIs (limited by artist_track_limit)
        """
        try:
            with self.lock:
                # Get artist's top tracks (market defaults to user's country)
                results = self.sp_client.artist_top_tracks(artist_id)
                tracks = results.get('tracks', [])

                track_uris = [track['uri'] for track in tracks[:self.artist_track_limit]]

            logger.info(f"Resolved artist {artist_id} to {len(track_uris)} top tracks")
            return track_uris
        except SpotifyException as e:
            logger.error(f"Failed to resolve artist {artist_id}: {e}")
            return []

    def resolve_uri(self, uri: str) -> List[str]:
        """
        Resolve Spotify URI to list of track URIs

        Args:
            uri: Spotify URI (track, playlist, album, or artist)

        Returns:
            List of track URIs

        Raises:
            ValueError: If URI format is invalid
        """
        try:
            # Normalize URI format
            uri = self._normalize_uri(uri)

            # Check cache
            cached = self._get_cached_content(uri)
            if cached:
                logger.debug(f"Using cached content for {uri}")
                return cached

            # Parse URI
            content_type, content_id = self._parse_uri(uri)

            # Resolve based on type
            if content_type == 'track':
                track_uris = self._resolve_track(content_id)
            elif content_type == 'playlist':
                track_uris = self._resolve_playlist(content_id)
            elif content_type == 'album':
                track_uris = self._resolve_album(content_id)
            elif content_type == 'artist':
                track_uris = self._resolve_artist(content_id)
            else:
                raise ValueError(f"Unsupported content type: {content_type}")

            # Cache result
            if track_uris:
                self._cache_content(uri, track_uris)

            return track_uris

        except ValueError as e:
            logger.error(str(e))
            return []
        except Exception as e:
            logger.error(f"Unexpected error resolving {uri}: {e}")
            return []

    def clear_cache(self):
        """Clear all cached content"""
        self.cache = {}
        if self.cache_file and self.cache_file.exists():
            try:
                self.cache_file.unlink()
                logger.info("Cache cleared")
            except Exception as e:
                logger.error(f"Failed to clear cache: {e}")
