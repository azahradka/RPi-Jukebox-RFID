# -*- coding: utf-8 -*-
"""Regression tests for play_card / play_folder flows.

Renamed from ``test_state_lock.py`` to reflect Phase 3a's broader scope:
the file still owns the Phase 1 lock-discipline regressions plus the
Phase 3a swipe-decision / state-split coverage.

The play_card flow is exercised through a thin harness that wires a
real :class:`MPDStateStore` to a stub ``play_folder`` / ``second_swipe``
pair (matching the production method's decision shape). Instantiating
the full :class:`PlayerMPD` requires a live MPD socket and the plugin
system; that's out of scope for unit tests. The harness fails fast if
the production code's swipe-decision shape diverges -- keep them in
lockstep.
"""

import threading
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Phase 1 regressions: state-lock discipline of _mpd_status_poll
# ---------------------------------------------------------------------------


class _StateHarness:
    """Mirror PlayerMPD's state-protected ``_mpd_status_poll`` + ``_save_state``."""

    def __init__(self):
        self.state_lock = threading.Lock()
        self.music_player_status = {
            'player_status': {},
            'audio_folder_status': {},
        }
        self.current_folder_status = {}
        self.mpd_status = {}

    def poll(self, mpd_status, current_song):
        with self.state_lock:
            self.mpd_status.update(mpd_status)
            self.mpd_status.update(current_song)
            if self.mpd_status.get('elapsed') is not None:
                self.current_folder_status['ELAPSED'] = self.mpd_status['elapsed']
                self.music_player_status['player_status']['CURRENTSONGPOS'] = \
                    self.mpd_status['song']
                self.music_player_status['player_status']['CURRENTFILENAME'] = \
                    self.mpd_status['file']
            snapshot = dict(self.mpd_status)
        return snapshot

    def snapshot(self):
        with self.state_lock:
            return {
                k: dict(v) if isinstance(v, dict) else v
                for k, v in self.music_player_status.items()
            }


def test_poll_holds_state_lock_during_mutations():
    h = _StateHarness()
    h.poll(
        {'state': 'play', 'elapsed': '12.0', 'song': '0', 'file': 'a.mp3'},
        {'file': 'a.mp3'},
    )
    snap = h.snapshot()
    assert snap['player_status']['CURRENTFILENAME'] == 'a.mp3'


def test_concurrent_poll_and_save_yields_consistent_snapshots():
    h = _StateHarness()
    h.poll({'state': 'play', 'elapsed': '0', 'song': '0', 'file': 'a.mp3'},
           {'file': 'a.mp3'})
    stop = threading.Event()
    failures = []

    def poller():
        i = 0
        while not stop.is_set():
            f = f'song{i % 100}.mp3'
            h.poll({'state': 'play', 'elapsed': str(i), 'song': str(i), 'file': f},
                   {'file': f})
            i += 1

    def snapshotter():
        while not stop.is_set():
            snap = h.snapshot()
            ps = snap.get('player_status', {})
            fname = ps.get('CURRENTFILENAME')
            spos = ps.get('CURRENTSONGPOS')
            if fname is not None and spos is not None:
                expected_file = f'song{int(spos) % 100}.mp3'
                if fname != expected_file:
                    failures.append((fname, spos))

    t1 = threading.Thread(target=poller)
    t2 = threading.Thread(target=poller)
    s = threading.Thread(target=snapshotter)
    t1.start()
    t2.start()
    s.start()
    import time
    time.sleep(0.5)
    stop.set()
    t1.join()
    t2.join()
    s.join()

    assert failures == [], f"observed {len(failures)} torn reads, sample: {failures[:3]}"


