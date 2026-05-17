# -*- coding: utf-8 -*-
"""Regression tests for podcast second-swipe lock release (Phase 1 fix #4).

Phase 1 patched ``play_podcast_series`` and ``play_podcast_episode`` so
they snapshot the second-swipe condition under ``self.lock``, *release*
the lock, then run the cross-plugin ``plugs.call('player','ctrl',
'playerstatus')`` and the configured ``second_swipe_action``. Holding
the lock across either of those would deadlock any code path that
re-enters the podcast player (e.g. the toggle handler calling
``playerstatus`` back into the podcast plugin).

Phase 3b replaced the pre-existing tests in this file. The Phase 1
suite used a source-text grep for the literal ``is_same_podcast = (``
plus a parallel-implementation harness with a fresh ``threading.RLock``
- neither exercised ``PlayerPodcast``. Phase 3a documented this as
"test theatre" and Phase 3b owns the cleanup.

The new tests drive the real ``PlayerPodcast.play_podcast_series``
through a mocked ``plugs`` module so we can interpose between the
second-swipe ``playerstatus`` call and the configured handler. The
interposer asserts ``self.lock`` is acquirable *during* the
cross-plugin call - the lock-release invariant in production code.
"""

import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest


# Mock external dependencies for component import (conftest already
# pre-mocks the jukebox framework but not feedparser/requests).
sys.modules.setdefault('feedparser', MagicMock())
sys.modules.setdefault('requests', MagicMock())
# Provide a stub ``components.player`` if not already present (real
# module needs MPD config). Do NOT shadow ``components.player.coordinator``
# - tests in test/components/player/test_coordinator.py need the real
# module, and sys.modules entries persist across tests.
if 'components.player' not in sys.modules:
    sys.modules['components.player'] = MagicMock()

from components.playerpodcast import PlayerPodcast  # noqa: E402


@pytest.fixture
def podcast_player():
    """Build a ``PlayerPodcast`` with only the attributes the
    play_podcast_series happy-path needs.

    We bypass ``__init__`` to skip filesystem / cfg setup and assign
    the minimum attribute surface so the second-swipe + queue-build
    code path executes."""
    p = PlayerPodcast.__new__(PlayerPodcast)
    p.lock = threading.RLock()
    p.feed_manager = MagicMock()
    p.queue_manager = MagicMock()
    p.state_manager = MagicMock()
    p.episode_downloader = None
    p.coverart_cache_path = None
    p.mpd_podcast_subdir = 'podcast-cache'
    # Establish a 'currently playing' state so the second-swipe path
    # actually triggers.
    p.current_podcast_id = 'pod1'
    p.current_episode_guid = 'ep1'
    p.current_feed_url = 'http://feed/a'
    p.playback_active = True
    p.current_episode_metadata = {'title': 'Ep 1', 'url': 'http://ep1'}
    p.current_podcast_metadata = {'title': 'Pod A', 'author': '', 'image_url': ''}

    # second_swipe_action will be replaced per test.
    p.second_swipe_action = MagicMock()
    return p


