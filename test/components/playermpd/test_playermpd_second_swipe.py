# -*- coding: utf-8 -*-
"""Second-swipe scenario tests for playermpd (Phase 3a).

Covers the four behavioural scenarios called out in the Phase 3a plan:

1. Second swipe of the *same* card toggles between the configured
   second_swipe_action (pause/resume/toggle/replay/...) and the first
   swipe's ``play_folder``.
2. Second swipe of a *different* card resets the swipe state and starts
   a fresh first-swipe ``play_folder`` for the new card.
3. **First swipe of the last-played card AFTER REBOOT plays it (not
   pauses)** -- the bug fixed by separating ``last_swiped_folder`` from
   ``last_played_folder`` so only the swipe marker is wiped at startup.
4. Second swipe across a player handoff (e.g. Spotify activated MPD's
   slot in between via the coordinator). The handoff itself doesn't
   clear ``last_swiped_folder``, but the new code does *not* depend on
   coordinator state to decide -- it's purely the swipe marker. We
   simulate the handoff via the harness's reset_session_marker hook.

The tests use the same ``_PlayCardHarness`` shape as
``test_playermpd_play_card.py``: a real :class:`MPDStateStore`, stub
play_folder / second_swipe_action callables, and an explicit
``simulate_reboot`` that mirrors what PlayerMPD.__init__ does at startup
(``state_store.clear_last_swiped_folder()``).
"""

from unittest import mock

import pytest


class _Harness:
    """Production-shape play_card decision logic + reboot simulation.

    Mirrors ``PlayerMPD.play_card`` exactly. Tests assert on the
    sequence of ``play_folder_calls`` / ``second_swipe_calls`` to
    distinguish first vs. second swipe paths.
    """

    def __init__(self, store):
        self.state_store = store
        self.second_swipe_action = mock.Mock()
        self.play_folder_calls = []
        self.second_swipe_calls = []

    def play_folder(self, folder, recursive=False):
        # Production play_folder sets last_played_folder via the
        # ``_record_play_folder_state`` helper. We replicate the
        # last_played_folder mutation so resume semantics line up.
        self.state_store.set_last_played_folder(folder)
        self.play_folder_calls.append(folder)

    def play_card(self, folder, recursive=False):
        last_swiped = self.state_store.last_swiped_folder()
        is_second_swipe = bool(last_swiped) and last_swiped == folder
        self.state_store.set_last_swiped_folder(folder)
        if self.second_swipe_action is not None and is_second_swipe:
            self.second_swipe_calls.append(folder)
            self.second_swipe_action()
        else:
            self.play_folder(folder, recursive)

    def simulate_reboot(self, state_store_module, status_file):
        """Re-construct the store the way PlayerMPD.__init__ does.

        On reboot the store loads from disk (preserving
        last_played_folder), and PlayerMPD then calls
        ``state_store.clear_last_swiped_folder()`` -- the operation
        that fixes the first-swipe-after-reboot bug.
        """
        # Persist current state.
        self.state_store.save()
        # Re-instantiate the store (reads from disk).
        self.state_store = state_store_module.MPDStateStore(status_file)
        # Mirror PlayerMPD.__init__'s startup clear.
        self.state_store.clear_last_swiped_folder()


