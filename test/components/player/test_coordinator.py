# -*- coding: utf-8 -*-
"""Tests for :class:`PlayerCoordinator` (Phase 2).

Covers the contract the three player backends now depend on:

* Registration + ``current()`` initial state.
* Handoff calls ``pause_fn`` before ``stop_fn`` on the outgoing backend.
* Re-activating the current backend is a no-op (no handoff work).
* Concurrent activations land deterministically (exactly one final state).
* A wedged ``stop_fn`` does not hang the handoff; an ERROR is logged.
* Pause-before-stop ordering on real handoffs (Spotify-during-podcast etc.).
"""

import logging
import sys
import threading
import time
from pathlib import Path

import pytest


# Make the jukebox source importable when running tests bare (no
# subdirectory conftest pre-mocks the plugs framework here — the
# coordinator is plugin-framework free by design).
_PKG_ROOT = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def coordinator():
    """A fresh :class:`PlayerCoordinator` per test.

    We instantiate directly (not via :func:`get_coordinator`) so tests
    cannot leak state into one another via the module-level singleton.
    """
    from components.player.coordinator import PlayerCoordinator
    return PlayerCoordinator()


def _make_backend(calls, name, *, pause_delay=0.0, stop_delay=0.0,
                  pause_raises=None, stop_raises=None):
    """Build (pause_fn, stop_fn) that record their invocations in ``calls``."""
    def pause():
        calls.append((name, 'pause'))
        if pause_delay:
            time.sleep(pause_delay)
        if pause_raises is not None:
            raise pause_raises

    def stop():
        calls.append((name, 'stop'))
        if stop_delay:
            time.sleep(stop_delay)
        if stop_raises is not None:
            raise stop_raises

    return pause, stop


# ---------------------------------------------------------------------------
# Registration / current()
# ---------------------------------------------------------------------------
def test_register_and_current(coordinator):
    """First registered backend becomes current; subsequent ones do not."""
    assert coordinator.current() is None

    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    assert coordinator.current() == 'mpd'

    p_spot, s_spot = _make_backend(calls, 'spotify')
    coordinator.register('spotify', stop_fn=s_spot, pause_fn=p_spot)
    # current() must NOT change just from a register() — only activate() shifts it.
    assert coordinator.current() == 'mpd'
    # And no pause/stop was triggered by registration.
    assert calls == []


# ---------------------------------------------------------------------------
# Handoff: pause-then-stop ordering
# ---------------------------------------------------------------------------
def test_activate_calls_previous_pause_then_stop(coordinator):
    """Handoff must invoke the OUTGOING backend's pause, then stop."""
    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    p_spot, s_spot = _make_backend(calls, 'spotify')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    coordinator.register('spotify', stop_fn=s_spot, pause_fn=p_spot)

    with coordinator.activate('spotify'):
        pass

    # Outgoing (mpd) gets pause then stop; incoming (spotify) is untouched.
    assert calls == [('mpd', 'pause'), ('mpd', 'stop')]
    assert coordinator.current() == 'spotify'