# ---------------------------------------------------------------------------
# Behavioural test 1: lock released around the second-swipe playerstatus RPC
# ---------------------------------------------------------------------------
def test_lock_released_during_playerstatus_rpc(podcast_player):
    """The cross-plugin ``playerstatus`` call from inside
    ``play_podcast_series`` must NOT hold ``self.lock``.

    We interpose on the mocked plugs.call to attempt a non-blocking
    lock acquire from a worker thread. The acquire must succeed -
    proving the calling thread released the lock before the RPC.

    Reversion check: if the production code is reverted to the
    pre-Phase-1 ``with self.lock:`` wrapping plugs.call, the worker's
    ``acquire(blocking=False)`` returns False and this test fails.
    """
    lock_was_acquirable_during_rpc = []

    def fake_plugs_call(*args, **kwargs):
        # If this looks like the playerstatus query for second-swipe,
        # probe the lock from a worker thread to ensure it's not held
        # by the calling thread.
        if args == ('player', 'ctrl', 'playerstatus'):
            probe_result = []

            def probe():
                acquired = podcast_player.lock.acquire(blocking=False)
                probe_result.append(acquired)
                if acquired:
                    podcast_player.lock.release()

            t = threading.Thread(target=probe)
            t.start()
            t.join(timeout=1.0)
            lock_was_acquirable_during_rpc.append(
                bool(probe_result) and probe_result[0]
            )
            # Return a 'playing' status to drive the second-swipe path.
            return {'state': 'play'}
        # Any other plugs.call from this code path (none expected
        # because the second-swipe handler is a MagicMock) - just
        # return empty.
        return {}

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = fake_plugs_call
        podcast_player.play_podcast_series('http://feed/a')

    assert lock_was_acquirable_during_rpc, (
        "playerstatus RPC was never called - the test setup is wrong"
    )
    assert all(lock_was_acquirable_during_rpc), (
        "self.lock was held across plugs.call('player','ctrl','playerstatus') "
        "- Phase 1 lock-release invariant is broken"
    )
    # And the second_swipe_action *was* invoked, confirming the path
    # exercised was the second-swipe path (not fresh-start).
    podcast_player.second_swipe_action.assert_called_once()


# ---------------------------------------------------------------------------
# Behavioural test 2: lock released BEFORE second_swipe_action
# ---------------------------------------------------------------------------
def test_lock_released_around_second_swipe_action(podcast_player):
    """The ``second_swipe_action`` handler must run with ``self.lock``
    free. The handler typically calls back into ``plugs.call`` (toggle
    -> player.ctrl.toggle -> can recurse into the podcast plugin),
    which would deadlock if the lock were still held.

    Reversion check: if production code reverts to the pre-Phase-1
    pattern where second_swipe_action ran inside ``with self.lock:``,
    the probe inside the handler returns False and this test fails.
    """
    probe_result = []

    def slow_swipe_action():
        # While the handler is running, probe the lock from another
        # thread. With Phase 1's fix the lock is free; pre-Phase-1
        # it was held by the calling thread.
        acquired_in_worker = []

        def worker():
            acquired_in_worker.append(
                podcast_player.lock.acquire(blocking=False)
            )
            if acquired_in_worker[-1]:
                podcast_player.lock.release()

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=1.0)
        probe_result.append(
            bool(acquired_in_worker) and acquired_in_worker[0]
        )
        # Simulate non-trivial work so a held-lock bug would show up
        # in real call sites too.
        time.sleep(0.05)

    podcast_player.second_swipe_action = slow_swipe_action

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = MagicMock(return_value={'state': 'play'})
        podcast_player.play_podcast_series('http://feed/a')

    assert probe_result, "second_swipe_action was never invoked"
    assert probe_result[0], (
        "self.lock was held across second_swipe_action - Phase 1 fix "
        "for second-swipe deadlock has regressed"
    )


# ---------------------------------------------------------------------------
# Behavioural test 3: same-feed-but-MPD-stopped path clears stale flag
# ---------------------------------------------------------------------------
def test_stale_flag_cleared_when_mpd_stopped(podcast_player):
    """If ``playback_active`` is True but MPD reports ``state == 'stop'``,
    Phase 1 fix #4 requires the stale flag to be cleared and the swipe
    to be treated as a fresh start.

    Reversion check: revert ``decide_second_swipe`` to ignore
    ``mpd_state`` (or revert ``play_podcast_series`` to skip the
    stop-state check) and this test will see ``second_swipe_action``
    invoked instead of the flag clear.
    """
    # Feed manager returns None -> fresh-start path aborts cleanly.
    podcast_player.feed_manager.fetch_feed.return_value = None

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = MagicMock(return_value={'state': 'stop'})
        podcast_player.play_podcast_series('http://feed/a')

    # Stale flag was cleared.
    assert podcast_player.playback_active is False
    # second_swipe_action NOT invoked (it was a fresh-start, not a tap).
    podcast_player.second_swipe_action.assert_not_called()
    # Feed manager was reached - we did fall through to the fresh-start
    # code path.
    podcast_player.feed_manager.fetch_feed.assert_called_once_with('http://feed/a')
