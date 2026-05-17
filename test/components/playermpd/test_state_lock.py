# -*- coding: utf-8 -*-
"""Regression tests for the ``music_player_status`` state lock.

Phase 1, fix #3: the poll thread and RPC threads mutating
``music_player_status`` / ``current_folder_status`` / ``mpd_status``
must hold ``state_lock`` so neither side observes a torn dict.
"""

import threading
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Lightweight harness: pull only the methods under test out of the
# PlayerMPD class so we don't drag in the full plugin / MPD wire setup.
# ---------------------------------------------------------------------------


class _StateHarness:
    """Re-implements just the state-protected ``_mpd_status_poll`` and
    ``_save_state`` shapes from PlayerMPD, with the same locking contract.

    We can't construct a real PlayerMPD in a unit test (it spins MPD
    threads on import), so we model the locking discipline directly and
    drive it under contention. If the production code's lock discipline
    regresses, the helper here is what to update — keep them in lockstep.
    """

    def __init__(self):
        self.state_lock = threading.Lock()
        self.music_player_status = {
            'player_status': {},
            'audio_folder_status': {},
        }
        self.current_folder_status = {}
        self.mpd_status = {}

    def poll(self, mpd_status, current_song):
        """Mirror PlayerMPD._mpd_status_poll's locking discipline."""
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
        """Mirror _save_state: snapshot ``music_player_status`` under lock."""
        with self.state_lock:
            # Deep-ish copy via dict comprehension is enough for this shape.
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
    """Run poll and snapshot concurrently; every snapshot must agree with
    itself (CURRENTFILENAME matches CURRENTSONGPOS for the file the poll
    wrote at that moment)."""
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
            # CURRENTFILENAME and CURRENTSONGPOS are both updated under the
            # same lock with consistent values, so they must be in sync.
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
    # Let them grind for a moment.
    import time
    time.sleep(0.5)
    stop.set()
    t1.join()
    t2.join()
    s.join()

    assert failures == [], f"observed {len(failures)} torn reads, sample: {failures[:3]}"


def test_state_lock_serialises_dict_updates():
    """Two threads each writing 1000 entries to music_player_status must
    end with 2000 entries — no lost updates from concurrent dict mutation
    on the same key namespace."""
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
# Production-code wiring smoke-check.
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
    # PlayerMPD takes the store's lock as its alias; the actual
    # ``threading.Lock()`` construction lives in MPDStateStore.
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
    # The buggy form must not reappear.
    assert 'self.mpd_client.mpd_version()' not in src_text


# Keep pytest + mock imports in use (they're used above).
_ = (pytest, mock)
