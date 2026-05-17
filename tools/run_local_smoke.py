# -*- coding: utf-8 -*-
"""Local smoke harness — Phase 7.

Boots a minimal jukebox-like environment without touching the daemon,
MPD, PulseAudio, or the network. The goal is to catch regressions in
the *production decision seams* (decide_swipe, PodcastStateManager,
PlayerCoordinator) in single-digit seconds, so a developer can run
this between every change instead of waiting for the RPi round-trip.

What this exercises (intentionally narrow — full-stack smoke is
``./run_pytest.sh``):

1. **MPD card swipes**: fresh swipe, repeated swipe, post-reset swipe
   (the regression that bit Phase 3a). Uses real ``decide_swipe`` +
   ``MPDStateStore`` with a tmp state file.

2. **Podcast card swipes**: fresh feed swipe, re-tap of playing feed,
   re-tap with stale ``playback_active`` flag (the regression that bit
   Phase 3b). Uses real ``decide_second_swipe``.

3. **Player coordinator handoffs**: MPD→Spotify→MPD. Asserts the
   coordinator calls pause-then-stop on the outgoing backend before
   activating the incoming one.

The harness calls ``reset_phoniebox_home_cache()`` between scenarios
so a per-scenario ``PHONIEBOX_HOME`` actually takes effect. Without
that, ``get_phoniebox_home`` would memoise the first scenario's home
and silently route subsequent scenarios at the wrong tree.

Exit code is 0 on full pass, non-zero on the first failure with a
human-readable diff to stderr.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path
from typing import Callable, List, Tuple

# Make src/jukebox importable so the harness uses real production code.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_JUKEBOX_SRC = _REPO_ROOT / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


# ----------------------------------------------------------------------
# Submodule loader: mirror the test/components/playermpd/conftest.py
# pattern. The decision seams we want to exercise live in submodules
# whose package ``__init__.py`` triggers ``@plugs.initialize`` at
# import time, which requires the full daemon plugin registry. We load
# the submodule file directly under its canonical dotted name and
# stub a minimal parent package so relative imports resolve.
# ----------------------------------------------------------------------


def _ensure_jukebox_utils_stub() -> None:
    """Install stub ``jukebox`` and ``jukebox.utils`` packages.

    Idempotent. After this, leaf modules under ``jukebox.utils`` can be
    loaded by full path without executing the real ``__init__.py`` of
    either package (which would drag in the entire daemon-side
    plumbing).
    """
    if 'jukebox' not in sys.modules:
        jb = types.ModuleType('jukebox')
        jb.__path__ = [str(_JUKEBOX_SRC / 'jukebox')]
        sys.modules['jukebox'] = jb
    if 'jukebox.utils' not in sys.modules:
        ju = types.ModuleType('jukebox.utils')
        ju.__path__ = [str(_JUKEBOX_SRC / 'jukebox' / 'utils')]
        sys.modules['jukebox.utils'] = ju


def _ensure_paths_module():
    """Load ``jukebox.utils.paths`` under its canonical name and return it."""
    _ensure_jukebox_utils_stub()
    qual = 'jukebox.utils.paths'
    if qual in sys.modules:
        return sys.modules[qual]
    spec = importlib.util.spec_from_file_location(
        qual,
        _JUKEBOX_SRC / 'jukebox' / 'utils' / 'paths.py',
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)
    return mod


def _install_atomic_io_module() -> None:
    """Make ``jukebox.utils.atomic_io`` importable without booting jukebox.utils.

    ``jukebox/utils/__init__.py`` pulls subprocess + RPC helpers at
    import time. The smoke harness only needs ``atomic_write_json_safe``
    for the MPD state store, so we install the leaf module directly
    under its canonical dotted name with stub parents in sys.modules.
    """
    qual = 'jukebox.utils.atomic_io'
    if qual in sys.modules:
        return
    _ensure_jukebox_utils_stub()
    spec = importlib.util.spec_from_file_location(
        qual,
        _JUKEBOX_SRC / 'jukebox' / 'utils' / 'atomic_io.py',
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qual] = mod
    spec.loader.exec_module(mod)


def _load_submodule(qualname: str, file_path: Path):
    """Load ``qualname`` from ``file_path`` without executing parent __init__.

    Idempotent: subsequent calls return the already-loaded module.
    """
    pkg_name = qualname.rsplit('.', 1)[0]
    if pkg_name and pkg_name not in sys.modules:
        parent_qual = pkg_name.rsplit('.', 1)[0]
        if parent_qual and parent_qual not in sys.modules:
            sys.modules[parent_qual] = types.ModuleType(parent_qual)
        stub = types.ModuleType(pkg_name)
        stub.__path__ = [str(file_path.parent)]
        sys.modules[pkg_name] = stub

    if qualname in sys.modules:
        return sys.modules[qualname]

    spec = importlib.util.spec_from_file_location(qualname, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# Tiny test-framework: scenarios + assertions
# ----------------------------------------------------------------------

class AssertionFail(Exception):
    """Distinct from stdlib AssertionError to keep tracebacks clean."""


def _check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionFail(msg)


class Scenario:
    def __init__(self, name: str, fn: Callable[[], None]) -> None:
        self.name = name
        self.fn = fn


def _new_scenario_home() -> Tuple[Path, tempfile.TemporaryDirectory]:
    """Allocate a fresh PHONIEBOX_HOME for one scenario.

    Returns ``(home, tmpdir_handle)`` — keep the handle alive for the
    duration of the scenario; let it go to clean up.
    """
    tmpdir = tempfile.TemporaryDirectory(prefix='phoniebox-smoke-')
    home = Path(tmpdir.name)
    # Mirror the shape `get_phoniebox_home` walks up to find — without
    # this the env-var path wins, but creating the marker dir keeps
    # things honest if the env var ever drops.
    (home / 'src' / 'jukebox').mkdir(parents=True)
    (home / 'shared' / 'settings').mkdir(parents=True)
    os.environ['PHONIEBOX_HOME'] = str(home)
    paths_mod = _ensure_paths_module()
    paths_mod.reset_phoniebox_home_cache()
    return home, tmpdir


# ----------------------------------------------------------------------
# Scenario 1: MPD swipe sequence
# ----------------------------------------------------------------------

def scenario_mpd_swipes() -> None:
    """Real ``decide_swipe`` over a real ``MPDStateStore``."""
    home, _td = _new_scenario_home()
    state_file = home / 'shared' / 'settings' / 'mpd_state.json'

    _install_atomic_io_module()
    state_store = _load_submodule(
        'components.playermpd.state_store',
        _JUKEBOX_SRC / 'components' / 'playermpd' / 'state_store.py',
    )
    MPDStateStore = state_store.MPDStateStore
    SwipeDecision = state_store.SwipeDecision
    decide_swipe = state_store.decide_swipe

    store = MPDStateStore(str(state_file))
    second_swipe_action = object()  # truthy sentinel; not None

    # Fresh swipe: nothing remembered -> FIRST.
    d1 = decide_swipe(store, 'audiofolders/Album-A', second_swipe_action)
    _check(d1 is SwipeDecision.FIRST,
           f"fresh swipe: expected FIRST, got {d1}")

    # Record this card as last swiped.
    store.set_last_swiped_folder('audiofolders/Album-A')

    # Second swipe of same card with feature configured -> SECOND_TOGGLE.
    d2 = decide_swipe(store, 'audiofolders/Album-A', second_swipe_action)
    _check(d2 is SwipeDecision.SECOND_TOGGLE,
           f"repeat swipe (configured): expected SECOND_TOGGLE, got {d2}")

    # Same swipe but feature disabled (None) -> FIRST.
    d3 = decide_swipe(store, 'audiofolders/Album-A', None)
    _check(d3 is SwipeDecision.FIRST,
           f"repeat swipe (disabled): expected FIRST, got {d3}")

    # Different card -> FIRST.
    d4 = decide_swipe(store, 'audiofolders/Album-B', second_swipe_action)
    _check(d4 is SwipeDecision.FIRST,
           f"different card: expected FIRST, got {d4}")

    # Post-reboot regression (Phase 3a bug fix): set last_played, save
    # to disk, simulate process restart, then mirror what
    # ``PlayerMPD.__init__`` does — call ``clear_last_swiped_folder``
    # on the freshly-loaded store. First swipe of last-played card
    # must classify as FIRST. Without the clear-on-init the first
    # post-reboot swipe was misclassified as SECOND_TOGGLE.
    store.set_last_played_folder('audiofolders/Album-A')
    store.set_last_swiped_folder('audiofolders/Album-A')
    store.save()
    rebooted = MPDStateStore(str(state_file))
    _check(rebooted.last_played_folder() == 'audiofolders/Album-A',
           'reboot: last_played should persist across re-instantiation')
    # Mirror PlayerMPD.__init__: clear the swipe marker, leave last_played.
    rebooted.clear_last_swiped_folder()
    d5 = decide_swipe(rebooted, 'audiofolders/Album-A', second_swipe_action)
    _check(d5 is SwipeDecision.FIRST,
           f"first-swipe-after-reboot: expected FIRST, got {d5}")

    # State file actually persisted.
    _check(state_file.exists(), 'state file should be written')
    on_disk = json.loads(state_file.read_text())
    _check('player_status' in on_disk,
           f"state file shape unexpected: {on_disk!r}")


# ----------------------------------------------------------------------
# Scenario 2: Podcast swipe sequence
# ----------------------------------------------------------------------

def scenario_podcast_swipes() -> None:
    """Real ``decide_second_swipe`` over realistic state snapshots."""
    home, _td = _new_scenario_home()

    pb = _load_submodule(
        'components.playerpodcast.playback_state',
        _JUKEBOX_SRC / 'components' / 'playerpodcast' / 'playback_state.py',
    )
    SecondSwipeDecision = pb.SecondSwipeDecision
    decide_second_swipe = pb.decide_second_swipe

    # Fresh swipe: nothing playing, no current feed.
    d1 = decide_second_swipe(
        playback_active=False,
        current_feed_url=None,
        incoming_feed_url='https://feeds.example.com/show.xml',
        mpd_state='stop',
    )
    _check(d1 is SecondSwipeDecision.FRESH_START,
           f"fresh podcast: expected FRESH_START, got {d1}")

    # Re-tap of currently playing feed -> INVOKE_HANDLER (resume/pause).
    d2 = decide_second_swipe(
        playback_active=True,
        current_feed_url='https://feeds.example.com/show.xml',
        incoming_feed_url='https://feeds.example.com/show.xml',
        mpd_state='play',
    )
    _check(d2 is SecondSwipeDecision.INVOKE_HANDLER,
           f"repeat-while-playing: expected INVOKE_HANDLER, got {d2}")

    # Stale flag regression (Phase 3b): playback_active says True but
    # MPD actually stopped -> CLEAR_STALE_AND_RESTART.
    d3 = decide_second_swipe(
        playback_active=True,
        current_feed_url='https://feeds.example.com/show.xml',
        incoming_feed_url='https://feeds.example.com/show.xml',
        mpd_state='stop',
    )
    _check(d3 is SecondSwipeDecision.CLEAR_STALE_AND_RESTART,
           f"stale flag: expected CLEAR_STALE_AND_RESTART, got {d3}")

    # Different feed swipe -> FRESH_START.
    d4 = decide_second_swipe(
        playback_active=True,
        current_feed_url='https://feeds.example.com/show.xml',
        incoming_feed_url='https://feeds.example.com/OTHER.xml',
        mpd_state='play',
    )
    _check(d4 is SecondSwipeDecision.FRESH_START,
           f"different feed: expected FRESH_START, got {d4}")


# ----------------------------------------------------------------------
# Scenario 3: Coordinator handoff
# ----------------------------------------------------------------------

def scenario_coordinator_handoff() -> None:
    """Real ``PlayerCoordinator`` with three fake backends."""
    _new_scenario_home()

    coord_mod = _load_submodule(
        'components.player.coordinator',
        _JUKEBOX_SRC / 'components' / 'player' / 'coordinator.py',
    )
    PlayerCoordinator = coord_mod.PlayerCoordinator

    coord = PlayerCoordinator()
    calls: List[Tuple[str, str]] = []

    def make_backend(name: str):
        def pause():
            calls.append((name, 'pause'))

        def stop():
            calls.append((name, 'stop'))
        return pause, stop

    mpd_pause, mpd_stop = make_backend('mpd')
    spo_pause, spo_stop = make_backend('spotify')
    pod_pause, pod_stop = make_backend('podcast')

    coord.register('mpd', mpd_stop, mpd_pause)
    coord.register('spotify', spo_stop, spo_pause)
    coord.register('podcast', pod_stop, pod_pause)

    _check(coord.current() == 'mpd',
           f"first-registered should be current; got {coord.current()}")

    # Handoff MPD -> Spotify.
    with coord.activate('spotify'):
        pass
    _check(coord.current() == 'spotify',
           f"after MPD->Spotify: current should be spotify, got {coord.current()}")
    _check(('mpd', 'pause') in calls and ('mpd', 'stop') in calls,
           f"MPD should be paused-then-stopped on handoff; calls={calls}")
    _check(calls.index(('mpd', 'pause')) < calls.index(('mpd', 'stop')),
           f"pause must precede stop; calls={calls}")

    pre_len = len(calls)

    # Idempotent re-activation: no extra calls.
    with coord.activate('spotify'):
        pass
    _check(len(calls) == pre_len,
           f"re-activate same backend should be a no-op; new calls: {calls[pre_len:]}")

    # Handoff Spotify -> MPD.
    with coord.activate('mpd'):
        pass
    _check(coord.current() == 'mpd',
           f"after Spotify->MPD: current should be mpd, got {coord.current()}")
    _check(('spotify', 'pause') in calls and ('spotify', 'stop') in calls,
           f"Spotify should be paused-then-stopped; calls={calls}")


# ----------------------------------------------------------------------
# Scenario 4: paths.resolve_under_home + cache-reset behaviour
# ----------------------------------------------------------------------

def scenario_paths_cache_reset() -> None:
    """``reset_phoniebox_home_cache`` actually invalidates the LRU cache."""
    paths_mod = _ensure_paths_module()
    get_phoniebox_home = paths_mod.get_phoniebox_home
    reset_phoniebox_home_cache = paths_mod.reset_phoniebox_home_cache
    resolve_under_home = paths_mod.resolve_under_home

    home1, _td1 = _new_scenario_home()
    p1 = get_phoniebox_home()
    _check(p1 == home1.resolve(),
           f"home1: expected {home1}, got {p1}")
    cfg1 = resolve_under_home('shared/settings/jukebox.yaml')
    _check(str(cfg1).startswith(str(home1.resolve())),
           f"resolve under home1 should anchor: {cfg1}")

    # New scenario: env var changes but cache must be cleared first.
    home2, _td2 = _new_scenario_home()  # already calls reset
    p2 = get_phoniebox_home()
    _check(p2 == home2.resolve(),
           f"home2: cache should have been reset; got {p2} vs {home2}")

    # Manual second call without reset would silently re-use cache —
    # confirm reset_phoniebox_home_cache() is what clears it.
    os.environ['PHONIEBOX_HOME'] = str(home1)
    # No reset → expect stale home2.
    p_stale = get_phoniebox_home()
    _check(p_stale == home2.resolve(),
           f"without reset: should still see home2 from cache; got {p_stale}")
    reset_phoniebox_home_cache()
    p_fresh = get_phoniebox_home()
    _check(p_fresh == home1.resolve(),
           f"after reset: should pick up home1; got {p_fresh}")


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------

SCENARIOS: List[Scenario] = [
    Scenario('mpd_swipes', scenario_mpd_swipes),
    Scenario('podcast_swipes', scenario_podcast_swipes),
    Scenario('coordinator_handoff', scenario_coordinator_handoff),
    Scenario('paths_cache_reset', scenario_paths_cache_reset),
]


def main() -> int:
    print("local smoke: starting", file=sys.stderr)
    t0 = time.time()
    failed: List[Tuple[str, str]] = []

    for scn in SCENARIOS:
        s_start = time.time()
        # Each scenario starts with a fresh env so PHONIEBOX_HOME from
        # the previous one doesn't bleed in if the scenario forgot to
        # call _new_scenario_home itself.
        os.environ.pop('PHONIEBOX_HOME', None)
        try:
            _ensure_paths_module().reset_phoniebox_home_cache()
        except Exception:
            pass
        try:
            scn.fn()
            print(f"  PASS  {scn.name}  ({(time.time() - s_start) * 1000:.0f}ms)",
                  file=sys.stderr)
        except AssertionFail as e:
            failed.append((scn.name, str(e)))
            print(f"  FAIL  {scn.name}  ({(time.time() - s_start) * 1000:.0f}ms)",
                  file=sys.stderr)
            print(f"        {e}", file=sys.stderr)
        except Exception:
            tb = traceback.format_exc()
            failed.append((scn.name, tb))
            print(f"  ERROR {scn.name}  ({(time.time() - s_start) * 1000:.0f}ms)",
                  file=sys.stderr)
            print(tb, file=sys.stderr)

    elapsed = time.time() - t0
    if failed:
        print(f"\nlocal smoke: {len(failed)} scenario(s) failed in {elapsed:.1f}s",
              file=sys.stderr)
        for name, err in failed:
            print(f"  - {name}: {err.splitlines()[0] if err else '(no message)'}",
                  file=sys.stderr)
        return 1
    print(f"\nlocal smoke: {len(SCENARIOS)} scenario(s) passed in {elapsed:.1f}s",
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
