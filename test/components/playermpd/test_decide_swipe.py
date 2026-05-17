# -*- coding: utf-8 -*-
"""Behavioural tests for the play_card swipe decision (Phase 3a).

These tests drive **production code directly** — the real
:func:`components.playermpd.state_store.decide_swipe` against a real
:class:`MPDStateStore` instance — so reverting the bug fix in production
causes failure here. The previous revisions of this suite re-implemented
the decision in a ``_PlayCardHarness`` and would have continued to pass
even if production were rolled back to the buggy form; see reviewer ask
#1 on PR #5.

Coverage is the four behavioural scenarios called out in the Phase 3a
plan:

1. First swipe of an unfamiliar card → ``SwipeDecision.FIRST``.
2. Second swipe of the same card → ``SwipeDecision.SECOND_TOGGLE``.
3. Second swipe of a *different* card → ``SwipeDecision.FIRST``
   (the marker only matches consecutive duplicates).
4. **First swipe after reboot of the last-played card →
   ``SwipeDecision.FIRST``** — THE bug fix. The test re-instantiates
   ``MPDStateStore`` against the same status_file path (simulating a
   process restart) and verifies the new instance's
   ``last_swiped_folder`` is empty while ``last_played_folder``
   survives. ``decide_swipe`` then returns ``FIRST`` for that folder.

Additional edge tests cover the ``second_swipe_action is None`` case
(feature disabled → every swipe is FIRST).
"""

import json
from unittest import mock


# ---------------------------------------------------------------------------
# Scenario 1: first swipe of an unfamiliar card → FIRST
# ---------------------------------------------------------------------------


