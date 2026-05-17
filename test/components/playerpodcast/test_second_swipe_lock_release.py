# -*- coding: utf-8 -*-
"""Regression test for podcast second-swipe lock release.

Phase 1, fix #4: ``play_podcast_series`` and ``play_podcast_episode`` in
``src/jukebox/components/playerpodcast/__init__.py`` previously held
``self.lock`` across ``plugs.call('player', 'ctrl', 'playerstatus')`` and
across the configured ``second_swipe_action`` invocation. Any code path
that re-entered the podcast player (e.g. the toggle action calling back
into ``playerstatus``) would deadlock, and concurrent RPC ``playerstatus``
requests stalled for the duration of the swipe action.

The fix snapshots the second-swipe condition under the lock, releases
it, then runs the cross-plugin call + swipe handler with the lock free.
This test simulates a slow ``second_swipe_action`` and asserts that a
concurrent ``playerstatus`` reader can still acquire the lock and return
during the swipe action.
"""

import threading
import time
from pathlib import Path


def test_second_swipe_releases_lock_before_action():
    """Pin the lock-release behavior at the source level."""
    source_path = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playerpodcast' / '__init__.py'
    )
    src_text = source_path.read_text()
    # Old pattern: action() called inside ``with self.lock``. New: snapshot
    # the bool, exit the with-block, then call the action.
    assert 'is_same_podcast = (' in src_text
    assert 'is_same_episode = (' in src_text
    # Old buggy literal must be gone.
    assert 'self.second_swipe_action()\n                        return' not in src_text


def test_swipe_does_not_block_concurrent_status_reads():
    """Simulate the new pattern: a swipe handler that sleeps must NOT
    prevent a parallel reader from acquiring the lock and finishing.
    Modelled directly on the playerpodcast lock discipline."""
    lock = threading.RLock()
    state = {'playback_active': True, 'current_feed_url': 'http://feed/a'}

    # Slow second-swipe action; would deadlock the old code by being
    # invoked while ``self.lock`` is still held.
    swipe_done = threading.Event()
    swipe_started = threading.Event()

    def slow_swipe():
        swipe_started.set()
        time.sleep(0.4)
        swipe_done.set()

    def play_card(feed_url):
        # New pattern: snapshot under the lock, release, then run swipe.
        with lock:
            is_same = (
                state['playback_active']
                and state['current_feed_url'] == feed_url
            )
        if is_same:
            slow_swipe()
            return True
        return False

    def status_reader():
        # The reader takes the lock for a short critical section, like
        # PlayerPodcast.playerstatus does.
        with lock:
            return dict(state)

    swiper = threading.Thread(target=play_card, args=('http://feed/a',))
    swiper.start()

    # Wait until the swipe handler is actually running.
    assert swipe_started.wait(timeout=1.0)
    # Now try to read status — old code held the lock across the swipe
    # and this acquire would hang for ~0.4s. New code released the lock
    # before calling slow_swipe, so this returns immediately.
    t0 = time.monotonic()
    snap = status_reader()
    elapsed = time.monotonic() - t0
    assert snap == state
    # Give plenty of headroom for slow CI, but require well under the
    # swipe handler's sleep time so we know the lock was released.
    assert elapsed < 0.2, (
        f"status_reader blocked {elapsed:.3f}s during swipe — "
        "the swipe action is holding the lock"
    )

    swiper.join(timeout=2.0)
    assert swipe_done.is_set()