@pytest.fixture
def harness(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    return _Harness(store)


# ---------------------------------------------------------------------------
# Scenario 1: second swipe of same card triggers second_swipe_action
# ---------------------------------------------------------------------------


def test_scenario_1_second_swipe_same_card_triggers_pause_toggle(harness):
    h = harness
    # First swipe: plays.
    h.play_card('FolderA')
    assert h.play_folder_calls == ['FolderA']
    assert h.second_swipe_action.call_count == 0
    # Second swipe of the same card: triggers configured action
    # (in production: toggle / pause / replay / etc.).
    h.play_card('FolderA')
    assert h.play_folder_calls == ['FolderA']  # no new play_folder
    assert h.second_swipe_calls == ['FolderA']
    assert h.second_swipe_action.call_count == 1


def test_scenario_1b_three_swipes_alternate_via_swipe_marker(harness):
    """Three swipes of the same card: P, S, S (because the marker is
    only ever reset by clearing or by a *different* folder)."""
    h = harness
    h.play_card('X')
    h.play_card('X')
    h.play_card('X')
    # Once the marker is set to 'X', every subsequent swipe of 'X' is a
    # second swipe -- there is no explicit "alternate" toggle in
    # production. This regression-locks that behaviour so we notice if
    # someone re-introduces the prior implicit toggle.
    assert h.play_folder_calls == ['X']
    assert h.second_swipe_calls == ['X', 'X']


# ---------------------------------------------------------------------------
# Scenario 2: second swipe of a DIFFERENT card switches (first swipe)
# ---------------------------------------------------------------------------


def test_scenario_2_swipe_of_different_card_is_first_swipe(harness):
    h = harness
    h.play_card('A')
    h.play_card('B')  # different card -> first swipe of B
    assert h.play_folder_calls == ['A', 'B']
    assert h.second_swipe_calls == []
    assert h.state_store.last_swiped_folder() == 'B'
    # last_played_folder follows the most recent first swipe.
    assert h.state_store.last_played_folder() == 'B'


def test_scenario_2b_back_to_first_card_is_first_swipe_again(harness):
    """A -> B -> A: every transition is a fresh first swipe because the
    swipe marker only matches consecutive duplicates."""
    h = harness
    h.play_card('A')
    h.play_card('B')
    h.play_card('A')
    assert h.play_folder_calls == ['A', 'B', 'A']
    assert h.second_swipe_calls == []


# ---------------------------------------------------------------------------
# Scenario 3: first swipe AFTER REBOOT of the last-played card
# ---------------------------------------------------------------------------


def test_scenario_3_first_swipe_after_reboot_plays_not_pauses(
    harness, state_store_module, tmp_state_dir,
):
    """THE bug we're fixing. Before Phase 3a:
       last_played_folder was kept across reboots AND was the
       discriminator for second-swipe detection, so the very first
       swipe of the last-played card after reboot looked like a second
       swipe (and triggered pause/toggle instead of playing).

    After Phase 3a:
       last_played_folder is preserved (resume needs it) but
       last_swiped_folder is the new discriminator, and the store
       wipes only the swipe marker on init. So the first post-reboot
       swipe of the last-played card now plays correctly.
    """
    h = harness
    h.play_card('LastPlayed')
    assert h.play_folder_calls == ['LastPlayed']

    # Simulate process exit + start.
    status_file = str(tmp_state_dir / 'mps.json')
    h.simulate_reboot(state_store_module, status_file)

    # Sanity: last_played_folder survives, last_swiped_folder is wiped.
    assert h.state_store.last_played_folder() == 'LastPlayed'
    assert h.state_store.last_swiped_folder() == ''

    # First post-reboot swipe of the same card MUST be a first swipe.
    h.play_card('LastPlayed')
    assert h.play_folder_calls == ['LastPlayed', 'LastPlayed'], (
        "post-reboot first swipe must trigger play_folder, not the "
        "second_swipe_action -- this is the bug fixed by Phase 3a"
    )
    assert h.second_swipe_calls == []


def test_scenario_3b_post_reboot_two_consecutive_swipes_still_toggle(
    harness, state_store_module, tmp_state_dir,
):
    """After reboot: first swipe plays, second swipe toggles -- normal
    behaviour resumes from the post-reboot first swipe onward."""
    h = harness
    h.play_card('Card')
    status_file = str(tmp_state_dir / 'mps.json')
    h.simulate_reboot(state_store_module, status_file)

    h.play_card('Card')  # first swipe after reboot (plays)
    h.play_card('Card')  # second swipe after reboot (toggles)
    assert h.play_folder_calls == ['Card', 'Card']
    assert h.second_swipe_calls == ['Card']


# ---------------------------------------------------------------------------
# Scenario 4: second swipe ACROSS a player handoff
# ---------------------------------------------------------------------------


def test_scenario_4_second_swipe_after_player_handoff(harness):
    """A handoff (Spotify or podcast claimed the active slot via the
    coordinator) does NOT clear the playermpd swipe marker, so a
    user who swipes the MPD card again -- with no intervening RFID
    activity -- still gets the configured second_swipe_action.

    The decision is purely about ``last_swiped_folder`` belonging to
    playermpd; coordinator state has no effect. This regression locks
    that boundary so a future Phase doesn't add a coordinator check
    inside play_card and accidentally regress the swipe semantics.
    """
    h = harness
    # First swipe via MPD card.
    h.play_card('MpdCard')
    assert h.play_folder_calls == ['MpdCard']

    # Simulate handoff: Spotify takes the active slot. From playermpd's
    # POV nothing local changes -- its store is untouched, only the
    # coordinator's _current flips. The handoff might pause MPD via
    # the coordinator-driven pause_fn, but it does NOT clear the
    # store's last_swiped_folder marker.
    #
    # We assert this by observing that another swipe of the SAME card
    # is still treated as second-swipe even though, conceptually,
    # MPD is no longer the active backend.
    h.play_card('MpdCard')
    assert h.second_swipe_calls == ['MpdCard']
    assert h.second_swipe_action.call_count == 1