def test_first_swipe_of_unfamiliar_card_returns_first(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    decide_swipe = state_store_module.decide_swipe
    SwipeDecision = state_store_module.SwipeDecision

    # Fresh store: no prior swipe.
    assert store.last_swiped_folder() == ''
    decision = decide_swipe(store, 'AlbumA', second_swipe_action=mock.Mock())
    assert decision is SwipeDecision.FIRST


# ---------------------------------------------------------------------------
# Scenario 2: second swipe of the same card → SECOND_TOGGLE
# ---------------------------------------------------------------------------


def test_second_swipe_of_same_card_returns_second_toggle(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    decide_swipe = state_store_module.decide_swipe
    SwipeDecision = state_store_module.SwipeDecision

    # First swipe sets the marker (what play_card does after consulting
    # decide_swipe).
    store.set_last_swiped_folder('AlbumA')

    decision = decide_swipe(store, 'AlbumA', second_swipe_action=mock.Mock())
    assert decision is SwipeDecision.SECOND_TOGGLE


# ---------------------------------------------------------------------------
# Scenario 3: second swipe of a DIFFERENT card → FIRST
# ---------------------------------------------------------------------------


def test_second_swipe_of_different_card_returns_first(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    decide_swipe = state_store_module.decide_swipe
    SwipeDecision = state_store_module.SwipeDecision

    store.set_last_swiped_folder('AlbumA')

    decision = decide_swipe(store, 'AlbumB', second_swipe_action=mock.Mock())
    assert decision is SwipeDecision.FIRST


# ---------------------------------------------------------------------------
# Scenario 4: first swipe AFTER REBOOT of the last-played card → FIRST
# ---------------------------------------------------------------------------


def test_first_swipe_after_reboot_of_last_played_card_returns_first(
    state_store_module, tmp_state_dir,
):
    """THE bug fixed by Phase 3a.

    Setup: a user played ``LastPlayed`` in the prior session; the
    process exited (or the Pi rebooted). On startup, ``PlayerMPD`` does:

        self.state_store = MPDStateStore(self.status_file)
        # ... load existing folder status etc ...
        self.state_store.clear_last_swiped_folder()

    Under the prior buggy code the discriminator was
    ``last_played_folder`` (preserved across reboots), so a fresh swipe
    of the SAME card looked like a 2nd swipe and triggered pause/toggle
    instead of play. The fix is to discriminate on
    ``last_swiped_folder`` (cleared by the store / by PlayerMPD.__init__)
    while preserving ``last_played_folder`` for the resume use case.

    This test reproduces that scenario against real production objects:
    write a state file containing ``last_played_folder`` and
    ``last_swiped_folder``, instantiate a NEW ``MPDStateStore`` (the
    reboot), call ``clear_last_swiped_folder`` (what PlayerMPD.__init__
    does), then call ``decide_swipe`` for the last-played folder. Must
    return ``FIRST``.
    """
    MPDStateStore = state_store_module.MPDStateStore
    decide_swipe = state_store_module.decide_swipe
    SwipeDecision = state_store_module.SwipeDecision

    status_file = str(tmp_state_dir / 'mps.json')

    # ---- Pre-reboot session: user played and swiped 'LastPlayed'. ----
    pre_reboot = MPDStateStore(status_file)
    pre_reboot.set_last_played_folder('LastPlayed')
    pre_reboot.set_last_swiped_folder('LastPlayed')
    pre_reboot.save()

    # Sanity: the on-disk file contains both fields. This pins the
    # serialised shape so a future refactor that drops last_played from
    # disk doesn't silently regress the resume use case.
    with open(status_file, 'r') as f:
        on_disk = json.load(f)
    assert on_disk['player_status']['last_played_folder'] == 'LastPlayed'
    assert on_disk['player_status']['last_swiped_folder'] == 'LastPlayed'

    # ---- Reboot: brand-new MPDStateStore against the same path. ----
    post_reboot = MPDStateStore(status_file)

    # The store itself reloads BOTH fields (last_swiped is wiped by
    # PlayerMPD.__init__, not the store ctor — that explicit responsibility
    # split is what makes the resume target persist).
    assert post_reboot.last_played_folder() == 'LastPlayed'
    assert post_reboot.last_swiped_folder() == 'LastPlayed'  # still present on disk

    # PlayerMPD.__init__ clears the swipe marker on every startup.
    post_reboot.clear_last_swiped_folder()
    assert post_reboot.last_played_folder() == 'LastPlayed'  # preserved
    assert post_reboot.last_swiped_folder() == ''            # wiped

    # First post-reboot swipe of the same card MUST be FIRST. This is
    # the contract the bug fix delivers; reverting clear_last_swiped_folder
    # or switching the discriminator back to last_played_folder breaks
    # this assertion.
    decision = decide_swipe(
        post_reboot, 'LastPlayed', second_swipe_action=mock.Mock(),
    )
    assert decision is SwipeDecision.FIRST, (
        "post-reboot first swipe of the last-played card must be FIRST "
        "(this is the Phase 3a bug fix; if decide_swipe returns "
        "SECOND_TOGGLE here, the user gets a pause/toggle instead of "
        "playback)."
    )


# ---------------------------------------------------------------------------
# Edge: second_swipe_action=None → feature disabled → always FIRST
# ---------------------------------------------------------------------------


def test_second_swipe_action_none_forces_first_even_on_repeat(
    state_store_module, tmp_state_dir,
):
    """When the user has not configured a second_swipe_action, repeat
    swipes should re-trigger play (so the card stays useful)."""
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    decide_swipe = state_store_module.decide_swipe
    SwipeDecision = state_store_module.SwipeDecision

    store.set_last_swiped_folder('AlbumA')
    decision = decide_swipe(store, 'AlbumA', second_swipe_action=None)
    assert decision is SwipeDecision.FIRST


# ---------------------------------------------------------------------------
# decide_swipe is read-only on the store
# ---------------------------------------------------------------------------


def test_decide_swipe_does_not_mutate_state_store(state_store_module, tmp_state_dir):
    """The decision function must not call ``set_last_swiped_folder`` —
    that's play_card's responsibility. Asserting purity makes the
    callable safe to reorder around other state operations."""
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    decide_swipe = state_store_module.decide_swipe

    store.set_last_swiped_folder('AlbumA')
    before = store.last_swiped_folder()
    decide_swipe(store, 'AlbumB', second_swipe_action=mock.Mock())
    after = store.last_swiped_folder()
    assert before == after == 'AlbumA'
