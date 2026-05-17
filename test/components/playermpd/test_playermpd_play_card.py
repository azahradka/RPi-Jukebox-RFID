# -*- coding: utf-8 -*-
"""Regression tests for play_card / play_folder flows (Phase 3a).

Renamed from ``test_state_lock.py`` to reflect Phase 3a's broader scope:
the file still owns the Phase 1 lock-discipline regressions plus the
Phase 3a source-grep checks that complement the behavioural tests for
``decide_swipe`` in :mod:`test_decide_swipe`.

Reviewer note (PR #5): the prior revisions of this file used a
``_PlayCardHarness`` that re-implemented production's swipe decision
and then asserted on the harness. That meant reverting production
would have left the tests green. Phase 3a extracts the decision into
``decide_swipe`` (state_store.py); the behavioural coverage now lives
in :mod:`test_decide_swipe` and :mod:`test_playermpd_second_swipe`,
both of which call production code directly. The source-grep checks
below remain as belt-and-braces against accidental inlining /
re-introduction of the buggy discriminator.
"""

from pathlib import Path


# ---------------------------------------------------------------------------
# Production-code wiring smoke-checks (source greps).
# ---------------------------------------------------------------------------


def test_player_mpd_module_defines_state_lock():
    """Smoke-check that ``PlayerMPD`` wires ``state_lock`` in ``__init__``
    and that ``_mpd_status_poll`` actually holds it.

    Phase 3a: the lock now lives in :class:`MPDStateStore`; PlayerMPD
    aliases it as ``self.state_lock = self.state_store.state_lock`` so
    the poll thread's ``with self.state_lock:`` discipline is unchanged.
    """
    repo_root = Path(__file__).resolve().parents[3]
    init_text = (
        repo_root / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    store_text = (
        repo_root / 'src' / 'jukebox' / 'components' / 'playermpd' / 'state_store.py'
    ).read_text()
    assert 'self.state_lock = self.state_store.state_lock' in init_text
    assert 'self.state_lock = threading.Lock()' in store_text
    assert 'with self.state_lock:' in init_text


def test_player_mpd_get_player_type_and_version_uses_attribute():
    """``mpd_version`` is an attribute on python-mpd2; the prior code
    called it ``mpd_version()`` which raised TypeError on the real
    client. Phase 1 fix: assert the call site reads the attribute."""
    source_path = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    )
    src_text = source_path.read_text()
    assert 'value = self.mpd_client.mpd_version\n' in src_text, (
        "expected attribute access self.mpd_client.mpd_version (no parens) "
        "in get_player_type_and_version"
    )
    assert 'self.mpd_client.mpd_version()' not in src_text


# ---------------------------------------------------------------------------
# Phase 3a: play_card source-grep guards (behaviour lives in
# test_decide_swipe.py and test_playermpd_second_swipe.py).
# ---------------------------------------------------------------------------


def test_play_folder_is_split_into_state_and_trigger_paths():
    """Phase 3a separates state bookkeeping from MPD wire activity in
    play_folder. Smoke-check via source inspection so a refactor that
    inlines them again is caught."""
    src_text = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    assert 'def _record_play_folder_state' in src_text
    assert 'def _trigger_play_folder' in src_text
    # play_folder body must call both halves.
    assert 'self._record_play_folder_state(folder)' in src_text
    assert 'self._trigger_play_folder(folder, recursive)' in src_text


def test_play_card_delegates_to_decide_swipe():
    """Phase 3a (reviewer ask #1): play_card must call ``decide_swipe``
    rather than re-deriving the swipe rule inline. This is what makes
    the behavioural tests in :mod:`test_decide_swipe` regression-locks
    on the bug fix; if play_card inlines the rule again, the production-
    coverage chain breaks."""
    src_text = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    pc_start = src_text.index('def play_card(self, folder')
    pc_end = src_text.index('def get_single_coverart', pc_start)
    pc_body = src_text[pc_start:pc_end]

    assert 'decide_swipe(' in pc_body, (
        "play_card must call decide_swipe(...) so the swipe rule has a "
        "single source of truth"
    )
    assert 'SwipeDecision.SECOND_TOGGLE' in pc_body, (
        "play_card must branch on the SwipeDecision enum"
    )
    # The old discriminator must be gone from play_card. (It is still
    # legitimate elsewhere - replay / replay_if_stopped read it.)
    assert "music_player_status['player_status']['last_played_folder']" not in pc_body


def test_activation_rule_is_documented_in_module_docstring():
    """Phase 3a pins the activation-vs-passive-control rule (Phase 2
    follow-up #1). Assert the docstring section exists in both
    coordinator.py and playermpd/__init__.py so a future docstring
    sweep doesn't drop it."""
    repo_root = Path(__file__).resolve().parents[3]
    init_text = (
        repo_root / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    coord_text = (
        repo_root / 'src' / 'jukebox' / 'components' / 'player' / 'coordinator.py'
    ).read_text()
    assert 'Activation vs. passive control' in init_text
    assert 'Activation vs. passive control' in coord_text


def test_activation_call_set_matches_documented_rule():
    """Smoke-check that the RPCs documented as activation events do
    call ``_activate_mpd()``, and the passive ones do not. This is a
    grep-level test -- a behavioural test would need a full PlayerMPD
    instance which we can't construct in unit scope."""
    src_text = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()

    def body_of(method_name: str) -> str:
        start = src_text.index(f'def {method_name}(')
        # Next blank-line-then-def or end-of-class
        after = src_text.find('\n    @plugs.tag', start + 1)
        if after == -1:
            after = src_text.find('\n    def ', start + 1)
        return src_text[start:after if after > 0 else len(src_text)]

    # Activation events must call _activate_mpd().
    for name in ('play', 'play_single', 'resume', 'play_album'):
        assert 'self._activate_mpd()' in body_of(name), (
            f"{name} is documented as an activation event but does not "
            f"call self._activate_mpd()"
        )
    # ``_trigger_play_folder`` is the activation-bearing half of
    # play_folder (the state-update half does not touch the wire).
    assert 'self._activate_mpd()' in body_of('_trigger_play_folder')

    # Passive controls must NOT call _activate_mpd().
    for name in ('stop', 'pause', 'toggle', 'shuffle', 'repeat', 'seek', 'rewind'):
        assert 'self._activate_mpd()' not in body_of(name), (
            f"{name} is documented as passive but calls self._activate_mpd() "
            f"-- this would silently steal playback from another backend"
        )
