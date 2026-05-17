# -*- coding: utf-8 -*-
"""Regression tests for ``jukebox.utils.atomic_io``.

Phase 1, fix #2: all three players persist state via the shared atomic
write helper so a crash mid-write cannot truncate the file on disk.
"""

import json
import os
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from jukebox.utils.atomic_io import atomic_write_json, atomic_write_json_safe  # noqa: E402


def test_atomic_write_creates_file(tmp_state_dir):
    target = tmp_state_dir / 'state.json'
    atomic_write_json(target, {'hello': 'world', 'n': 3})
    assert tmp_state_dir.read_json('state.json') == {'hello': 'world', 'n': 3}


def test_atomic_write_overwrites(tmp_state_dir):
    target = tmp_state_dir / 'state.json'
    atomic_write_json(target, {'v': 1})
    atomic_write_json(target, {'v': 2})
    assert tmp_state_dir.read_json('state.json') == {'v': 2}


def test_atomic_write_creates_parent_dir(tmp_state_dir):
    target = tmp_state_dir / 'sub' / 'nested' / 'state.json'
    atomic_write_json(target, {'ok': True})
    assert json.loads(open(target).read()) == {'ok': True}


def test_no_tmp_files_left_after_success(tmp_state_dir):
    target = tmp_state_dir / 'state.json'
    atomic_write_json(target, {'x': 1})
    leftovers = [p.name for p in Path(str(tmp_state_dir)).iterdir()
                 if p.name.endswith('.tmp')]
    assert leftovers == [], f"unexpected leftover tmp files: {leftovers}"


def test_crash_mid_write_leaves_original_intact(tmp_state_dir):
    """If json.dump explodes during the temp write, os.replace must NOT
    have run — the original file is untouched and no tmp is left behind."""
    target = tmp_state_dir / 'state.json'
    atomic_write_json(target, {'good': 'data'})

    class Boom(RuntimeError):
        pass

    def exploding_dump(obj, fp, **kw):
        # Write a few bytes then fail, like a half-completed write.
        fp.write('{"partial":')
        raise Boom("simulated crash")

    with mock.patch('jukebox.utils.atomic_io.json.dump', side_effect=exploding_dump):
        with pytest.raises(Boom):
            atomic_write_json(target, {'new': 'data'})

    # Target is untouched.
    assert tmp_state_dir.read_json('state.json') == {'good': 'data'}
    # No orphan tmp files.
    leftovers = [p.name for p in Path(str(tmp_state_dir)).iterdir()
                 if p.name.endswith('.tmp')]
    assert leftovers == [], f"orphan tmp files after failed write: {leftovers}"


def test_safe_variant_swallows_errors(tmp_state_dir):
    target = tmp_state_dir / 'state.json'
    with mock.patch('jukebox.utils.atomic_io.json.dump',
                    side_effect=RuntimeError('boom')):
        assert atomic_write_json_safe(target, {'x': 1}) is False
    # No file should exist (we never had a prior write).
    assert not os.path.exists(target)


def test_safe_variant_returns_true_on_success(tmp_state_dir):
    target = tmp_state_dir / 'state.json'
    assert atomic_write_json_safe(target, {'x': 1}) is True
    assert tmp_state_dir.read_json('state.json') == {'x': 1}


def test_concurrent_writers_yield_a_valid_file(tmp_state_dir):
    """Multiple threads writing different payloads must always leave the
    target as a valid, parseable JSON object — never half-written."""
    target = tmp_state_dir / 'state.json'

    def writer(payload):
        for _ in range(50):
            atomic_write_json(target, payload)

    payloads = [{'who': name, 'data': list(range(20))} for name in ('a', 'b', 'c')]
    threads = [threading.Thread(target=writer, args=(p,)) for p in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # File parses cleanly and equals one of the payloads.
    with open(target) as f:
        final = json.load(f)
    assert final in payloads