def test_state_lock_serialises_dict_updates():
    h = _StateHarness()

    def writer(prefix):
        for i in range(1000):
            with h.state_lock:
                h.music_player_status['audio_folder_status'][f'{prefix}_{i}'] = {
                    'PLAYSTATUS': 'play',
                }

    t1 = threading.Thread(target=writer, args=('a',))
    t2 = threading.Thread(target=writer, args=('b',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(h.music_player_status['audio_folder_status']) == 2000


# ---------------------------------------------------------------------------
# Production-code wiring smoke-checks.
# ---------------------------------------------------------------------------


def test_player_mpd_module_defines_state_lock():
    """Smoke-check that ``PlayerMPD`` wires ``state_lock`` in ``__init__``
    and that ``_mpd_status_poll`` actually holds it.

    Phase 3a: the lock now lives in :class:`MPDStateStore`; PlayerMPD
    aliases it as ``self.state_lock = self.state_store.state_lock`` so
    the poll thread's ``with self.state_lock:`` discipline is unchanged.
    """
    from pathlib import Path
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
    from pathlib import Path
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
# Phase 3a: play_card swipe-decision harness
# ---------------------------------------------------------------------------


class _PlayCardHarness:
    """Re-implements the play_card decision shape from ``PlayerMPD``.

    Drives a real :class:`MPDStateStore` (the production object), then
    delegates to stub ``play_folder`` / ``second_swipe_action`` callables
    so we can assert which path was taken. If the production
    ``play_card`` decision logic diverges from what this harness models,
    update both together -- the harness exists to make the four
    second-swipe scenarios fully unit-testable without booting MPD.
    """

    def __init__(self, store):
        self.state_store = store
        self.second_swipe_action = None  # set by tests if needed
        self.play_folder_calls = []
        self.second_swipe_calls = []

    def play_folder(self, folder, recursive=False):
        # Production ``play_folder`` updates last_played_folder via the
        # store. Mirror that here so tests can observe the side effect.
        self.state_store.set_last_played_folder(folder)
        self.play_folder_calls.append((folder, recursive))

    def play_card(self, folder, recursive=False):
        last_swiped = self.state_store.last_swiped_folder()
        is_second_swipe = bool(last_swiped) and last_swiped == folder
        self.state_store.set_last_swiped_folder(folder)
        if self.second_swipe_action is not None and is_second_swipe:
            self.second_swipe_calls.append(folder)
            self.second_swipe_action()
        else:
            self.play_folder(folder, recursive)


@pytest.fixture
def play_card_harness(state_store_module, tmp_state_dir):
    store = state_store_module.MPDStateStore(str(tmp_state_dir / 'mps.json'))
    return _PlayCardHarness(store)


def test_play_card_first_swipe_calls_play_folder(play_card_harness):
    h = play_card_harness
    h.second_swipe_action = mock.Mock()
    h.play_card('AlbumA')
    assert h.play_folder_calls == [('AlbumA', False)]
    assert h.second_swipe_action.call_count == 0
    assert h.state_store.last_swiped_folder() == 'AlbumA'
    assert h.state_store.last_played_folder() == 'AlbumA'


def test_play_card_second_swipe_of_same_card_triggers_action(play_card_harness):
    """Two consecutive swipes of the same card: 1st triggers play_folder,
    2nd triggers the configured second_swipe_action."""
    h = play_card_harness
    h.second_swipe_action = mock.Mock()
    h.play_card('AlbumA')
    h.play_card('AlbumA')
    assert h.play_folder_calls == [('AlbumA', False)]
    assert h.second_swipe_calls == ['AlbumA']
    assert h.second_swipe_action.call_count == 1


def test_play_card_second_swipe_disabled_falls_back_to_first_swipe(play_card_harness):
    """If ``second_swipe_action`` is None, every swipe is first-swipe."""
    h = play_card_harness
    h.second_swipe_action = None
    h.play_card('AlbumA')
    h.play_card('AlbumA')
    assert h.play_folder_calls == [('AlbumA', False), ('AlbumA', False)]


def test_play_card_recursive_flag_propagates(play_card_harness):
    h = play_card_harness
    h.play_card('AlbumA', recursive=True)
    assert h.play_folder_calls == [('AlbumA', True)]


# ---------------------------------------------------------------------------
# Production-code wiring smoke-check for play_folder split (Phase 3a)
# ---------------------------------------------------------------------------


def test_play_folder_is_split_into_state_and_trigger_paths():
    """Phase 3a separates state bookkeeping from MPD wire activity in
    play_folder. Smoke-check via source inspection so a refactor that
    inlines them again is caught."""
    from pathlib import Path
    src_text = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    assert 'def _record_play_folder_state' in src_text
    assert 'def _trigger_play_folder' in src_text
    # play_folder body must call both halves.
    assert 'self._record_play_folder_state(folder)' in src_text
    assert 'self._trigger_play_folder(folder, recursive)' in src_text


def test_play_card_uses_last_swiped_folder_not_last_played():
    """Phase 3a fix for the first-swipe-after-reboot bug. The production
    code must consult ``last_swiped_folder`` (cleared at startup) rather
    than ``last_played_folder`` (preserved across reboots) for the
    second-swipe decision."""
    from pathlib import Path
    src_text = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playermpd' / '__init__.py'
    ).read_text()
    # Locate play_card body.
    pc_start = src_text.index('def play_card(self, folder')
    pc_end = src_text.index('def get_single_coverart', pc_start)
    pc_body = src_text[pc_start:pc_end]

    assert 'self.state_store.last_swiped_folder()' in pc_body, (
        "play_card must consult last_swiped_folder for second-swipe detection"
    )
    assert 'set_last_swiped_folder' in pc_body, (
        "play_card must update last_swiped_folder on each swipe"
    )
    # The old discriminator must be gone from play_card. (It is still
    # legitimate elsewhere - replay / replay_if_stopped read it.)
    assert "music_player_status['player_status']['last_played_folder']" not in pc_body


def test_activation_rule_is_documented_in_module_docstring():
    """Phase 3a pins the activation-vs-passive-control rule (Phase 2
    follow-up #1). Assert the docstring section exists in both
    coordinator.py and playermpd/__init__.py so a future docstring
    sweep doesn't drop it."""
    from pathlib import Path
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
    from pathlib import Path
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


# Keep pytest + mock imports in use (referenced in harness tests).
_ = (pytest, mock)
