# -*- coding: utf-8 -*-
"""Tests for :class:`components.playermpd.state_store.MPDStateStore`.

Exercise the store in isolation:

* New-file path seeds the empty schema and persists immediately.
* Existing-file path loads cleanly; missing sub-dicts get back-filled
  defensively (manual edits / older schemas).
* Field accessors round-trip through the lock.
* ``save()`` uses :func:`atomic_write_json_safe` (so a partial write
  never leaves a torn file — verified by inspecting the on-disk JSON).
* Concurrent updates against ``state_lock`` produce no torn snapshots.
"""

import json
import threading


def test_initialises_empty_schema_when_file_absent(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    path = str(tmp_state_dir / 'mps.json')
    store = MPDStateStore(path)

    assert store.player_status == {}
    assert store.audio_folder_status == {}
    # The init path should have persisted the empty schema.
    on_disk = tmp_state_dir.read_json('mps.json')
    assert on_disk == {'player_status': {}, 'audio_folder_status': {}}


def test_loads_existing_state_from_disk(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    path = str(tmp_state_dir / 'mps.json')
    payload = {
        'player_status': {
            'last_played_folder': 'Lullabies',
            'CURRENTSONGPOS': '3',
            'CURRENTFILENAME': 'Lullabies/04.mp3',
        },
        'audio_folder_status': {
            'Lullabies': {'PLAYSTATUS': 'pause', 'ELAPSED': '42.5'},
        },
    }
    with open(path, 'w') as f:
        json.dump(payload, f)

    store = MPDStateStore(path)
    assert store.last_played_folder() == 'Lullabies'
    assert store.last_swiped_folder() == ''  # absent → empty string
    assert store.get_folder_status('Lullabies')['PLAYSTATUS'] == 'pause'


def test_loads_state_backfills_missing_subdicts(state_store_module, tmp_state_dir):
    """A partial file (manual edit, older schema) loads without crashing."""
    MPDStateStore = state_store_module.MPDStateStore
    path = str(tmp_state_dir / 'mps.json')
    with open(path, 'w') as f:
        json.dump({'player_status': {'last_played_folder': 'X'}}, f)

    store = MPDStateStore(path)
    assert store.last_played_folder() == 'X'
    assert store.audio_folder_status == {}  # back-filled


def test_unreadable_file_falls_back_to_empty_schema(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    path = str(tmp_state_dir / 'mps.json')
    with open(path, 'w') as f:
        f.write('{not json')

    store = MPDStateStore(path)
    assert store.player_status == {}


def test_last_swiped_folder_setter_and_clear(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    assert store.last_swiped_folder() == ''
    store.set_last_swiped_folder('Card123')
    assert store.last_swiped_folder() == 'Card123'

    store.clear_last_swiped_folder()
    assert store.last_swiped_folder() == ''


def test_last_played_and_last_swiped_are_independent(state_store_module, tmp_state_dir):
    """Setting one must not disturb the other — first-swipe-after-reboot
    relies on this independence."""
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    store.set_last_played_folder('Resume')
    store.set_last_swiped_folder('Swiped')
    assert store.last_played_folder() == 'Resume'
    assert store.last_swiped_folder() == 'Swiped'

    store.clear_last_swiped_folder()
    assert store.last_played_folder() == 'Resume'  # unchanged
    assert store.last_swiped_folder() == ''


def test_save_persists_atomically(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    path = str(tmp_state_dir / 'mps.json')
    store = MPDStateStore(path)

    store.set_last_played_folder('Mystery')
    store.set_last_swiped_folder('Mystery')
    store.ensure_folder_entry('Mystery')['PLAYSTATUS'] = 'play'
    assert store.save() is True

    on_disk = tmp_state_dir.read_json('mps.json')
    assert on_disk['player_status']['last_played_folder'] == 'Mystery'
    assert on_disk['player_status']['last_swiped_folder'] == 'Mystery'
    assert on_disk['audio_folder_status']['Mystery']['PLAYSTATUS'] == 'play'

    # No leftover temp files (the helper cleans up on success).
    leftovers = list(tmp_state_dir.path.glob('mps.json.*'))
    assert leftovers == []


def test_ensure_folder_entry_creates_and_returns(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    entry = store.ensure_folder_entry('NewFolder')
    entry['PLAYSTATUS'] = 'play'

    # Re-fetching returns the same dict (in-place mutations persist).
    again = store.ensure_folder_entry('NewFolder')
    assert again is entry
    assert again['PLAYSTATUS'] == 'play'


def test_set_current_folder_status_points_reference(state_store_module, tmp_state_dir):
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    entry = store.set_current_folder_status('FolderA')
    entry['ELAPSED'] = '12.3'
    assert store.current_folder_status is entry
    assert store.get_folder_status('FolderA')['ELAPSED'] == '12.3'


def test_state_lock_serialises_concurrent_writes(state_store_module, tmp_state_dir):
    """Two threads write 1000 entries each; no lost updates."""
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    def writer(prefix):
        for i in range(1000):
            with store.state_lock:
                store.audio_folder_status[f'{prefix}_{i}'] = {'PLAYSTATUS': 'play'}

    t1 = threading.Thread(target=writer, args=('a',))
    t2 = threading.Thread(target=writer, args=('b',))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(store.audio_folder_status) == 2000


def test_save_snapshot_is_consistent_under_concurrent_mutation(
    state_store_module, tmp_state_dir,
):
    """Save must serialise a self-consistent snapshot even while another
    thread mutates ``player_status`` — the prior bug (Phase 1 fix #3)
    is now an invariant of the store, not the call site."""
    MPDStateStore = state_store_module.MPDStateStore
    store = MPDStateStore(str(tmp_state_dir / 'mps.json'))

    stop = threading.Event()
    failures = []

    def mutator():
        i = 0
        while not stop.is_set():
            with store.state_lock:
                store.player_status['CURRENTSONGPOS'] = str(i)
                store.player_status['CURRENTFILENAME'] = f'song{i}.mp3'
            i += 1

    def saver():
        while not stop.is_set():
            store.save()
            on_disk = tmp_state_dir.read_json('mps.json')
            pos = on_disk['player_status'].get('CURRENTSONGPOS')
            fname = on_disk['player_status'].get('CURRENTFILENAME')
            if pos is not None and fname is not None:
                expected = f'song{pos}.mp3'
                if fname != expected:
                    failures.append((pos, fname))

    t1 = threading.Thread(target=mutator)
    t2 = threading.Thread(target=saver)
    t1.start()
    t2.start()
    import time
    time.sleep(0.3)
    stop.set()
    t1.join()
    t2.join()

    assert failures == [], f"torn save snapshots: {failures[:3]}"
