# -*- coding: utf-8 -*-
"""Second-swipe scenario sequencing tests (Phase 3a).

Where :mod:`test_decide_swipe` covers each scenario in isolation, this
module exercises multi-swipe *sequences* against the real production
``decide_swipe`` + ``MPDStateStore`` pair, plus the mutation step
(``set_last_swiped_folder``) that ``PlayerMPD.play_card`` performs
after every decision. The sequencer below is intentionally minimal:
it does what play_card does and no more, so any divergence between
this fixture and play_card is a bug in play_card -- not in a parallel
implementation.

Reviewer note (PR #5): prior revisions used ``_Harness`` which
re-implemented the decision rule. That meant the four behavioural
scenarios were locked against the harness, not against production.
The fixture below calls ``decide_swipe`` directly and asserts on its
return value plus the resulting store state. Reverting the bug fix
breaks ``test_scenario_3_first_swipe_after_reboot_plays_not_pauses``.
"""

from unittest import mock

import pytest


class _SwipeSequencer:
    """Drive a sequence of swipes through production ``decide_swipe``.

    Records the decision returned for each swipe and (separately)
    mutates the store via ``set_last_swiped_folder`` -- exactly what
    ``PlayerMPD.play_card`` does after consulting decide_swipe.
    Also tracks the ``last_played_folder`` writes that
    ``_record_play_folder_state`` would perform when a FIRST swipe
    is dispatched to ``play_folder``.

    The sequencer does NOT re-implement the decision rule -- it
    delegates to the real ``decide_swipe`` from state_store.py.
    """

    def __init__(self, state_store_module, store):
        self.state_store = store
        self.decide_swipe = state_store_module.decide_swipe
        self.SwipeDecision = state_store_module.SwipeDecision
        self.second_swipe_action = mock.Mock()
        # Recorded outcomes for assertions.
        self.decisions = []          # list[SwipeDecision]
        self.first_swipe_folders = []
        self.second_swipe_folders = []

    def play_card(self, folder):
        decision = self.decide_swipe(
            self.state_store, folder, self.second_swipe_action,
        )
        self.decisions.append(decision)
        # Mirror PlayerMPD.play_card: the marker update happens AFTER
        # the decision, regardless of which branch we take.
        self.state_store.set_last_swiped_folder(folder)
        if decision is self.SwipeDecision.SECOND_TOGGLE:
            self.second_swipe_action()
            self.second_swipe_folders.append(folder)
        else:
            # Mirror what play_folder -> _record_play_folder_state does.
            self.state_store.set_last_played_folder(folder)
            self.first_swipe_folders.append(folder)


