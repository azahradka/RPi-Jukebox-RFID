# -*- coding: utf-8 -*-
"""Tests for :class:`components.playermpd.mpd_client.MPDClientWrapper`.

Exercise the wrapper in isolation using a hand-rolled stub client so we
can assert connect-on-enter, RLock re-entrancy, error swallowing in
``call_with_retry``, and the suppression of the "already connected"
ConnectionError specifically (vs. propagating other errors).
"""

import threading


class _FakeClient:
    """Minimal stand-in for ``mpd.MPDClient`` used by these tests."""

    def __init__(self):
        self.connect_calls = []
        self.disconnect_calls = 0
        self.connected = False
        # Errors to raise from connect(); list popped on each call.
        self.connect_errors = []
        self.cmd_log = []

    def connect(self, host, port):
        self.connect_calls.append((host, port))
        if self.connect_errors:
            raise self.connect_errors.pop(0)
        self.connected = True

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False

    def status(self):
        self.cmd_log.append('status')
        return {'state': 'play'}

    def boom(self):
        raise RuntimeError('mpd unhappy')


def test_enter_acquires_lock_and_connects(mpd_client_module):
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'localhost', 6600)

    with w as got:
        assert got is w
        assert fake.connect_calls == [('localhost', 6600)]


def test_exit_releases_lock(mpd_client_module):
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'localhost', 6600)
    with w:
        pass
    # After exit a fresh acquire from another thread must succeed.
    other_thread_got_lock = []

    def grab():
        if w.acquire(timeout=0.5):
            other_thread_got_lock.append(True)
            w.release()

    t = threading.Thread(target=grab)
    t.start()
    t.join(timeout=1.0)
    assert other_thread_got_lock == [True]


def test_rlock_is_reentrant(mpd_client_module):
    """The old ``MpdLock`` was an RLock; play_folder relied on re-entering
    the same lock when calling addid in a loop."""
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)
    with w:
        with w:
            # Two connect attempts (one per enter), both fine.
            assert len(fake.connect_calls) == 2


def test_already_connected_error_is_swallowed(mpd_client_module):
    """The ``_try_connect`` path must swallow the "already connected"
    ConnectionError that python-mpd2 raises on a redundant connect()."""
    # Use the module's own _MPD_CONNECTION_ERROR so we match the import
    # branch (real mpd vs. test fallback to builtin ConnectionError).
    err_cls = mpd_client_module._MPD_CONNECTION_ERROR
    fake = _FakeClient()
    fake.connect_errors.append(err_cls('already connected'))
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)

    # Should NOT raise.
    with w:
        pass
    assert fake.connect_calls == [('h', 6600)]


def test_other_connect_errors_propagate(mpd_client_module):
    """Non-ConnectionError exceptions from connect() must propagate so
    the caller can log / surface a real fault."""
    fake = _FakeClient()
    fake.connect_errors.append(OSError('refused'))
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)

    raised = False
    try:
        with w:
            pass
    except OSError:
        raised = True
    assert raised


def test_call_with_retry_returns_command_result(mpd_client_module):
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)
    result = w.call_with_retry(fake.status)
    assert result == {'state': 'play'}
    assert fake.cmd_log == ['status']


def test_call_with_retry_swallows_errors_returns_none(mpd_client_module):
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)
    result = w.call_with_retry(fake.boom)
    assert result is None


def test_call_with_retry_holds_lock_for_duration(mpd_client_module):
    """The lock must be held across the command call — otherwise the
    poll thread could interleave a status() with an RPC's play()."""
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)

    contended = []

    def probe():
        # If the lock is held, this non-blocking acquire fails.
        if not w.acquire(blocking=False):
            contended.append(True)

    def slow_cmd():
        t = threading.Thread(target=probe)
        t.start()
        t.join()
        return 'ok'

    assert w.call_with_retry(slow_cmd) == 'ok'
    assert contended == [True]


def test_disconnect_passes_through(mpd_client_module):
    fake = _FakeClient()
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)
    w.connect()
    w.disconnect()
    assert fake.disconnect_calls == 1


def test_connect_method_calls_underlying(mpd_client_module):
    """``connect()`` (vs. ``_try_connect``) does NOT swallow errors."""
    fake = _FakeClient()
    fake.connect_errors.append(OSError('refused'))
    w = mpd_client_module.MPDClientWrapper(fake, 'h', 6600)
    raised = False
    try:
        w.connect()
    except OSError:
        raised = True
    assert raised