def test_activate_handoff_preserves_pause_before_stop_ordering(coordinator):
    """Cycle podcast -> spotify -> mpd and assert ordering at every hop.

    The pause-first invariant is what preserves the outgoing backend's
    resume position (mpd's pause() persists state; spotify's pause()
    leaves the Spotify-side cursor where it is). Stop-only would
    discard that information.
    """
    calls = []
    p_podcast, s_podcast = _make_backend(calls, 'podcast')
    p_spotify, s_spotify = _make_backend(calls, 'spotify')
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    coordinator.register('podcast', stop_fn=s_podcast, pause_fn=p_podcast)
    coordinator.register('spotify', stop_fn=s_spotify, pause_fn=p_spotify)
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)

    # podcast was registered first, so it's current.
    assert coordinator.current() == 'podcast'

    with coordinator.activate('spotify'):
        pass
    with coordinator.activate('mpd'):
        pass

    assert calls == [
        ('podcast', 'pause'), ('podcast', 'stop'),
        ('spotify', 'pause'), ('spotify', 'stop'),
    ]
    assert coordinator.current() == 'mpd'


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
def test_activate_is_idempotent(coordinator):
    """Activating the already-current backend triggers no pause/stop work."""
    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)

    with coordinator.activate('mpd'):
        pass
    with coordinator.activate('mpd'):
        pass

    assert calls == []
    assert coordinator.current() == 'mpd'


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
def test_concurrent_activations_land_deterministically(coordinator):
    """Two threads racing to activate different backends produce a
    consistent final state. The coordinator's lock serialises the
    swap, so the final ``current()`` is the value of whichever
    activation completed last — not a torn read."""
    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    p_spot, s_spot = _make_backend(calls, 'spotify')
    p_podcast, s_podcast = _make_backend(calls, 'podcast')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    coordinator.register('spotify', stop_fn=s_spot, pause_fn=p_spot)
    coordinator.register('podcast', stop_fn=s_podcast, pause_fn=p_podcast)

    barrier = threading.Barrier(2)

    def claim(target):
        barrier.wait()
        with coordinator.activate(target):
            pass

    t1 = threading.Thread(target=claim, args=('spotify',))
    t2 = threading.Thread(target=claim, args=('podcast',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # The final state must be one of the two targets — never something
    # else (no torn read), never None.
    assert coordinator.current() in {'spotify', 'podcast'}


# ---------------------------------------------------------------------------
# Stop timeout
# ---------------------------------------------------------------------------
def test_stop_timeout_logs_error_and_proceeds(coordinator, monkeypatch, caplog):
    """A ``stop_fn`` that blocks past the timeout must not hang the handoff.

    We monkeypatch ``STOP_TIMEOUT_SECONDS`` down so the test is fast.
    The hanging stop_fn returns eventually (so the worker thread doesn't
    leak past pytest), but the coordinator must move on before then.
    """
    from components.player import coordinator as coord_mod
    monkeypatch.setattr(coord_mod, 'STOP_TIMEOUT_SECONDS', 0.2)

    calls = []
    # outgoing backend has a stop_fn that sleeps WELL beyond the timeout
    p_slow, s_slow = _make_backend(calls, 'slow', stop_delay=2.0)
    p_fast, s_fast = _make_backend(calls, 'fast')
    coordinator.register('slow', stop_fn=s_slow, pause_fn=p_slow)
    coordinator.register('fast', stop_fn=s_fast, pause_fn=p_fast)

    t0 = time.monotonic()
    with caplog.at_level(logging.ERROR, logger='jb.player.coordinator'):
        with coordinator.activate('fast'):
            pass
    elapsed = time.monotonic() - t0

    # We waited for the timeout (~0.2s) but NOT the full sleep (2s).
    assert elapsed < 1.0, f"activate() should have timed out, took {elapsed:.2f}s"
    assert coordinator.current() == 'fast'

    # An ERROR log line should mention the timeout.
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any('timeout' in m.lower() for m in msgs), \
        f"expected a timeout ERROR log, got: {msgs}"


def test_stop_exception_is_logged_but_handoff_proceeds(coordinator, caplog):
    """A ``stop_fn`` that raises must not abort the handoff."""
    calls = []
    p_out, s_out = _make_backend(calls, 'outgoing',
                                  stop_raises=RuntimeError('wire broke'))
    p_in, s_in = _make_backend(calls, 'incoming')
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out)
    coordinator.register('incoming', stop_fn=s_in, pause_fn=p_in)

    with caplog.at_level(logging.ERROR, logger='jb.player.coordinator'):
        with coordinator.activate('incoming'):
            pass

    assert coordinator.current() == 'incoming'
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any('wire broke' in m or 'RuntimeError' in m for m in msgs), \
        f"expected stop_fn error to be logged, got: {msgs}"


def test_pause_exception_is_logged_but_handoff_proceeds(coordinator, caplog):
    """A ``pause_fn`` that raises must not abort the handoff either."""
    calls = []
    p_out, s_out = _make_backend(calls, 'outgoing',
                                  pause_raises=RuntimeError('pause failed'))
    p_in, s_in = _make_backend(calls, 'incoming')
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out)
    coordinator.register('incoming', stop_fn=s_in, pause_fn=p_in)

    with caplog.at_level(logging.ERROR, logger='jb.player.coordinator'):
        with coordinator.activate('incoming'):
            pass

    # Stop should still run even though pause raised.
    assert ('outgoing', 'pause') in calls
    assert ('outgoing', 'stop') in calls
    assert coordinator.current() == 'incoming'


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
def test_get_coordinator_returns_singleton():
    """``get_coordinator()`` must hand back the same instance every call."""
    from components.player.coordinator import get_coordinator
    a = get_coordinator()
    b = get_coordinator()
    assert a is b
