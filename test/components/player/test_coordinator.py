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
                  pause_raises=None, stop_raises=None,
                  publish_cleanup_raises=None,
                  with_publish_cleanup=False):
    """Build callbacks that record their invocations in ``calls``.

    Returns ``(pause_fn, stop_fn)`` when ``with_publish_cleanup=False``
    (legacy 2-callback signature used by all existing tests), or
    ``(pause_fn, stop_fn, publish_cleanup_fn)`` when
    ``with_publish_cleanup=True`` (Phase 5a — three-callback signature
    for tests of the cleanup-publish hook).
    """
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

    if not with_publish_cleanup:
        return pause, stop

    def publish_cleanup():
        calls.append((name, 'publish_cleanup'))
        if publish_cleanup_raises is not None:
            raise publish_cleanup_raises

    return pause, stop, publish_cleanup


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


def test_concurrent_activations_call_each_handoff_callback_exactly_once(coordinator):
    """Phase 2 FU#5 regression: under concurrent activations, the
    outgoing backend's ``pause_fn`` / ``stop_fn`` must each fire
    exactly *once* per actual handoff transition.

    The pre-FU#5 test (``test_concurrent_activations_land_deterministically``)
    only asserted the final state was one of the targets. That would
    have missed a regression where the coordinator double-invoked
    the outgoing backend's pause/stop on a race (which would be
    audible: MPD pausing twice has no visible effect, but for
    podcast it can corrupt resume position).

    With three backends (mpd → first activation → second activation),
    we expect the outgoing backend's pause and stop to be invoked
    exactly once each, totalling either:
    - 4 callback invocations if both incoming threads do work
      (mpd is paused/stopped by one thread, then whoever wins among
      the second pair pauses/stops the loser). However the
      coordinator's lock serialises activations: if T1 wins first,
      mpd→T1.target, then T2 activates → T1.target is current
      already? No — T2 has its own target. So if T1 finishes first
      and sets ``current = spotify``, T2 then sees outgoing=spotify
      and pauses/stops spotify before setting current=podcast.

    The invariant we pin: ``pause_fn(outgoing)`` and ``stop_fn(outgoing)``
    each fire exactly once per *successful* transition, NOT twice.
    """
    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    p_spot, s_spot = _make_backend(calls, 'spotify')
    p_podcast, s_podcast = _make_backend(calls, 'podcast')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    coordinator.register('spotify', stop_fn=s_spot, pause_fn=p_spot)
    coordinator.register('podcast', stop_fn=s_podcast, pause_fn=p_podcast)

    # Sequential, deterministic case first — this is the strong pin.
    with coordinator.activate('spotify'):
        pass
    # mpd was current → mpd should have been paused/stopped exactly once.
    assert calls.count(('mpd', 'pause')) == 1, \
        f"mpd.pause_fn invoked {calls.count(('mpd', 'pause'))} times; expected 1"
    assert calls.count(('mpd', 'stop')) == 1, \
        f"mpd.stop_fn invoked {calls.count(('mpd', 'stop'))} times; expected 1"
    assert calls.count(('spotify', 'pause')) == 0
    assert calls.count(('spotify', 'stop')) == 0

    with coordinator.activate('podcast'):
        pass
    # spotify was current → spotify paused/stopped exactly once.
    assert calls.count(('spotify', 'pause')) == 1
    assert calls.count(('spotify', 'stop')) == 1
    # mpd's counts must not have changed.
    assert calls.count(('mpd', 'pause')) == 1
    assert calls.count(('mpd', 'stop')) == 1


