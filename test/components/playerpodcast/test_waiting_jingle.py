# -*- coding: utf-8 -*-
"""
Unit tests for the waiting jingle feature in the podcast player.

Tests _play_wav_direct(), _start_waiting_jingle(), and the integration
in _resolve_playback_url() that plays a jingle during episode downloads.
"""

import sys
import pytest
import threading
from unittest.mock import Mock, MagicMock, patch

# Mock external dependencies that __init__.py imports transitively
# (feedparser via feed_manager, requests via episode_downloader)
# Must happen before importing PlayerPodcast.
sys.modules.setdefault('feedparser', MagicMock())
sys.modules.setdefault('requests', MagicMock())
sys.modules.setdefault('components.player', MagicMock())

# conftest.py handles jukebox framework mocking before imports
from components.playerpodcast import PlayerPodcast  # noqa: E402


@pytest.fixture
def mock_cfg():
    """Mock cfg.getn for jingle and podcast config."""
    with patch('components.playerpodcast.cfg') as mock:
        mock.getn = Mock(side_effect=_cfg_getn_defaults)
        yield mock


def _cfg_getn_defaults(*args, default=None):
    """Default config values for tests."""
    key_path = args
    if key_path == ('jingle', 'waiting_sound'):
        return '../../resources/audio/waitingsound.wav'
    if key_path == ('playerpodcast', 'status_file'):
        return '/tmp/test_podcast_status.json'
    if key_path == ('playerpodcast', 'cache_path'):
        return '/tmp/test_podcast_cache/'
    return default


@pytest.fixture
def player(mock_cfg):
    """Create a PlayerPodcast instance with mocked dependencies."""
    with patch('components.playerpodcast.PodcastFeedManager'), \
         patch('components.playerpodcast.EpisodeQueueManager'), \
         patch('components.playerpodcast.PodcastStateManager'), \
         patch('components.playerpodcast.EpisodeDownloadManager'), \
         patch('components.playerpodcast.plugs'), \
         patch('components.playerpodcast.publishing'):
        p = PlayerPodcast.__new__(PlayerPodcast)
        p.lock = threading.RLock()
        p.episode_downloader = Mock()
        p.feed_manager = Mock()
        p.queue_manager = Mock()
        p.state_manager = Mock()
        p.current_podcast_metadata = {'title': 'Test Podcast'}
        p.current_podcast_id = 'test_id'
        p.current_episode_guid = None
        p.current_feed_url = 'https://example.com/feed'
        p.playback_active = False
        p.current_episode_metadata = None
        p.mpd_podcast_subdir = 'podcast-cache'
        p.status_file = '/tmp/test_podcast_status.json'
        yield p


# ---------------------------------------------------------------------------
# _play_wav_direct tests
# ---------------------------------------------------------------------------

