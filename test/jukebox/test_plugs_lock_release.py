# -*- coding: utf-8 -*-
"""Tests for ``plugs.drop_module_lock_for_blocking_call``.

Phase 6 / Phase 3b FU#1: ``plugs.call`` holds the module-level RLock
across the entire callable. A plugin doing a long blocking I/O (jingle
WAV playback, ~10-60 s) starves every other RPC until it returns. The
fix is an opt-in context manager that releases the lock around the
blocking section.

These tests exercise the real lock object — not a parallel
re-implementation — so a regression in the drop/restore plumbing fails
them.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

# Make ``src/jukebox`` importable as a package root.
_PKG_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import jukebox.plugs as plugs  # noqa: E402


def test_drop_module_lock_releases_for_other_thread():
    """Other thread can acquire while we're inside the drop block.

    Reversion check: remove ``drop_module_lock_for_blocking_call`` from
    jingle.play (or revert the helper itself) and the blocking section
    holds the lock — this test times out waiting for the other thread.
    """
    # Acquire as the "main RPC" would (mimics what plugs.call's
    # ``with _lock_module`` does).
    acquired_by_other = threading.Event()
    released_to_other = threading.Event()

    def other_thread():
        # Wait until main signals it's inside the drop section
        released_to_other.wait(timeout=2.0)
        # This must succeed quickly (lock is dropped)
        if plugs._lock_module.acquire(timeout=1.0):
            acquired_by_other.set()
            plugs._lock_module.release()

    plugs._lock_module.acquire()
    try:
        t = threading.Thread(target=other_thread, daemon=True)
        t.start()
        with plugs.drop_module_lock_for_blocking_call():
            # Inside the drop section: another thread must be able to
            # acquire the plugs module lock.
            released_to_other.set()
            t.join(timeout=2.0)
        assert acquired_by_other.is_set(), (
            "Other thread could not acquire plugs lock during the "
            "drop-for-blocking-call section."
        )
    finally:
        plugs._lock_module.release()


def test_drop_module_lock_restores_on_exit():
    """Lock count is fully restored after the drop block exits.

    A subsequent thread attempting to acquire must block again.
    """
    plugs._lock_module.acquire()
    try:
        with plugs.drop_module_lock_for_blocking_call():
            pass
        # Still held by this thread after exit — another thread must block.
        other_got_it = threading.Event()

        def other():
            if plugs._lock_module.acquire(timeout=0.2):
                other_got_it.set()
                plugs._lock_module.release()

        t = threading.Thread(target=other, daemon=True)
        t.start()
        t.join(timeout=1.0)
        assert not other_got_it.is_set(), (
            "Lock was not re-acquired by the original thread after "
            "the drop-for-blocking-call section ended."
        )
    finally:
        plugs._lock_module.release()


def test_drop_module_lock_restores_recursion_depth():
    """RLock recursion depth is preserved across drop/restore.

    The original thread acquires N times, drops, re-enters drop block,
    exits, and must still hold the lock N times (verified by being
    able to release N times without error).
    """
    # Acquire 3 times (simulating nested plugs.call invocations on
    # the same thread before reaching the blocking section).
    plugs._lock_module.acquire()
    plugs._lock_module.acquire()
    plugs._lock_module.acquire()
    try:
        with plugs.drop_module_lock_for_blocking_call():
            # During drop, another thread must be able to acquire.
            other_got_it = threading.Event()

            def other():
                if plugs._lock_module.acquire(timeout=1.0):
                    other_got_it.set()
                    plugs._lock_module.release()

            t = threading.Thread(target=other, daemon=True)
            t.start()
            t.join(timeout=2.0)
            assert other_got_it.is_set()
        # After exit, we must still be able to release 3 times — i.e.
        # all 3 recursive acquires were restored.
        plugs._lock_module.release()
        plugs._lock_module.release()
        # Final release in finally.
    finally:
        plugs._lock_module.release()


def test_drop_module_lock_propagates_exception_and_restores():
    """An exception inside the drop block re-acquires the lock before
    propagating, so callers can still safely release their original count."""
    plugs._lock_module.acquire()
    try:
        raised = False
        try:
            with plugs.drop_module_lock_for_blocking_call():
                raise RuntimeError('boom')
        except RuntimeError:
            raised = True
        assert raised
        # Confirm we still hold the lock (another thread must block).
        other_got_it = threading.Event()

        def other():
            if plugs._lock_module.acquire(timeout=0.2):
                other_got_it.set()
                plugs._lock_module.release()

        t = threading.Thread(target=other, daemon=True)
        t.start()
        t.join(timeout=1.0)
        assert not other_got_it.is_set()
    finally:
        plugs._lock_module.release()
