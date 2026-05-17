# -*- coding: utf-8 -*-
"""
Podcast Episode Download Manager - Cache management for seekable playback

Handles:
- Episode download with progress tracking
- LRU cache management with automatic eviction
- Disk space monitoring
- Cache metadata persistence
"""

import logging
import json
import hashlib
import os
import shutil
import tempfile
import requests
from pathlib import Path
from typing import Dict, Optional, Any, Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

import jukebox.publishing as publishing

logger = logging.getLogger('jb.EpisodeDownloadManager')


class EpisodeDownloadManager:
    """Manages podcast episode download cache with LRU eviction"""

    def __init__(self, cache_path: Path, max_cache_size_mb: int,
                 download_timeout: int = 300, min_free_space_mb: int = 500):
        """
        Initialize episode download manager

        Args:
            cache_path: Directory for cached episodes
            max_cache_size_mb: Maximum cache size in MB
            download_timeout: Download timeout in seconds
            min_free_space_mb: Minimum free disk space required (MB)
        """
        self.cache_path = Path(cache_path)
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.download_timeout = download_timeout
        self.min_free_space_bytes = min_free_space_mb * 1024 * 1024

        # Create cache directory if needed
        self.cache_path.mkdir(parents=True, exist_ok=True)

        # Metadata file
        self.metadata_file = self.cache_path / '.cache_metadata.json'

        # Load or initialize metadata
        self.metadata = self._load_metadata()

        # Cleanup orphaned files
        self._cleanup_orphaned_files()

        logger.info(f"Episode cache initialized: {len(self.metadata.get('episodes', {}))} episodes, "
                    f"{self.metadata.get('total_size_bytes', 0) / (1024 * 1024):.1f} MB / "
                    f"{max_cache_size_mb} MB")

    def _load_metadata(self) -> Dict[str, Any]:
        """Load cache metadata from JSON file"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    metadata = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cache metadata: {e}")
                metadata = {}
        else:
            metadata = {}

        # Initialize structure if needed
        if 'episodes' not in metadata:
            metadata['episodes'] = {}
        if 'total_size_bytes' not in metadata:
            metadata['total_size_bytes'] = 0
        if 'max_cache_size_bytes' not in metadata:
            metadata['max_cache_size_bytes'] = self.max_cache_size_bytes

        return metadata

    def save_metadata(self):
        """Save cache metadata atomically using write-temp-rename pattern"""
        temp_path = None
        try:
            self.metadata['max_cache_size_bytes'] = self.max_cache_size_bytes

            # Write to temp file in same directory (ensures same filesystem)
            metadata_dir = os.path.dirname(self.metadata_file)
            os.makedirs(metadata_dir, exist_ok=True)

            with tempfile.NamedTemporaryFile(
                mode='w',
                dir=metadata_dir,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                json.dump(self.metadata, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())  # Force write to disk
                temp_path = temp_file.name

            # Atomic rename (overwrites target atomically on POSIX)
            shutil.move(temp_path, self.metadata_file)
            logger.debug(f"Cache metadata saved atomically to {self.metadata_file}")

        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")
            # Clean up temp file if it exists
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception:
                    pass

    def _cleanup_orphaned_files(self):
        """Remove files in cache directory that aren't in metadata"""
        if not self.cache_path.exists():
            return

        tracked_files = set(ep['file_path'] for ep in self.metadata.get('episodes', {}).values())
        actual_files = set(f.name for f in self.cache_path.iterdir()
                          if f.is_file() and not f.name.startswith('.'))

        orphaned = actual_files - tracked_files
        for filename in orphaned:
            try:
                (self.cache_path / filename).unlink()
                logger.info(f"Removed orphaned cache file: {filename}")
            except Exception as e:
                logger.warning(f"Failed to remove orphaned file {filename}: {e}")

    def _get_episode_hash(self, episode_guid: str) -> str:
        """Generate hash for episode GUID"""
        return hashlib.sha256(episode_guid.encode()).hexdigest()[:16]

    def _get_extension_from_url(self, url: str, content_type: Optional[str] = None) -> str:
        """Extract file extension from URL or Content-Type header"""
        # Try Content-Type header first
        if content_type:
            if 'audio/mpeg' in content_type or 'audio/mp3' in content_type:
                return 'mp3'
            elif 'audio/mp4' in content_type or 'audio/m4a' in content_type:
                return 'm4a'
            elif 'audio/ogg' in content_type:
                return 'ogg'
            elif 'audio/wav' in content_type:
                return 'wav'

        # Fallback to URL parsing
        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith('.mp3'):
            return 'mp3'
        elif path.endswith('.m4a'):
            return 'm4a'
        elif path.endswith('.ogg'):
            return 'ogg'
        elif path.endswith('.wav'):
            return 'wav'

        # Default to mp3 if unknown
        return 'mp3'

    def _get_free_disk_space(self) -> int:
        """Get free disk space in bytes"""
        stat = shutil.disk_usage(self.cache_path)
        return stat.free

    def is_cached(self, episode_guid: str) -> bool:
        """
        Check if episode is cached

        Args:
            episode_guid: Episode GUID

        Returns:
            True if episode is in cache
        """
        ep_hash = self._get_episode_hash(episode_guid)
        if ep_hash in self.metadata.get('episodes', {}):
            # Verify file actually exists
            file_path = self.cache_path / self.metadata['episodes'][ep_hash]['file_path']
            return file_path.exists()
        return False

    def get_local_path(self, episode_guid: str) -> Optional[Path]:
        """
        Get local file path for cached episode

        Args:
            episode_guid: Episode GUID

        Returns:
            Path to cached file or None if not cached
        """
        ep_hash = self._get_episode_hash(episode_guid)
        if ep_hash in self.metadata.get('episodes', {}):
            file_path = self.cache_path / self.metadata['episodes'][ep_hash]['file_path']
            if file_path.exists():
                # Update last accessed time in memory (persisted on eviction/shutdown)
                self.metadata['episodes'][ep_hash]['last_accessed'] = datetime.now(timezone.utc).isoformat()
                return file_path.resolve()
        return None

    def download_episode(self, episode_url: str, episode_guid: str,  # noqa: C901
                        episode_title: str = "", podcast_title: str = "",
                        progress_callback: Optional[Callable[[int, int], None]] = None) -> Path:
        """
        Download episode to cache

        Args:
            episode_url: Episode audio URL
            episode_guid: Episode GUID
            episode_title: Episode title (for metadata)
            podcast_title: Podcast title (for metadata)
            progress_callback: Optional callback(downloaded_bytes, total_bytes)

        Returns:
            Path to downloaded file

        Raises:
            Exception: On download failure
        """
        ep_hash = self._get_episode_hash(episode_guid)

        # Check if already cached
        if self.is_cached(episode_guid):
            logger.info(f"Episode already cached: {ep_hash}")
            return self.get_local_path(episode_guid)

        # Check free disk space
        free_space = self._get_free_disk_space()
        if free_space < self.min_free_space_bytes:
            raise Exception(f"Insufficient disk space: {free_space / (1024 * 1024):.1f} MB free, "
                          f"need {self.min_free_space_bytes / (1024 * 1024):.1f} MB minimum")

        logger.info(f"Downloading episode: {episode_url}")

        try:
            # Start download with streaming
            response = requests.get(episode_url, stream=True, timeout=(10, self.download_timeout))
            response.raise_for_status()

            # Get file extension
            content_type = response.headers.get('content-type', '')
            extension = self._get_extension_from_url(episode_url, content_type)

            # Create temp file path
            temp_filename = f"ep_{ep_hash}_temp.{extension}"
            temp_file_path = self.cache_path / temp_filename
            final_filename = f"ep_{ep_hash}.{extension}"
            final_file_path = self.cache_path / final_filename

            # Get total size
            total_size = int(response.headers.get('content-length', 0))
            logger.info(f"Download size: {total_size / (1024 * 1024):.1f} MB")

            # Check if we need to evict episodes
            if total_size > 0:
                available_space = self.max_cache_size_bytes - self.metadata.get('total_size_bytes', 0)
                if total_size > available_space:
                    bytes_needed = total_size - available_space
                    logger.info(f"Cache full, need to free {bytes_needed / (1024 * 1024):.1f} MB")
                    self._evict_oldest_episodes(bytes_needed)

            # Download with progress tracking
            downloaded = 0
            last_progress_mb = 0
            chunk_size = 8192

            with open(temp_file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Call progress callback
                        if progress_callback:
                            progress_callback(downloaded, total_size)

                        # Publish progress every 1MB
                        progress_mb = downloaded / (1024 * 1024)
                        if progress_mb - last_progress_mb >= 1.0:
                            last_progress_mb = progress_mb
                            percent = (downloaded / total_size * 100) if total_size > 0 else 0
                            publishing.get_publisher().send('podcast.download_progress', {
                                'episode_guid': episode_guid,
                                'downloaded_bytes': downloaded,
                                'total_bytes': total_size,
                                'percent': percent
                            })

            # Get actual file size
            file_size = temp_file_path.stat().st_size

            # Move temp file to final location
            temp_file_path.rename(final_file_path)

            # Update metadata
            self.metadata['episodes'][ep_hash] = {
                'episode_guid': episode_guid,
                'episode_url': episode_url,
                'file_path': final_filename,
                'file_size_bytes': file_size,
                'download_timestamp': datetime.now(timezone.utc).isoformat(),
                'last_accessed': datetime.now(timezone.utc).isoformat(),
                'podcast_title': podcast_title,
                'episode_title': episode_title
            }
            self.metadata['total_size_bytes'] = self.metadata.get('total_size_bytes', 0) + file_size
            self.save_metadata()

            logger.info(f"Downloaded episode to {final_filename} ({file_size / (1024 * 1024):.1f} MB)")
            return final_file_path.resolve()

        except requests.exceptions.Timeout:
            logger.error(f"Download timeout after {self.download_timeout}s")
            raise Exception("Download timeout")
        except requests.exceptions.RequestException as e:
            logger.error(f"Download failed: {e}")
            raise Exception(f"Download failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected download error: {e}")
            # Clean up temp file if it exists
            if temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass
            raise
        finally:
            # Ensure temp file is cleaned up
            if 'temp_file_path' in locals() and temp_file_path.exists():
                try:
                    temp_file_path.unlink()
                except Exception:
                    pass

    def _evict_oldest_episodes(self, bytes_needed: int):
        """
        Evict oldest episodes to free space

        Args:
            bytes_needed: Minimum bytes to free
        """
        if not self.metadata.get('episodes'):
            return

        # Sort episodes by last accessed time (oldest first)
        episodes = list(self.metadata['episodes'].items())
        episodes.sort(key=lambda x: x[1].get('last_accessed', ''))

        bytes_freed = 0
        for ep_hash, ep_data in episodes:
            if bytes_freed >= bytes_needed:
                break

            try:
                file_path = self.cache_path / ep_data['file_path']
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Evicted episode: {ep_data.get('episode_title', ep_hash)} "
                              f"({ep_data['file_size_bytes'] / (1024 * 1024):.1f} MB)")

                bytes_freed += ep_data['file_size_bytes']
                self.metadata['total_size_bytes'] -= ep_data['file_size_bytes']
                del self.metadata['episodes'][ep_hash]
            except Exception as e:
                logger.warning(f"Failed to evict episode {ep_hash}: {e}")

        self.save_metadata()
        logger.info(f"Evicted episodes, freed {bytes_freed / (1024 * 1024):.1f} MB")

    def evict_episode(self, episode_guid: str):
        """
        Remove a specific episode from cache

        Args:
            episode_guid: Episode GUID
        """
        ep_hash = self._get_episode_hash(episode_guid)
        if ep_hash not in self.metadata.get('episodes', {}):
            logger.warning(f"Episode not in cache: {episode_guid}")
            return

        ep_data = self.metadata['episodes'][ep_hash]
        try:
            file_path = self.cache_path / ep_data['file_path']
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Removed episode from cache: {ep_data.get('episode_title', ep_hash)}")

            self.metadata['total_size_bytes'] -= ep_data['file_size_bytes']
            del self.metadata['episodes'][ep_hash]
            self.save_metadata()
        except Exception as e:
            logger.error(f"Failed to evict episode {ep_hash}: {e}")

    def cleanup_cache(self, target_size_mb: Optional[int] = None):
        """
        Clean up cache to target size (or clear all if 0)

        Args:
            target_size_mb: Target cache size in MB (None = use max_cache_size)
        """
        if target_size_mb == 0:
            # Clear all episodes
            for ep_hash, ep_data in list(self.metadata.get('episodes', {}).items()):
                try:
                    file_path = self.cache_path / ep_data['file_path']
                    if file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {ep_data['file_path']}: {e}")

            self.metadata['episodes'] = {}
            self.metadata['total_size_bytes'] = 0
            self.save_metadata()
            logger.info("Cache cleared")
            return

        # Evict to target size
        if target_size_mb is None:
            target_size_mb = self.max_cache_size_bytes / (1024 * 1024)

        target_size_bytes = target_size_mb * 1024 * 1024
        current_size = self.metadata.get('total_size_bytes', 0)

        if current_size > target_size_bytes:
            bytes_to_free = current_size - target_size_bytes
            self._evict_oldest_episodes(bytes_to_free)
            logger.info(f"Cache cleaned to {target_size_mb} MB")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics

        Returns:
            Dictionary with cache statistics
        """
        total_size_mb = self.metadata.get('total_size_bytes', 0) / (1024 * 1024)
        max_size_mb = self.max_cache_size_bytes / (1024 * 1024)
        episode_count = len(self.metadata.get('episodes', {}))
        free_space_mb = self._get_free_disk_space() / (1024 * 1024)

        return {
            'episode_count': episode_count,
            'total_size_mb': round(total_size_mb, 1),
            'max_size_mb': round(max_size_mb, 1),
            'usage_percent': round((total_size_mb / max_size_mb * 100) if max_size_mb > 0 else 0, 1),
            'free_disk_space_mb': round(free_space_mb, 1),
            'cache_path': str(self.cache_path)
        }
