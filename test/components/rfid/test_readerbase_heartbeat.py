# -*- coding: utf-8 -*-
"""Tests for :class:`ReaderBaseClass` heartbeat behaviour.

Phase 6: ``read_card()`` may block indefinitely (hardware readers
wait for an IRQ). A heartbeat watchdog logs that the reader is still
alive while it's blocked beyond ``wait_for_tag_timeout_s``. The
watchdog is observation-only — it never interrupts ``read_card()`` —
so existing driver implementations stay unaffected.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import pytest

# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))

from components.rfid.readerbase import ReaderBaseClass  # noqa: E402


class _FakeReader(ReaderBaseClass):
    """Minimal concrete reader that blocks until told to return."""

    def __init__(self, wait_for_tag_timeout_s=ReaderBaseClass.WAIT_TIMEOUT_DEFAULT_S):
        super().__init__(
            reader_cfg_key='fake',
            description='FakeReader',
            logger=logging.getLogger('test.fakereader'),
            wait_for_tag_timeout_s=wait_for_tag_timeout_s,
        )
        self.unblock = threading.Event()
        self.read_card_started = threading.Event()
        self.calls = 0

    def read_card(self):
        self.read_card_started.set()
        self.calls += 1
        # Block until the test releases us
        self.unblock.wait(timeout=5.0)
        self.unblock.clear()
        self.read_card_started.clear()
        return 'CARD-1'

    def cleanup(self):
        pass

    def stop(self):
        self.unblock.set()


def test_heartbeat_logs_while_read_card_blocked(caplog):
    """While ``read_card()`` is blocked beyond the timeout, a debug log
    fires periodically.

    Reversion check: revert the ``_heartbeat_thread`` machinery and
    this test sees no heartbeat logs within the deadline.
    """
    # The floor for wait_for_tag_timeout_s is 1.0s. Allow up to 5s
    # for the heartbeat to fire — generous to keep the test stable
    # when the full suite runs under load.
    reader = _FakeReader(wait_for_tag_timeout_s=1.0)
    caplog.set_level(logging.DEBUG, logger='test.fakereader')

    def call_read():
        # Use the context-manager entry that drives the heartbeat
        with reader:
            iter(reader).__next__()

    t = threading.Thread(target=call_read, daemon=True)
    t.start()
    # Wait for read_card to be in the blocking section
    assert reader.read_card_started.wait(timeout=3.0)
    # Give the heartbeat enough time to fire at least once
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if any('still waiting for tag' in r.getMessage()
               for r in caplog.records):
            break
        time.sleep(0.1)

    matched = [r for r in caplog.records
               if 'still waiting for tag' in r.getMessage()]
    assert matched, (
        "Heartbeat log did not fire while read_card was blocked. "
        "Watchdog regressed."
    )
    # Release read_card so the thread exits cleanly
    reader.unblock.set()
    t.join(timeout=3.0)


def test_heartbeat_does_not_interrupt_read_card():
    """The watchdog must not cancel or timeout the blocking read_card.

    Reversion check: if a future change tries to "fix" the watchdog by
    cancelling the read, this test fails because read_card returns
    early without our unblock signal.
    """
    # Floor is 1.0s; wait 1.5s to see at least one heartbeat fire
    # without read_card returning.
    reader = _FakeReader(wait_for_tag_timeout_s=1.0)
    finished = threading.Event()
    result = []

    def call_read():
        with reader:
            result.append(iter(reader).__next__())
        finished.set()

    t = threading.Thread(target=call_read, daemon=True)
    t.start()
    assert reader.read_card_started.wait(timeout=3.0)
    # Wait long enough for at least one heartbeat interval to fire
    time.sleep(1.5)
    assert not finished.is_set(), (
        "read_card returned before the test released it; the watchdog "
        "may have interrupted it (it must not)."
    )
    # Now unblock and confirm result comes through
    reader.unblock.set()
    assert finished.wait(timeout=3.0)
    assert result == ['CARD-1']


def test_heartbeat_uses_configured_timeout():
    """The constructor parameter sets the watchdog interval."""
    reader = _FakeReader(wait_for_tag_timeout_s=42.5)
    assert reader.wait_for_tag_timeout_s == 42.5


def test_heartbeat_floor_at_one_second():
    """Sub-second timeouts are floored to 1.0s to avoid log flooding."""
    reader = _FakeReader(wait_for_tag_timeout_s=0.001)
    assert reader.wait_for_tag_timeout_s == 1.0


def test_heartbeat_inactive_outside_read_card(caplog):
    """Between iterations, the heartbeat must not log — the reader is
    not blocked on a tag wait, it's the runner's between-iter sleep."""
    # Floor is 1.0s; wait > 1.0s so the heartbeat thread definitely
    # checked the active flag at least once.
    reader = _FakeReader(wait_for_tag_timeout_s=1.0)
    caplog.set_level(logging.DEBUG, logger='test.fakereader')

    with reader:
        # Don't enter read_card — just hold the context manager and
        # wait past one heartbeat interval.
        time.sleep(1.3)

    matched = [r for r in caplog.records
               if 'still waiting for tag' in r.getMessage()]
    assert matched == [], (
        "Heartbeat fired outside read_card. The 'active' flag was not "
        "honoured."
    )


def test_default_timeout_is_30_seconds():
    """Phase 6 contract: default heartbeat interval is 30s.

    Reversion check: change the constant and this test fails.
    """
    assert ReaderBaseClass.WAIT_TIMEOUT_DEFAULT_S == 30.0


@pytest.mark.parametrize("input_value,expected", [
    (1.0, 1.0),
    (15.0, 15.0),
    (0.5, 1.0),  # floor
    (60, 60.0),
])
def test_timeout_normalisation(input_value, expected):
    reader = _FakeReader(wait_for_tag_timeout_s=input_value)
    assert reader.wait_for_tag_timeout_s == expected
