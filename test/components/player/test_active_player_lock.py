# -*- coding: utf-8 -*-
"""Regression tests for the ``_active_player`` lock + CAS API.

Phase 1, fix #1: ``components.player.set_active_player`` is now thread-safe
and supports compare-and-swap so that two competing player activations
land in a deterministic final state.
"""

import sys
import threading
from pathlib import Path
from unittest import mock

import pytest


# Make src/jukebox importable.
_PKG_ROOT = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def player_module():
    """Import (or re-import) components.player with a stub config handler."""
    fake_cfg = mock.MagicMock()
    fake_cfg.setndefault.return_value = '~/.config/mpd/mpd.conf'
    with mock.patch('jukebox.cfghandler.get_handler', return_value=fake_cfg):
        sys.modules.pop('components.player', None)
        import components.player as player  # noqa: WPS433
        yield player
        player.set_active_player('mpd')


def test_set_active_player_unconditional(player_module):
    assert player_module.set_active_player('spotify') is True
    assert player_module.get_active_player() == 'spotify'


def test_set_active_player_cas_succeeds(player_module):
    player_module.set_active_player('mpd')
    ok = player_module.set_active_player('spotify', expected_current='mpd')
    assert ok is True
    assert player_module.get_active_player() == 'spotify'


def test_set_active_player_cas_rejects_mismatch(player_module):
    player_module.set_active_player('spotify')
    ok = player_module.set_active_player('mpd', expected_current='podcast')
    assert ok is False
    # State unchanged.
    assert player_module.get_active_player() == 'spotify'


def test_concurrent_cas_has_deterministic_final_state(player_module):
    """Two threads race to claim the player via CAS from a common start state.

    Both start from 'mpd'; one tries to install 'spotify', the other 'podcast'.
    Exactly one CAS must succeed; the loser must observe the winner's value
    when it reads back, and the final state must equal the winner's value.
    """
    player_module.set_active_player('mpd')

    barrier = threading.Barrier(2)
    results = {}

    def claim(target):
        barrier.wait()
        results[target] = player_module.set_active_player(target, expected_current='mpd')

    t1 = threading.Thread(target=claim, args=('spotify',))
    t2 = threading.Thread(target=claim, args=('podcast',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    winners = [k for k, v in results.items() if v]
    losers = [k for k, v in results.items() if not v]
    assert len(winners) == 1, f"expected exactly one CAS winner, got {results}"
    assert len(losers) == 1
    assert player_module.get_active_player() == winners[0]


def test_no_torn_reads_under_contention(player_module):
    """A reader thread polling get_active_player while writers churn must
    only ever observe valid strings (or None) — never a half-written value."""
    valid = {'mpd', 'spotify', 'podcast', None}
    observed = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            observed.append(player_module.get_active_player())

    def writer():
        for _ in range(2000):
            player_module.set_active_player('spotify')
            player_module.set_active_player('mpd')

    r = threading.Thread(target=reader)
    w1 = threading.Thread(target=writer)
    w2 = threading.Thread(target=writer)
    r.start()
    w1.start()
    w2.start()
    w1.join()
    w2.join()
    stop.set()
    r.join()

    assert all(v in valid for v in observed)
    assert len(observed) > 0