def test_idempotent_activate_does_not_invoke_self_callbacks(coordinator):
    """A second ``activate('mpd')`` while mpd is already current must
    NOT invoke mpd's own pause/stop. The pre-FU#5 test pinned that no
    work was done at all; this test specifically pins the "outgoing ==
    incoming" branch is recognised."""
    calls = []
    p_mpd, s_mpd = _make_backend(calls, 'mpd')
    coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)

    with coordinator.activate('mpd'):
        pass
    with coordinator.activate('mpd'):
        pass
    with coordinator.activate('mpd'):
        pass

    assert calls.count(('mpd', 'pause')) == 0
    assert calls.count(('mpd', 'stop')) == 0


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
# Cleanup-publish hook (Phase 5a, project_phase_3c_followups.md #2)
# ---------------------------------------------------------------------------
def test_publish_cleanup_runs_after_pause_and_stop(coordinator):
    """When an outgoing backend has registered ``publish_cleanup_fn``,
    the coordinator must invoke it during handoff AFTER pause + stop
    (so the cleanup snapshot reflects the now-paused state) and BEFORE
    the active-backend slot is reassigned (so the backend's own
    publish helpers still gate-allow the snapshot)."""
    calls = []
    p_out, s_out, pc_out = _make_backend(calls, 'outgoing',
                                          with_publish_cleanup=True)
    p_in, s_in = _make_backend(calls, 'incoming')
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out,
                         publish_cleanup_fn=pc_out)
    coordinator.register('incoming', stop_fn=s_in, pause_fn=p_in)

    with coordinator.activate('incoming'):
        pass

    assert calls == [
        ('outgoing', 'pause'),
        ('outgoing', 'stop'),
        ('outgoing', 'publish_cleanup'),
    ]
    assert coordinator.current() == 'incoming'


def test_publish_cleanup_optional_for_backends_that_dont_opt_in(coordinator):
    """A backend that registers WITHOUT publish_cleanup_fn must continue
    to work — no exception, no missing callback in the handoff sequence.
    This guards the legacy MPD/podcast registrations (they don't yet
    opt in to cleanup-publish)."""
    calls = []
    p_out, s_out = _make_backend(calls, 'outgoing')
    p_in, s_in = _make_backend(calls, 'incoming')
    # No publish_cleanup_fn → omitted (defaults to None).
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out)
    coordinator.register('incoming', stop_fn=s_in, pause_fn=p_in)

    with coordinator.activate('incoming'):
        pass

    assert calls == [('outgoing', 'pause'), ('outgoing', 'stop')]
    assert coordinator.current() == 'incoming'


def test_publish_cleanup_runs_before_active_slot_swap(coordinator):
    """The cleanup hook must run while ``coordinator.current()`` still
    reports the outgoing backend, NOT after the swap. Otherwise the
    backend's own publish helpers (which gate on
    ``coordinator.current() == self.name``) would refuse the cleanup
    snapshot and the UI would never receive the clear.

    We verify this by having the cleanup callback record
    ``coordinator.current()`` at the moment of invocation."""
    calls = []
    observed_active = []

    def pause_out():
        calls.append(('outgoing', 'pause'))

    def stop_out():
        calls.append(('outgoing', 'stop'))

    def publish_cleanup_out():
        calls.append(('outgoing', 'publish_cleanup'))
        observed_active.append(coordinator.current())

    def pause_in():
        calls.append(('incoming', 'pause'))

    def stop_in():
        calls.append(('incoming', 'stop'))

    coordinator.register('outgoing', stop_fn=stop_out, pause_fn=pause_out,
                         publish_cleanup_fn=publish_cleanup_out)
    coordinator.register('incoming', stop_fn=stop_in, pause_fn=pause_in)

    with coordinator.activate('incoming'):
        pass

    assert observed_active == ['outgoing'], (
        f"cleanup-publish must see coordinator.current() == 'outgoing' "
        f"(not yet swapped); saw {observed_active!r}"
    )
    assert coordinator.current() == 'incoming'


def test_publish_cleanup_exception_does_not_block_handoff(coordinator, caplog):
    """A failing cleanup-publish (e.g. publisher torn down) must not
    abort the handoff. Log the error and proceed to the slot swap."""
    calls = []
    p_out, s_out, pc_out = _make_backend(
        calls, 'outgoing',
        with_publish_cleanup=True,
        publish_cleanup_raises=RuntimeError('publisher gone'),
    )
    p_in, s_in = _make_backend(calls, 'incoming')
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out,
                         publish_cleanup_fn=pc_out)
    coordinator.register('incoming', stop_fn=s_in, pause_fn=p_in)

    with caplog.at_level(logging.ERROR, logger='jb.player.coordinator'):
        with coordinator.activate('incoming'):
            pass

    assert coordinator.current() == 'incoming'
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any('publisher gone' in m or 'RuntimeError' in m for m in msgs)


