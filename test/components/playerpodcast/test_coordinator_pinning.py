# -*- coding: utf-8 -*-
"""Phase 2 FU#2: podcast pins itself as the active backend.

The pre-fix flow had a coordinator-state-leak:

1. Card swipe -> ``play_podcast_series`` -> ``_activate_podcast()``
   sets ``coordinator.current() == 'podcast'``.
2. ``plugs.call('player','ctrl','play_single', ...)`` -> MPD's
   ``play_single`` calls ``_activate_mpd()`` -> coordinator flips
   back to ``'mpd'``.
3. UI sees ``coordinator.current() == 'mpd'`` but the user just
   tapped a podcast card. Worse, a subsequent Spotify activation
   pause+stops *MPD* (not podcast), discarding the podcast's
   resume position.

The Phase 3b fix introduces ``play_single_passive`` on playermpd
(does NOT call ``_activate_mpd``) and routes podcast through it.
Podcast also re-pins itself on the user-facing passive controls
(``play`` / ``pause`` / ``next`` / ``prev`` / ``_toggle_playback``)
so any drift self-heals.

These tests exercise the real ``PlayerCoordinator`` (not a mock) and
drive the podcast methods through a mocked plugs that simulates
playermpd's ``_activate_mpd`` side-effect for ``play_single`` only -
proving that the passive variants do NOT trigger the flip.
"""

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


# Do NOT pre-mock ``requests`` / ``feedparser`` at module level here
# - both are installed in the venv, and a module-level MagicMock for
# ``requests`` pollutes sys.modules for later-collected test files
# (e.g. playerspotify, where ``spotipy.oauth2`` does
# ``isinstance(x, requests.Session)`` and that raises TypeError when
# Session is a MagicMock instead of a class). Conftest pre-mocks
# the jukebox framework and ``components.player`` only.

from components.playerpodcast import PlayerPodcast  # noqa: E402


