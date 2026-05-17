# -*- coding: utf-8 -*-
"""Behavioural regression tests for Phase 2's podcast lock-release sweep.

Phase 2 extended the Phase 1 lock-discipline ("snapshot under
self.lock, release, then call out across plugs") to every
``plugs.call`` site in the podcast player:

* ``play_podcast_series`` / ``play_podcast_episode`` - MPD play_single
* ``_play_episode_from_queue`` - MPD play_single (next/prev navigation)
* ``stop()`` - MPD stop
* ``exit()`` - MPD playerstatus (final position save)

The original test file (also from Phase 2) used 5 source-text greps
and 1 behavioural test against a fresh ``threading.RLock`` rather
than ``PlayerPodcast``. Phase 3b owns the cleanup (Phase 2 FU#4).

Each test below drives the real ``PlayerPodcast`` method via a mocked
``plugs`` module that probes ``self.lock`` from a worker thread at
the moment of the cross-plugin call. The probe acquires
non-blockingly: success means the calling thread released the lock,
failure means it didn't.

Reversion check: re-introducing ``with self.lock:`` around any
covered plugs.call site causes the corresponding probe to return
False - test fails.
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


# Mock optional native deps that the podcast component imports
# transitively (feedparser via feed_manager, requests via downloader).
sys.modules.setdefault('feedparser', MagicMock())
sys.modules.setdefault('requests', MagicMock())
sys.modules.setdefault('components.player', MagicMock())
sys.modules.setdefault(
    'components.player.coordinator',
    MagicMock(get_coordinator=MagicMock()),
)

from components.playerpodcast import PlayerPodcast  # noqa: E402


@pytest.fixture
def podcast_player():
    """Minimal PlayerPodcast for lock-release tests.

    Bypasses ``__init__`` (filesystem + cfg setup) and assigns only
    the attributes the four code paths under test touch.
    """
    p = PlayerPodcast.__new__(PlayerPodcast)
    p.lock = threading.RLock()
    p.feed_manager = MagicMock()
    p.queue_manager = MagicMock()
    p.state_manager = MagicMock()
    p.episode_downloader = None
    p.mpd_podcast_subdir = 'podcast-cache'
    # Background thread bookkeeping (used by exit()).
    p.position_thread = MagicMock()
    p.position_thread.is_alive.return_value = False
    p.position_thread_stop = threading.Event()
    # Fresh, idle-ish state.
    p.current_podcast_id = None
    p.current_episode_guid = None
    p.current_feed_url = None
    p.playback_active = False
    p.current_episode_metadata = None
    p.current_podcast_metadata = None
    p.second_swipe_action = MagicMock()
    return p


def _probing_plugs_call(podcast_player, target_args, probe_results):
    """Build a fake ``plugs.call`` that probes the lock when called
    with ``target_args`` and records whether the probe succeeded."""
    def fake_call(*args, **kwargs):
        if args == target_args:
            probe = []

            def worker():
                acquired = podcast_player.lock.acquire(blocking=False)
                probe.append(acquired)
                if acquired:
                    podcast_player.lock.release()

            t = threading.Thread(target=worker)
            t.start()
            t.join(timeout=1.0)
            probe_results.append(bool(probe) and probe[0])
        # All other cross-plugin calls return a benign default.
        if args[-1:] == ('playerstatus',):
            return {'state': 'play', 'elapsed': '5', 'duration': '100'}
        return {}
    return fake_call


# ---------------------------------------------------------------------------
# play_podcast_series - play_single must NOT hold self.lock
# ---------------------------------------------------------------------------
def test_play_podcast_series_releases_lock_around_play_single(podcast_player):
    """Drive ``play_podcast_series`` happy path and assert ``self.lock``
    is free at the moment of ``plugs.call('player','ctrl','play_single',
    ...)``.

    Reversion check: wrap the play_single call in ``with self.lock:``
    in production and the probe returns False - test fails.
    """
    # Feed manager returns a one-episode feed.
    podcast_player.feed_manager.fetch_feed.return_value = {
        'podcast_id': 'pod1',
        'title': 'P', 'author': '', 'image_url': '',
        'episodes': [{'guid': 'ep1', 'title': 'E', 'url': 'http://ep1'}],
    }
    podcast_player.queue_manager.get_playable_queue.return_value = (
        [{'guid': 'ep1', 'title': 'E', 'url': 'http://ep1'}], False,
    )
    podcast_player.queue_manager.find_resume_episode.return_value = None
    podcast_player.state_manager.get_resume_position.return_value = 0

    probe_results = []
    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = _probing_plugs_call(
            podcast_player,
            ('player', 'ctrl', 'play_single'),
            probe_results,
        )
        # _activate_podcast goes through coordinator (mocked at module
        # import) - we don't probe it here, just let it pass.
        with patch.object(podcast_player, '_activate_podcast'):
            podcast_player.play_podcast_series('http://feed/a')

    assert probe_results, "play_single RPC was never invoked"
    assert all(probe_results), (
        "self.lock was held across plugs.call(play_single) in "
        "play_podcast_series - Phase 2 lock-release regression"
    )


# ---------------------------------------------------------------------------
# play_podcast_episode - play_single must NOT hold self.lock
# ---------------------------------------------------------------------------
def test_play_podcast_episode_releases_lock_around_play_single(podcast_player):
    """Same invariant as ``test_play_podcast_series_...`` but for the
    specific-episode entry point."""
    podcast_player.feed_manager.fetch_feed.return_value = {
        'podcast_id': 'pod1',
        'title': 'P', 'author': '', 'image_url': '',
        'episodes': [{'guid': 'ep1', 'title': 'E', 'url': 'http://ep1'}],
    }
    podcast_player.queue_manager.get_episode_by_guid.return_value = {
        'guid': 'ep1', 'title': 'E', 'url': 'http://ep1',
    }
    podcast_player.state_manager.get_resume_position.return_value = 0

    probe_results = []
    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = _probing_plugs_call(
            podcast_player,
            ('player', 'ctrl', 'play_single'),
            probe_results,
        )
        with patch.object(podcast_player, '_activate_podcast'):
            podcast_player.play_podcast_episode('http://feed/a', 'ep1')

    assert probe_results, "play_single RPC was never invoked"
    assert all(probe_results), (
        "self.lock was held across plugs.call(play_single) in "
        "play_podcast_episode - Phase 2 lock-release regression"
    )


# ---------------------------------------------------------------------------
# _play_episode_from_queue - next/prev navigation path
# ---------------------------------------------------------------------------
def test_play_episode_from_queue_releases_lock_around_play_single(podcast_player):
    """``_play_episode_from_queue`` is the shared next/prev helper.
    It must release ``self.lock`` around ``plugs.call(play_single)``
    too - Phase 2 fixed this one alongside the entry-point methods."""
    episode = {'guid': 'ep2', 'title': 'E2', 'url': 'http://ep2'}

    probe_results = []
    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = _probing_plugs_call(
            podcast_player,
            ('player', 'ctrl', 'play_single'),
            probe_results,
        )
        podcast_player._play_episode_from_queue(episode)

    assert probe_results, "play_single RPC was never invoked"
    assert all(probe_results), (
        "self.lock was held across plugs.call(play_single) in "
        "_play_episode_from_queue - Phase 2 lock-release regression"
    )


# ---------------------------------------------------------------------------
# stop() - plugs.call(stop) must NOT hold self.lock
# ---------------------------------------------------------------------------
def test_stop_releases_lock_around_plugs_call(podcast_player):
    """``stop()`` calls ``plugs.call('player','ctrl','stop')`` and then
    mutates state under the lock. The stop call must run with the
    lock free."""
    podcast_player.playback_active = True

    probe_results = []
    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = _probing_plugs_call(
            podcast_player,
            ('player', 'ctrl', 'stop'),
            probe_results,
        )
        podcast_player.stop()

    assert probe_results, "stop RPC was never invoked"
    assert all(probe_results), (
        "self.lock was held across plugs.call(stop) in stop() - "
        "Phase 2 lock-release regression"
    )
    # And the state mutation happened (post-call critical section).
    assert podcast_player.playback_active is False


# ---------------------------------------------------------------------------
# exit() - final position save (playerstatus) must NOT hold self.lock
# ---------------------------------------------------------------------------
def test_exit_releases_lock_around_final_playerstatus(podcast_player):
    """``exit()`` snapshots state under the lock, releases it, then
    calls ``plugs.call('player','ctrl','playerstatus')`` for the final
    position save. The playerstatus call must run with the lock free.
    """
    # Force the "should_save" branch.
    podcast_player.playback_active = True
    podcast_player.current_episode_guid = 'ep1'
    podcast_player.episode_downloader = None  # skip save_metadata path

    probe_results = []
    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = _probing_plugs_call(
            podcast_player,
            ('player', 'ctrl', 'playerstatus'),
            probe_results,
        )
        podcast_player.exit()

    assert probe_results, "playerstatus RPC was never invoked in exit()"
    assert all(probe_results), (
        "self.lock was held across plugs.call(playerstatus) in exit() "
        "- Phase 2 lock-release regression"
    )
    # And state_manager.update_episode_position was driven with the
    # snapshotted guid.
    podcast_player.state_manager.update_episode_position.assert_called_once()
    call_args = podcast_player.state_manager.update_episode_position.call_args[0]
    assert call_args[0] == 'ep1'


# ---------------------------------------------------------------------------
# Concurrent-reader: real podcast object must not block parallel readers
# ---------------------------------------------------------------------------
def test_concurrent_status_read_does_not_block_during_play_single(podcast_player):
    """While ``play_podcast_series`` is in its ``plugs.call(play_single)``
    window, another thread can acquire and release ``self.lock`` (as
    the status RPC does) without blocking. This is the test that
    pre-Phase-2 would have hung."""
    podcast_player.feed_manager.fetch_feed.return_value = {
        'podcast_id': 'pod1',
        'title': 'P', 'author': '', 'image_url': '',
        'episodes': [{'guid': 'ep1', 'title': 'E', 'url': 'http://ep1'}],
    }
    podcast_player.queue_manager.get_playable_queue.return_value = (
        [{'guid': 'ep1', 'title': 'E', 'url': 'http://ep1'}], False,
    )
    podcast_player.queue_manager.find_resume_episode.return_value = None
    podcast_player.state_manager.get_resume_position.return_value = 0

    in_play_single = threading.Event()
    finished_probe = threading.Event()

    def slow_play_single_call(*args, **kwargs):
        if args == ('player', 'ctrl', 'play_single'):
            in_play_single.set()
            # Wait until the reader thread has had a chance to probe.
            finished_probe.wait(timeout=1.0)
            return None
        return {}

    reader_acquired = []

    def reader():
        in_play_single.wait(timeout=1.0)
        acquired = podcast_player.lock.acquire(blocking=False)
        reader_acquired.append(acquired)
        if acquired:
            podcast_player.lock.release()
        finished_probe.set()

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = slow_play_single_call
        with patch.object(podcast_player, '_activate_podcast'):
            reader_thread = threading.Thread(target=reader)
            reader_thread.start()
            podcast_player.play_podcast_series('http://feed/a')
            reader_thread.join(timeout=2.0)

    assert reader_acquired and reader_acquired[0], (
        "Concurrent reader could not acquire self.lock during "
        "play_single - lock-release invariant violated"
    )