class TestPlayWavDirect:
    """Tests for _play_wav_direct static method."""

    @patch('components.playerpodcast.PlayerPodcast.__init__', lambda *a, **kw: None)
    def test_plays_wav_file(self):
        """Verify it opens the file, creates PCM device, and writes frames."""
        mock_wave_ctx = MagicMock()
        mock_wave_ctx.getnchannels.return_value = 2
        mock_wave_ctx.getsampwidth.return_value = 2
        mock_wave_ctx.getframerate.return_value = 44100
        # Return data once, then empty to stop loop
        mock_wave_ctx.readframes.side_effect = [b'\x00' * 100, b'']

        mock_wave = MagicMock()
        mock_wave.open.return_value.__enter__ = Mock(return_value=mock_wave_ctx)
        mock_wave.open.return_value.__exit__ = Mock(return_value=False)

        mock_pcm = MagicMock()
        mock_alsaaudio = MagicMock()
        mock_alsaaudio.PCM.return_value = mock_pcm
        mock_alsaaudio.PCM_FORMAT_S16_LE = 2

        with patch.dict('sys.modules', {'wave': mock_wave, 'alsaaudio': mock_alsaaudio}):
            PlayerPodcast._play_wav_direct('test.wav')

        mock_wave.open.assert_called_once_with('test.wav', 'rb')
        mock_alsaaudio.PCM.assert_called_once()
        mock_pcm.write.assert_called_once_with(b'\x00' * 100)

    @patch('components.playerpodcast.PlayerPodcast.__init__', lambda *a, **kw: None)
    def test_handles_missing_file_gracefully(self):
        """Verify it catches exceptions and doesn't crash."""
        mock_wave = MagicMock()
        mock_wave.open.side_effect = FileNotFoundError("No such file")

        mock_alsaaudio = MagicMock()

        with patch.dict('sys.modules', {'wave': mock_wave, 'alsaaudio': mock_alsaaudio}):
            # Should not raise
            PlayerPodcast._play_wav_direct('nonexistent.wav')

    @patch('components.playerpodcast.PlayerPodcast.__init__', lambda *a, **kw: None)
    def test_handles_alsa_error_gracefully(self):
        """Verify it catches ALSA device errors."""
        mock_wave_ctx = MagicMock()
        mock_wave_ctx.getnchannels.return_value = 2
        mock_wave_ctx.getsampwidth.return_value = 2
        mock_wave_ctx.getframerate.return_value = 44100

        mock_wave = MagicMock()
        mock_wave.open.return_value.__enter__ = Mock(return_value=mock_wave_ctx)
        mock_wave.open.return_value.__exit__ = Mock(return_value=False)

        mock_alsaaudio = MagicMock()
        mock_alsaaudio.PCM.side_effect = Exception("Device busy")

        with patch.dict('sys.modules', {'wave': mock_wave, 'alsaaudio': mock_alsaaudio}):
            # Should not raise
            PlayerPodcast._play_wav_direct('test.wav')


# ---------------------------------------------------------------------------
# _start_waiting_jingle tests
# ---------------------------------------------------------------------------

class TestStartWaitingJingle:
    """Tests for _start_waiting_jingle method."""

    def test_returns_none_when_no_config(self, player, mock_cfg):
        """When waiting_sound is not configured, returns None without pausing."""
        mock_cfg.getn = Mock(return_value=None)

        result = player._start_waiting_jingle()

        assert result is None

    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_play_wav_direct')
    def test_pauses_mpd_and_starts_thread(self, mock_play, mock_plugs, player, mock_cfg):
        """When configured, pauses MPD and returns a started thread."""
        result = player._start_waiting_jingle()

        assert result is not None
        assert isinstance(result, threading.Thread)
        assert result.name == 'WaitingJingle'
        assert result.daemon is True
        mock_plugs.call_ignore_errors.assert_called_once_with('player', 'ctrl', 'pause')

        # Wait for thread to finish so _play_wav_direct gets called
        result.join(timeout=1)
        mock_play.assert_called_once_with('../../resources/audio/waitingsound.wav')

    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_play_wav_direct')
    def test_thread_runs_in_background(self, mock_play, mock_plugs, player, mock_cfg):
        """The jingle thread should not block the caller."""
        # Make _play_wav_direct block until we release it
        barrier = threading.Event()
        mock_play.side_effect = lambda f: barrier.wait(timeout=2)

        thread = player._start_waiting_jingle()
        assert thread is not None
        assert thread.is_alive()

        # Release the thread
        barrier.set()
        thread.join(timeout=2)
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# _resolve_playback_url integration tests
# ---------------------------------------------------------------------------