@pytest.fixture
def sequencer(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    return _SwipeSequencer(state_store_module, store)


# ---------------------------------------------------------------------------
# Scenario 1: second swipe of same card triggers second_swipe_action
# ---------------------------------------------------------------------------


def test_scenario_1_second_swipe_same_card_triggers_pause_toggle(sequencer):
    s = sequencer
    s.play_card('FolderA')
    s.play_card('FolderA')
    assert s.first_swipe_folders == ['FolderA']
    assert s.second_swipe_folders == ['FolderA']
    assert s.second_swipe_action.call_count == 1


def test_scenario_1b_three_swipes_alternate_via_swipe_marker(sequencer):
    """Three swipes of the same card: F, S, S (because the marker is
    only ever reset by clearing or by a *different* folder). This
    regression-locks that we have NOT re-introduced an implicit toggle."""
    s = sequencer
    s.play_card('X')
    s.play_card('X')
    s.play_card('X')
    assert s.first_swipe_folders == ['X']
    assert s.second_swipe_folders == ['X', 'X']


# ---------------------------------------------------------------------------
# Scenario 2: second swipe of a DIFFERENT card switches (first swipe)
# ---------------------------------------------------------------------------


def test_scenario_2_swipe_of_different_card_is_first_swipe(sequencer):
    s = sequencer
    s.play_card('A')
    s.play_card('B')
    assert s.first_swipe_folders == ['A', 'B']
    assert s.second_swipe_folders == []
    assert s.state_store.last_swiped_folder() == 'B'
    assert s.state_store.last_played_folder() == 'B'


def test_scenario_2b_back_to_first_card_is_first_swipe_again(sequencer):
    """A -> B -> A: every transition is a fresh first swipe because the
    swipe marker only matches consecutive duplicates."""
    s = sequencer
    s.play_card('A')
    s.play_card('B')
    s.play_card('A')
    assert s.first_swipe_folders == ['A', 'B', 'A']
    assert s.second_swipe_folders == []


# ---------------------------------------------------------------------------
# Scenario 3: first swipe AFTER REBOOT of the last-played card
# ---------------------------------------------------------------------------


def test_scenario_3_first_swipe_after_reboot_plays_not_pauses(
    state_store_module, tmp_state_dir,
):
    """End-to-end sequencing of THE bug fix: play, reboot, play again.

    Uses a real :class:`MPDStateStore` re-instantiation (the reboot
    simulation in :mod:`test_decide_swipe` covers the same path in
    isolation; here we verify the full sequencer also sees FIRST after
    the restart). Reverting either ``clear_last_swiped_folder`` or
    the swipe-discriminator change breaks this test.
    """
    status_file = str(tmp_state_dir / 'mps.json')
    store = state_store_module.MPDStateStore(status_file)
    s = _SwipeSequencer(state_store_module, store)

    s.play_card('LastPlayed')
    assert s.first_swipe_folders == ['LastPlayed']

    # Simulate process exit + start.
    s.state_store.save()
    new_store = state_store_module.MPDStateStore(status_file)
    new_store.clear_last_swiped_folder()  # what PlayerMPD.__init__ does

    # Sanity: last_played survives, swipe marker is wiped.
    assert new_store.last_played_folder() == 'LastPlayed'
    assert new_store.last_swiped_folder() == ''

    s2 = _SwipeSequencer(state_store_module, new_store)
    s2.play_card('LastPlayed')
    assert s2.first_swipe_folders == ['LastPlayed'], (
        "post-reboot first swipe must trigger first-swipe (play_folder), "
        "not the second_swipe_action -- this is the bug fixed by Phase 3a"
    )
    assert s2.second_swipe_folders == []


def test_scenario_3b_post_reboot_two_consecutive_swipes_still_toggle(
    state_store_module, tmp_state_dir,
):
    """After reboot: first swipe plays, second swipe toggles -- normal
    behaviour resumes from the post-reboot first swipe onward."""
    status_file = str(tmp_state_dir / 'mps.json')
    store = state_store_module.MPDStateStore(status_file)
    s = _SwipeSequencer(state_store_module, store)
    s.play_card('Card')

    # Reboot.
    s.state_store.save()
    new_store = state_store_module.MPDStateStore(status_file)
    new_store.clear_last_swiped_folder()

    s2 = _SwipeSequencer(state_store_module, new_store)
    s2.play_card('Card')  # first swipe after reboot (plays)
    s2.play_card('Card')  # second swipe after reboot (toggles)
    assert s2.first_swipe_folders == ['Card']
    assert s2.second_swipe_folders == ['Card']


# ---------------------------------------------------------------------------
# Scenario 4: second swipe ACROSS a player handoff
# ---------------------------------------------------------------------------


def test_scenario_4_second_swipe_after_player_handoff(sequencer):
    """A coordinator handoff (Spotify or podcast claimed the active
    slot) does NOT touch the playermpd store, so a user who swipes the
    MPD card again -- with no intervening RFID activity -- still gets
    the configured second_swipe_action.

    The decision is purely about ``last_swiped_folder``; coordinator
    state has no input. This regression locks that boundary so a future
    phase doesn't add a coordinator check inside ``decide_swipe`` and
    accidentally regress the swipe semantics.
    """
    s = sequencer
    s.play_card('MpdCard')
    assert s.first_swipe_folders == ['MpdCard']

    # Handoff happens externally — no change to s.state_store.
    s.play_card('MpdCard')
    assert s.second_swipe_folders == ['MpdCard']
    assert s.second_swipe_action.call_count == 1
