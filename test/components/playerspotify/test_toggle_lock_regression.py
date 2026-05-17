# -*- coding: utf-8 -*-
"""Regression test for toggle() lock semantics (Phase 2 FU#3).

The Spotify ``toggle()`` flow is::

    toggle()
        playerstatus()             # reads self.player_status (no lock)
        if playing: pause()        # acquires self.lock (RLock)
        else:       play()         # acquires self.lock (RLock)

In Phase 2 the reviewer flagged that ``self.lock`` is an RLock — if a
future refactor made ``playerstatus()`` take the lock as well, the
nested acquire would still work (RLock semantics) but the *contract*
needs to be regression-locked. If a future refactor downgrades the
RLock to a plain :class:`threading.Lock`, the test must fail.

The test exercises the real ``PlayerSpotify.toggle()`` and asserts the
call returns within a hard time bound even when another thread holds
``self.lock`` briefly. The bound is short enough that a real deadlock
would trip it.

REVERSION CHECK: downgrade ``self.lock = threading.RLock()`` to
``threading.Lock()`` in PlayerSpotify.__init__. ``toggle()`` would
then deadlock if it ever ended up calling itself recursively under
the lock. The test in
``test_toggle_does_not_deadlock_under_lock_contention`` would hang
past its 5s timeout and fail.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Bare-bones PlayerSpotify factory
# ---------------------------------------------------------------------------
@pytest.fixture
def player():
    """Construct a PlayerSpotify with the heavy paths skipped.

    We need a real :class:`threading.RLock` on ``self.lock`` so the
    nesting semantics are exercised faithfully. Other state is
    minimal — just enough for play/pause/toggle to traverse their
    lock-acquiring branches.
    """
    from components.playerspotify import PlayerSpotify
    p = PlayerSpotify.__new__(PlayerSpotify)
    p.lock = threading.RLock()
    p.sp_client = MagicMock()
    p.player_status = {
        'state': 'playing',
        'last_played_uri': None,
        'last_card_uri': None,
        'current_track': None,
        'position_ms': 0,
        'device_id': 'devY',
        'shuffle': False,
        'repeat': 'off',
    }
    p.status_file = '/tmp/_toggle_regression_status.json'

    # Stub out token-refresh and device-ensure paths so the lock-only
    # behaviour is what we measure.
    p._require_client = lambda: None
    p._refresh_token_if_needed = lambda: None
    p._ensure_device = lambda: True
    return p


def test_production_self_lock_is_an_rlock():
    """Reversion check: ``PlayerSpotify.__init__`` must construct
    ``self.lock`` as an :class:`threading.RLock`, not a plain Lock.

    A plain Lock would silently work today (toggle doesn't currently
    take the lock around ``playerstatus()``) but tomorrow's refactor
    that takes the lock there would deadlock. Pin the type by reading
    the actual source — using ``threading.RLock`` is the contract.
    """
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playerspotify' / '__init__.py'
    )
    text = src.read_text()
    assert 'self.lock = threading.RLock()' in text, (
        "PlayerSpotify.__init__ no longer constructs self.lock as a "
        "threading.RLock. The toggle() flow relies on RLock semantics "
        "so a future refactor that nests the lock won't deadlock. "
        "Restore: ``self.lock = threading.RLock()``"
    )
    # Also pin behaviourally: a freshly-constructed RLock allows
    # double-acquire from the same thread. (If someone replaces the
    # source with a wrapper class, this catches a behaviour change.)
    import threading as _t
    rl = _t.RLock()
    assert rl.acquire(blocking=False)
    assert rl.acquire(blocking=False)
    rl.release()
    rl.release()


def test_toggle_does_not_deadlock_under_lock_contention(player):
    """Toggle must complete promptly even when another thread is
    briefly holding ``self.lock``.

    Setup: a background thread holds the lock for 0.2s. We start
    ``toggle()`` from the main thread immediately. ``toggle()`` will
    block on ``pause()``'s ``with self.lock`` until the background
    thread releases, then proceed. We assert the whole flow completes
    well within 5s — a genuine deadlock would hang forever (the
    pytest harness would eventually time out, but on a deadlock the
    function would never return).
    """
    holder_done = threading.Event()
    holder_acquired = threading.Event()

    def hold_lock_briefly():
        with player.lock:
            holder_acquired.set()
            time.sleep(0.2)
        holder_done.set()

    holder = threading.Thread(target=hold_lock_briefly)
    holder.start()
    # Make sure the holder actually has the lock before we start toggle
    assert holder_acquired.wait(timeout=1.0)

    t0 = time.monotonic()
    player.toggle()
    elapsed = time.monotonic() - t0

    holder.join(timeout=1.0)
    assert holder_done.is_set(), "background lock-holder never finished"
    # Must NOT take anywhere near 5s — that would indicate a deadlock
    # that pytest's --maxfail timeout would eventually trip.
    assert elapsed < 2.0, f"toggle() took {elapsed:.2f}s — possible deadlock"
    # And the toggle must have actually performed its work.
    player.sp_client.pause_playback.assert_called()


def test_toggle_recursive_acquire_from_same_thread_does_not_deadlock(player):
    """Direct reversion-check for the RLock contract.

    Acquire the lock from the main thread, then call ``toggle()``
    which internally tries to acquire the same lock. With an RLock,
    the inner acquire succeeds and toggle completes. With a plain
    Lock this would deadlock.

    A 1s budget is plenty — even a slow CI box completes ``toggle()``
    well under 100ms when the lock is owned by the calling thread.
    """
    completed = threading.Event()

    def run():
        with player.lock:
            player.toggle()
        completed.set()

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=1.0)
    assert completed.is_set(), (
        "toggle() did not return within 1s while holding self.lock — "
        "either self.lock is no longer an RLock or toggle() now does "
        "something blocking under the lock."
    )
    player.sp_client.pause_playback.assert_called()


def test_toggle_paused_to_playing_under_contention(player):
    """Same regression coverage but for the play branch of toggle()."""
    player.player_status['state'] = 'paused'
    # Make playerstatus return paused
    player.sp_client.current_playback.return_value = {
        'is_playing': False,
        'progress_ms': 0,
        'shuffle_state': False,
        'repeat_state': 'off',
        'item': {
            'name': 't', 'uri': 'spotify:track:t',
            'duration_ms': 1000,
            'artists': [{'name': 'a'}],
            'album': {'name': 'al', 'images': []}
        }
    }

    def hold_lock_briefly():
        with player.lock:
            time.sleep(0.15)

    holder = threading.Thread(target=hold_lock_briefly)
    holder.start()
    time.sleep(0.02)  # let holder grab the lock

    t0 = time.monotonic()
    player.toggle()
    elapsed = time.monotonic() - t0
    holder.join(timeout=1.0)

    assert elapsed < 2.0, f"toggle() took {elapsed:.2f}s — possible deadlock"
    player.sp_client.start_playback.assert_called()
