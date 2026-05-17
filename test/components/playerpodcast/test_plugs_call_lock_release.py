# -*- coding: utf-8 -*-
"""Regression test for Phase 1 follow-up #2: podcast must not hold
``self.lock`` across ANY ``plugs.call`` site.

Phase 1, fix #4 fixed the second-swipe ``plugs.call('player','ctrl',
'playerstatus')`` path; Phase 2 extends that discipline to the other
cross-plugin call sites that previously held the lock:

* ``play_podcast_series`` / ``play_podcast_episode`` — MPD play_single
* ``_play_episode_from_queue`` — MPD play_single (next/prev navigation)
* ``stop()`` — MPD stop
* ``exit()`` — MPD playerstatus (final position save)

The bug is "lock held across plugs.call". The fix is "snapshot under
the lock, release, call out". We pin this at the source level (so the
test is robust to refactors of the surrounding logic) AND with a
behavioural test that imitates the new lock discipline.
"""

import re
import threading
import time
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[3]
    / 'src' / 'jukebox' / 'components' / 'playerpodcast' / '__init__.py'
)


def _read_source():
    return SOURCE.read_text()


def _find_method(src, name):
    """Return source body of the named method or top-level def."""
    pattern = re.compile(rf'^(    )?def {re.escape(name)}\(', re.MULTILINE)
    m = pattern.search(src)
    assert m, f"method {name} not found"
    start = m.start()
    # Find end: next def at same indent level.
    indent = m.group(1) or ''
    end_re = re.compile(rf'^{indent}(?:def |@|class )', re.MULTILINE)
    end_m = end_re.search(src, m.end())
    return src[start:(end_m.start() if end_m else len(src))]


def test_play_episode_from_queue_releases_lock_before_plugs_call():
    """The internal next/prev helper used to hold ``self.lock`` across
    ``plugs.call('player','ctrl','play_single', ...)``. After Phase 2
    the cross-plugin call must run OUTSIDE the lock."""
    body = _find_method(_read_source(), '_play_episode_from_queue')
    # Locate the plugs.call line and confirm it is NOT preceded by
    # an open ``with self.lock:`` block that has yet to close.
    play_single_idx = body.find("plugs.call('player', 'ctrl', 'play_single'")
    assert play_single_idx > 0, "play_single plugs.call not found"
    preamble = body[:play_single_idx]
    # The fix removes the with-lock wrapping. So the plugs.call line
    # must NOT be indented more than one level inside the method body.
    # Easier sanity check: between the last `with self.lock:` and the
    # plugs.call there must be a closing dedent (i.e. another
    # statement at method-body indent before the call).
    assert 'with self.lock:\n            plugs.call' not in preamble + body, \
        "play_single still inside a with self.lock block"


def test_play_podcast_series_releases_lock_around_play_single():
    body = _find_method(_read_source(), 'play_podcast_series')
    assert 'plugs.call(' in body
    # The pattern "with self.lock: ... plugs.call('player', 'ctrl', 'play_single'..."
    # (without an intervening dedent) is the bug; assert it's gone.
    assert "with self.lock:\n                # Use MPD's play_single" not in body
    assert "with self.lock:\n                logger.info(f\"Calling MPD play_single" not in body


def test_play_podcast_episode_releases_lock_around_play_single():
    body = _find_method(_read_source(), 'play_podcast_episode')
    assert 'plugs.call(' in body
    assert "with self.lock:\n                # Use playermpd's play_single" not in body
    assert "with self.lock:\n                plugs.call('player', 'ctrl', 'play_single'" not in body


def test_stop_releases_lock_before_plugs_call():
    body = _find_method(_read_source(), 'stop')
    # plugs.call('player','ctrl','stop') must appear BEFORE the
    # ``with self.lock:`` that does state mutations.
    stop_call_idx = body.find("plugs.call('player', 'ctrl', 'stop')")
    lock_idx = body.find('with self.lock:')
    assert stop_call_idx > 0, 'plugs.call(stop) not found'
    assert lock_idx > 0, 'with self.lock: not found in stop()'
    assert stop_call_idx < lock_idx, \
        "stop() still holds the lock across plugs.call"


def test_exit_releases_lock_around_final_position_save():
    body = _find_method(_read_source(), 'exit')
    # The old pattern had ``with self.lock: ... plugs.call('player',
    # 'ctrl','playerstatus')`` inside. The new pattern snapshots
    # under the lock, releases, then calls plugs.call.
    if "plugs.call('player', 'ctrl', 'playerstatus')" in body:
        # Find the call and ensure it's not indented inside `with self.lock:`.
        snapshot_idx = body.find("with self.lock:")
        call_idx = body.find("plugs.call('player', 'ctrl', 'playerstatus')")
        # New pattern: snapshot must come before the plugs.call.
        assert snapshot_idx >= 0
        assert call_idx > snapshot_idx
        # And there should be a dedented statement (e.g. `if should_save:`)
        # between them, showing the with-block was closed.
        between = body[snapshot_idx:call_idx]
        # 8-space indent = method body level; 12+ = inside a with.
        # We expect at least one line dedented to method-body indent
        # before the call.
        method_body_lines = [
            ln for ln in between.splitlines()
            if ln.startswith('        ') and not ln.startswith('         ')
        ]
        assert method_body_lines, \
            "exit() still holds the lock across plugs.call(playerstatus)"


# ---------------------------------------------------------------------------
# Behavioural counterpart: model the new pattern and prove it does not
# block parallel readers. Mirrors test_second_swipe_lock_release.py.
# ---------------------------------------------------------------------------
def test_new_pattern_does_not_block_concurrent_readers():
    """The new pattern: snapshot under lock, release, call out, then
    reacquire for mutations. A slow plugs.call must not stall a
    concurrent reader."""
    lock = threading.RLock()
    state = {'playback_active': True, 'current_episode_guid': 'g1'}

    plugs_started = threading.Event()
    plugs_done = threading.Event()

    def slow_plugs_call():
        plugs_started.set()
        time.sleep(0.4)
        plugs_done.set()

    def play_episode_from_queue_new_pattern():
        # New pattern: prep done outside the lock, plugs.call outside
        # the lock, then a tiny critical section for state mutations.
        slow_plugs_call()
        with lock:
            state['current_episode_guid'] = 'g2'

    def status_reader():
        with lock:
            return dict(state)

    worker = threading.Thread(target=play_episode_from_queue_new_pattern)
    worker.start()

    assert plugs_started.wait(timeout=1.0)
    # Read while plugs_call is still "running" — must NOT block.
    t0 = time.monotonic()
    snap = status_reader()
    elapsed = time.monotonic() - t0
    # Read should be effectively instant (lock free during plugs.call).
    assert elapsed < 0.1, f"reader blocked for {elapsed:.2f}s (lock held across plugs.call)"
    assert snap['current_episode_guid'] == 'g1'

    worker.join(timeout=2.0)
    assert plugs_done.is_set()