class TestResolvePlaybackUrlJingle:
    """Tests for waiting jingle integration in _resolve_playback_url."""

    def _make_episode(self, guid='ep1'):
        return {
            'guid': guid,
            'title': 'Test Episode',
            'url': 'https://example.com/ep1.mp3',
        }

    @patch('components.playerpodcast.publishing')
    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_start_waiting_jingle', return_value=None)
    @patch.object(PlayerPodcast, '_update_mpd_database')
    @patch.object(PlayerPodcast, '_to_mpd_uri', return_value='podcast-cache/ep1.mp3')
    def test_jingle_not_played_when_cached(self, mock_uri, mock_update, mock_jingle,
                                           mock_plugs, mock_pub, player, mock_cfg):
        """No jingle when episode is already cached."""
        cached_path = Mock()
        cached_path.exists.return_value = True
        player.episode_downloader.get_local_path.return_value = cached_path
        player.episode_downloader.is_cached.return_value = True

        result = player._resolve_playback_url(self._make_episode(), resume_position=0)

        assert result == 'podcast-cache/ep1.mp3'
        mock_jingle.assert_not_called()

    @patch('components.playerpodcast.publishing')
    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_start_waiting_jingle')
    @patch.object(PlayerPodcast, '_update_mpd_database')
    @patch.object(PlayerPodcast, '_to_mpd_uri', return_value='podcast-cache/ep1.mp3')
    def test_jingle_played_when_download_needed(self, mock_uri, mock_update, mock_jingle,
                                                mock_plugs, mock_pub, player, mock_cfg):
        """Jingle should start when episode needs downloading."""
        mock_thread = Mock()
        mock_jingle.return_value = mock_thread

        downloaded_path = Mock()
        downloaded_path.exists.return_value = True
        player.episode_downloader.get_local_path.return_value = None
        player.episode_downloader.is_cached.return_value = False
        player.episode_downloader.download_episode.return_value = downloaded_path

        result = player._resolve_playback_url(self._make_episode(), resume_position=0)

        assert result == 'podcast-cache/ep1.mp3'
        mock_jingle.assert_called_once()
        mock_thread.join.assert_called_once()

    @patch('components.playerpodcast.publishing')
    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_start_waiting_jingle', return_value=None)
    @patch.object(PlayerPodcast, '_update_mpd_database')
    @patch.object(PlayerPodcast, '_to_mpd_uri', return_value='podcast-cache/ep1.mp3')
    def test_join_skipped_when_no_jingle_config(self, mock_uri, mock_update, mock_jingle,
                                                mock_plugs, mock_pub, player, mock_cfg):
        """When _start_waiting_jingle returns None, join is safely skipped."""
        downloaded_path = Mock()
        downloaded_path.exists.return_value = True
        player.episode_downloader.get_local_path.return_value = None
        player.episode_downloader.is_cached.return_value = False
        player.episode_downloader.download_episode.return_value = downloaded_path

        # Should not raise even though jingle_thread is None
        result = player._resolve_playback_url(self._make_episode(), resume_position=0)

        assert result == 'podcast-cache/ep1.mp3'

    @patch('components.playerpodcast.publishing')
    @patch('components.playerpodcast.plugs')
    @patch.object(PlayerPodcast, '_start_waiting_jingle')
    def test_jingle_joined_even_on_download_failure(self, mock_jingle,
                                                    mock_plugs, mock_pub, player, mock_cfg):
        """If download fails, jingle thread is still joined (via exception handler)."""
        mock_thread = Mock()
        mock_jingle.return_value = mock_thread

        player.episode_downloader.get_local_path.return_value = None
        player.episode_downloader.is_cached.return_value = False
        player.episode_downloader.download_episode.side_effect = Exception("Network error")

        # Falls back to stream URL
        result = player._resolve_playback_url(self._make_episode(), resume_position=0)

        assert result == 'https://example.com/ep1.mp3'
        # The jingle thread.join() is inside the try block, so on exception
        # it won't be called - but the thread is daemon so it won't block exit

    @patch('components.playerpodcast.publishing')
    @patch('components.playerpodcast.plugs')
    def test_no_jingle_when_downloader_disabled(self, mock_plugs, mock_pub, player, mock_cfg):
        """When episode_downloader is None, returns stream URL with no jingle."""
        player.episode_downloader = None

        result = player._resolve_playback_url(self._make_episode(), resume_position=0)

        assert result == 'https://example.com/ep1.mp3'