@pytest.fixture
def real_coordinator(monkeypatch):
    """Inject a fresh ``PlayerCoordinator`` into the podcast module's
    ``get_coordinator`` reference. Avoids singleton pollution between
    tests."""
    # Load the real coordinator module file directly to get a fresh
    # PlayerCoordinator class.
    import importlib.util
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'player' / 'coordinator.py'
    )
    spec = importlib.util.spec_from_file_location(
        '_real_coordinator_for_test', src,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    coord = mod.PlayerCoordinator()
    monkeypatch.setattr(
        'components.playerpodcast.get_coordinator',
        lambda: coord,
    )
    return coord


@pytest.fixture
def podcast_player(real_coordinator):
    """``PlayerPodcast`` wired to ``real_coordinator`` with the
    minimum attributes for the methods under test."""
    p = PlayerPodcast.__new__(PlayerPodcast)
    p.lock = threading.RLock()
    p.feed_manager = MagicMock()
    p.queue_manager = MagicMock()
    p.state_manager = MagicMock()
    p.episode_downloader = None
    p.mpd_podcast_subdir = 'podcast-cache'
    p.current_podcast_id = 'pod1'
    p.current_episode_guid = 'ep1'
    p.current_feed_url = 'http://feed/a'
    p.playback_active = True
    p.current_episode_metadata = {'title': 'E', 'url': 'http://ep1'}
    p.current_podcast_metadata = {'title': 'P', 'author': '', 'image_url': ''}
    p.second_swipe_action = MagicMock()
    return p


def _mock_mpd_play_single_activates(coordinator, mock_plugs):
    """Wire ``mock_plugs.call`` so play_single mimics playermpd's
    real behaviour: it switches the coordinator to 'mpd'.
    play_single_passive does NOT.
    """
    def fake_call(*args, **kwargs):
        if args == ('player', 'ctrl', 'play_single'):
            # Simulate playermpd._activate_mpd().
            with coordinator.activate('mpd'):
                pass
        # play_single_passive intentionally does no coordinator work.
        if args[-1:] == ('playerstatus',):
            return {'state': 'play', 'elapsed': '5', 'duration': '100'}
        return {}
    mock_plugs.call = fake_call


# ---------------------------------------------------------------------------
# Core decision tests
# ---------------------------------------------------------------------------
def test_play_podcast_series_keeps_coordinator_on_podcast(
    podcast_player, real_coordinator,
):
    """The headline FU#2 invariant: ``coordinator.current()`` stays
    on ``'podcast'`` after ``play_podcast_series`` returns.

    Reversion check: revert ``play_single`` -> ``play_single_passive``
    in the podcast module (or revert the playermpd
    ``play_single_passive`` addition) and the coordinator flips to
    ``'mpd'`` - this test fails.
    """
    # Register the backends so handoff has something to pause/stop.
    pause_stop_log = []

    def make_callbacks(name):
        return (
            lambda: pause_stop_log.append(('pause', name)),
            lambda: pause_stop_log.append(('stop', name)),
        )

    p_mpd, s_mpd = make_callbacks('mpd')
    p_pod, s_pod = make_callbacks('podcast')
    real_coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    real_coordinator.register('podcast', stop_fn=s_pod, pause_fn=p_pod)
    assert real_coordinator.current() == 'mpd'  # mpd first

    # Set up the queue manager to return a one-episode feed.
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
    # Make second-swipe decision fall through to fresh start.
    podcast_player.playback_active = False
    podcast_player.current_feed_url = None

    with patch('components.playerpodcast.plugs') as mock_plugs:
        _mock_mpd_play_single_activates(real_coordinator, mock_plugs)
        podcast_player.play_podcast_series('http://feed/a')

    # The headline assertion.
    assert real_coordinator.current() == 'podcast', (
        f"coordinator drifted to {real_coordinator.current()!r} - "
        "play_single_passive should NOT touch the coordinator"
    )
    # And mpd was paused+stopped during the handoff (proving the
    # coordinator activation actually fired).
    assert ('pause', 'mpd') in pause_stop_log
    assert ('stop', 'mpd') in pause_stop_log


def test_passive_controls_re_pin_podcast_after_drift(
    podcast_player, real_coordinator,
):
    """If the coordinator has somehow drifted to ``'mpd'`` (e.g. an
    external RPC or a legacy bug), the user-facing podcast passive
    controls (``play`` / ``pause`` / ``_toggle_playback``) re-pin
    podcast on the next call.

    Reversion check: remove ``self._activate_podcast()`` from the
    podcast ``play``/``pause``/``_toggle_playback`` methods and
    this test fails - the coordinator stays on 'mpd'.
    """
    pause_stop_log = []

    def make_callbacks(name):
        return (
            lambda: pause_stop_log.append(('pause', name)),
            lambda: pause_stop_log.append(('stop', name)),
        )

    p_mpd, s_mpd = make_callbacks('mpd')
    p_pod, s_pod = make_callbacks('podcast')
    real_coordinator.register('mpd', stop_fn=s_mpd, pause_fn=p_mpd)
    real_coordinator.register('podcast', stop_fn=s_pod, pause_fn=p_pod)
    # Force drift.
    with real_coordinator.activate('mpd'):
        pass
    pause_stop_log.clear()
    assert real_coordinator.current() == 'mpd'

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = MagicMock(return_value={})
        podcast_player.play()

    assert real_coordinator.current() == 'podcast'
    # Re-pinning fired the handoff: mpd was paused+stopped.
    assert ('pause', 'mpd') in pause_stop_log
    assert ('stop', 'mpd') in pause_stop_log


def test_play_uses_passive_pause_not_mpd_play(
    podcast_player, real_coordinator,
):
    """``PlayerPodcast.play`` must call MPD's ``pause(0)`` (passive
    resume), NOT MPD's ``play`` (activation event). Calling MPD's
    ``play`` would re-activate MPD and yank coordinator state.

    Reversion check: change ``play()`` to call ``plugs.call(player,
    ctrl, play)`` again and this test fails - the mock records
    'play' not 'pause' with state=0.
    """
    real_coordinator.register(
        'podcast', stop_fn=MagicMock(), pause_fn=MagicMock(),
    )

    recorded = []

    def recorder(*args, **kwargs):
        recorded.append((args, kwargs))

    with patch('components.playerpodcast.plugs') as mock_plugs:
        mock_plugs.call = recorder
        podcast_player.play()

    # Find the actual MPD call (skip any others).
    mpd_calls = [
        (a, k) for (a, k) in recorded
        if a[:2] == ('player', 'ctrl') and a[2] in ('play', 'pause')
    ]
    assert mpd_calls, "play() did not call into MPD"
    args, kwargs = mpd_calls[0]
    # Must be pause(state=0), not play.
    assert args == ('player', 'ctrl', 'pause'), (
        f"play() called {args[2]!r}; expected 'pause' (passive resume) "
        "to avoid triggering MPD's _activate_mpd"
    )
    assert kwargs.get('args') == (0,), (
        f"play() must call pause(0); got pause(args={kwargs.get('args')})"
    )