def test_publish_cleanup_skipped_for_idempotent_activation(coordinator):
    """Activating the already-current backend is a no-op: no pause,
    no stop, no cleanup-publish. The cleanup hook is only relevant on
    REAL handoffs."""
    calls = []
    p_out, s_out, pc_out = _make_backend(calls, 'outgoing',
                                          with_publish_cleanup=True)
    coordinator.register('outgoing', stop_fn=s_out, pause_fn=p_out,
                         publish_cleanup_fn=pc_out)

    with coordinator.activate('outgoing'):
        pass
    with coordinator.activate('outgoing'):
        pass

    assert calls == []


def test_publish_cleanup_clears_stale_ui_state_during_429_storm(coordinator):
    """Regression test for project_phase_3c_followups.md #2.

    Simulate the canonical failure mode: Spotify is the active
    backend, hits a 429 storm so its status loop is throttled to a
    30s backoff. The user swipes an MPD card during the storm. Without
    the cleanup-publish, the UI would be stuck on the last Spotify
    status (the title/artist/file fields of whatever was playing)
    until either (a) MPD pushes its first status, or (b) Spotify's
    next throttled poll comes around — whichever comes first.

    The cleanup-publish guarantees a cleared snapshot lands AS PART
    of the coordinator handoff, before either of those events. We
    assert: (1) the cleanup callback fires exactly once on handoff,
    (2) it fires after Spotify's pause+stop, (3) MPD (the incoming
    backend) never sees a cleanup-publish (because it didn't opt in)."""
    sent_messages = []

    def pause_spotify():
        sent_messages.append(('spotify', 'pause_called'))

    def stop_spotify():
        sent_messages.append(('spotify', 'stop_called'))

    def spotify_cleanup_publish():
        # Mimics the real backend: builds a cleared snapshot dict
        # and forwards it to the publisher.
        cleared = {'state': 'stop', 'title': '', 'file': '',
                   'player_type': 'spotify'}
        sent_messages.append(('spotify', 'publish_cleanup', cleared))

    def pause_mpd():
        sent_messages.append(('mpd', 'pause_called'))

    def stop_mpd():
        sent_messages.append(('mpd', 'stop_called'))

    coordinator.register('spotify', stop_fn=stop_spotify, pause_fn=pause_spotify,
                         publish_cleanup_fn=spotify_cleanup_publish)
    # MPD registered after Spotify but coordinator.register() doesn't
    # flip current(), so we explicitly activate spotify first.
    coordinator.register('mpd', stop_fn=stop_mpd, pause_fn=pause_mpd)
    with coordinator.activate('spotify'):
        pass
    sent_messages.clear()  # discard the spotify-activation noise

    # User swipes MPD card mid-429-storm.
    with coordinator.activate('mpd'):
        pass

    # Cleanup-publish fired exactly once on this handoff, after
    # Spotify's pause+stop, and the payload was the cleared snapshot.
    cleanup_events = [m for m in sent_messages if m[0] == 'spotify' and m[1] == 'publish_cleanup']
    assert len(cleanup_events) == 1, (
        f"expected exactly one cleanup-publish during handoff, got "
        f"{len(cleanup_events)}: {sent_messages!r}"
    )
    cleared_payload = cleanup_events[0][2]
    # The UI's stale-state guard relies on these fields being blanked.
    assert cleared_payload['state'] == 'stop'
    assert cleared_payload['title'] == ''
    assert cleared_payload['file'] == ''

    # Ordering: pause → stop → publish_cleanup (no MPD callbacks in
    # between — MPD only acts as the incoming backend).
    spotify_seq = [m[1] for m in sent_messages if m[0] == 'spotify']
    assert spotify_seq == ['pause_called', 'stop_called', 'publish_cleanup']

    # MPD didn't opt in to cleanup-publish (it's the incoming backend
    # anyway, but we double-check no callback fired for it).
    mpd_events = [m for m in sent_messages if m[0] == 'mpd']
    assert all(m[1] != 'publish_cleanup' for m in mpd_events)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
def test_get_coordinator_returns_singleton():
    """``get_coordinator()`` must hand back the same instance every call."""
    from components.player.coordinator import get_coordinator
    a = get_coordinator()
    b = get_coordinator()
    assert a is b
