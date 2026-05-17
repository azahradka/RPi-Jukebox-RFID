# -*- coding: utf-8 -*-
"""Tests for the Phase 3c status_publisher_loop split.

The loop is now scaffolding over four single-responsibility methods:

* ``_fetch_status``    — pull current playback from spotipy.
* ``_transform_status`` — turn cached state into MPD-format dict.
* ``_publish_status``  — gate on coordinator + send to publisher.
* ``_handle_status_error_with_backoff`` — choose next interval after err.
* ``_apply_error_backoff`` — apply the consecutive-error curve.

These tests exercise the real production methods on a real
``PlayerSpotify`` instance (bypassing the heavy ``__init__`` only where
needed for isolation). They are reversion-checked: change the interval
constants or break the 429 Retry-After handling and the corresponding
test fails.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from spotipy.exceptions import SpotifyException

from components.playerspotify import PlayerSpotify


# ---------------------------------------------------------------------------
# Bare-bones constructor — skip the full __init__ heavy paths
# ---------------------------------------------------------------------------
def _bare_player(state=None):
    """Construct a PlayerSpotify without running __init__.

    We mutate just enough state for the methods under test to work.
    Avoids the network / file-system side effects of full construction.
    """
    p = PlayerSpotify.__new__(PlayerSpotify)
    p.player_status = state or {
        'state': 'stopped',
        'last_played_uri': None,
        'last_card_uri': None,
        'current_track': None,
        'position_ms': 0,
        'device_id': None,
        'shuffle': False,
        'repeat': 'off',
    }
    p.sp_client = None
    p.status_file = '/tmp/_bare_status.json'
    return p


# ---------------------------------------------------------------------------
# _publish_status: gating on coordinator
# ---------------------------------------------------------------------------
def test_publish_status_skips_send_when_spotify_not_active():
    """If MPD is current, _publish_status is a no-op."""
    p = _bare_player()
    fake_publisher = MagicMock()
    with patch('components.playerspotify.publishing.get_publisher',
               return_value=fake_publisher), \
         patch('components.playerspotify.get_coordinator') as get_coord:
        get_coord.return_value.current.return_value = 'mpd'
        p._publish_status({'state': 'stop'})
    fake_publisher.send.assert_not_called()


def test_publish_status_sends_when_spotify_is_active():
    """If Spotify is current, _publish_status sends the message."""
    p = _bare_player()
    fake_publisher = MagicMock()
    payload = {'state': 'play', 'title': 't'}
    with patch('components.playerspotify.publishing.get_publisher',
               return_value=fake_publisher), \
         patch('components.playerspotify.get_coordinator') as get_coord:
        get_coord.return_value.current.return_value = 'spotify'
        p._publish_status(payload)
    fake_publisher.send.assert_called_once_with('playerstatus', payload)


# ---------------------------------------------------------------------------
# _handle_status_error_with_backoff: 429 vs generic
# ---------------------------------------------------------------------------
def test_handle_status_error_429_with_retry_after_honoured():
    """HTTP 429 returns the server's Retry-After (≥30s)."""
    p = _bare_player()
    exc = SpotifyException(429, -1, 'Too Many', headers={'Retry-After': '120'})
    interval = p._handle_status_error_with_backoff(exc)
    assert interval == 120


def test_handle_status_error_429_floor_30s():
    """Retry-After below 30 is floored to 30 by _get_retry_after."""
    p = _bare_player()
    exc = SpotifyException(429, -1, 'Too Many', headers={'Retry-After': '5'})
    interval = p._handle_status_error_with_backoff(exc)
    assert interval == 30


def test_handle_status_error_429_missing_header_default_30s():
    """No Retry-After header defaults to 30."""
    p = _bare_player()
    exc = SpotifyException(429, -1, 'Too Many', headers={})
    interval = p._handle_status_error_with_backoff(exc)
    assert interval == 30


def test_handle_status_error_generic_returns_base_backoff():
    """Non-429 errors return the base; the loop applies the curve."""
    p = _bare_player()
    exc = SpotifyException(500, -1, 'Server error', headers={})
    interval = p._handle_status_error_with_backoff(exc)
    assert interval == PlayerSpotify._ERROR_BACKOFF_BASE


def test_handle_status_error_non_spotify_exception_returns_base():
    """Any other exception type also falls into the generic branch."""
    p = _bare_player()
    interval = p._handle_status_error_with_backoff(ConnectionError('boom'))
    assert interval == PlayerSpotify._ERROR_BACKOFF_BASE


# ---------------------------------------------------------------------------
# _apply_error_backoff: linear scaling, capped, 429 passthrough
# ---------------------------------------------------------------------------
def test_apply_error_backoff_first_error_returns_base():
    p = _bare_player()
    assert p._apply_error_backoff(
        PlayerSpotify._ERROR_BACKOFF_BASE, consecutive_errors=1
    ) == PlayerSpotify._ERROR_BACKOFF_BASE


def test_apply_error_backoff_scales_with_consecutive_errors():
    p = _bare_player()
    assert p._apply_error_backoff(
        PlayerSpotify._ERROR_BACKOFF_BASE, consecutive_errors=3
    ) == 3 * PlayerSpotify._ERROR_BACKOFF_BASE


def test_apply_error_backoff_caps_at_max():
    p = _bare_player()
    assert p._apply_error_backoff(
        PlayerSpotify._ERROR_BACKOFF_BASE, consecutive_errors=100
    ) == PlayerSpotify._ERROR_BACKOFF_MAX


def test_apply_error_backoff_passes_through_429_retry_after():
    """When base > _ERROR_BACKOFF_BASE (e.g. Retry-After=120) we
    return the supplied value untouched, regardless of error count.
    """
    p = _bare_player()
    assert p._apply_error_backoff(120, consecutive_errors=5) == 120


# ---------------------------------------------------------------------------
# _poll_status_once: adaptive interval depending on state
# ---------------------------------------------------------------------------
def test_poll_status_once_returns_playing_interval_when_playing():
    """state == playing → 1s interval (production constant)."""
    p = _bare_player()
    p.sp_client = MagicMock()
    p.player_status['state'] = 'playing'
    with patch.object(p, '_fetch_status'), \
         patch.object(p, '_publish_status'):
        interval, ok = p._poll_status_once()
    assert ok is True
    assert interval == PlayerSpotify._POLL_INTERVAL_PLAYING


def test_poll_status_once_returns_idle_interval_when_paused():
    p = _bare_player()
    p.sp_client = MagicMock()
    p.player_status['state'] = 'paused'
    with patch.object(p, '_fetch_status'), \
         patch.object(p, '_publish_status'):
        interval, ok = p._poll_status_once()
    assert ok is True
    assert interval == PlayerSpotify._POLL_INTERVAL_IDLE


def test_poll_status_once_returns_idle_interval_when_stopped():
    p = _bare_player()
    p.sp_client = MagicMock()
    p.player_status['state'] = 'stopped'
    with patch.object(p, '_fetch_status'), \
         patch.object(p, '_publish_status'):
        interval, ok = p._poll_status_once()
    assert ok is True
    assert interval == PlayerSpotify._POLL_INTERVAL_IDLE


def test_poll_status_once_no_client_returns_no_client_interval():
    """Without a client the loop still publishes cached state."""
    p = _bare_player()
    p.sp_client = None
    with patch.object(p, '_publish_status') as mock_pub:
        interval, ok = p._poll_status_once()
    assert ok is True
    assert interval == PlayerSpotify._POLL_INTERVAL_NO_CLIENT
    mock_pub.assert_called_once()


def test_poll_status_once_on_429_returns_retry_after_and_not_success():
    """429 path: interval is the server-supplied Retry-After, ok is False."""
    p = _bare_player()
    p.sp_client = MagicMock()
    err = SpotifyException(429, -1, 'rl', headers={'Retry-After': '90'})
    with patch.object(p, '_fetch_status', side_effect=err), \
         patch.object(p, '_publish_status'):
        interval, ok = p._poll_status_once()
    assert ok is False
    assert interval == 90


def test_poll_status_once_on_generic_error_returns_base_and_not_success():
    p = _bare_player()
    p.sp_client = MagicMock()
    err = SpotifyException(500, -1, 'oops', headers={})
    with patch.object(p, '_fetch_status', side_effect=err), \
         patch.object(p, '_publish_status'):
        interval, ok = p._poll_status_once()
    assert ok is False
    assert interval == PlayerSpotify._ERROR_BACKOFF_BASE


def test_poll_status_once_publishes_cached_status_even_on_error():
    """During an error window, the UI still gets the last-known status."""
    p = _bare_player()
    p.sp_client = MagicMock()
    err = SpotifyException(500, -1, 'oops', headers={})
    with patch.object(p, '_fetch_status', side_effect=err), \
         patch.object(p, '_publish_status') as mock_pub:
        p._poll_status_once()
    mock_pub.assert_called_once()


# ---------------------------------------------------------------------------
# Loop-level: backoff curve grows with consecutive errors
# ---------------------------------------------------------------------------
def test_status_publisher_loop_resets_error_counter_on_success():
    """A success cycle resets consecutive_errors → next error uses
    base, not base*N. We exercise this by mocking _poll_status_once to
    yield error, error, success, error and checking sleep calls.
    """
    p = _bare_player()
    p.sp_client = MagicMock()
    import threading
    p.status_thread_stop = threading.Event()
    sleeps = []

    def fake_wait(timeout):
        sleeps.append(timeout)
        if len(sleeps) >= 4:
            p.status_thread_stop.set()
        return False

    p.status_thread_stop.wait = fake_wait

    # Sequence: error, error, success, error
    base = PlayerSpotify._ERROR_BACKOFF_BASE
    results = iter([
        (base, False),   # err: backoff -> base * 1
        (base, False),   # err: backoff -> base * 2
        (1.0, True),     # success: 1s (playing)
        (base, False),   # err: backoff -> base * 1 (counter was reset)
    ])
    with patch.object(p, '_poll_status_once', side_effect=lambda: next(results)):
        p._status_publisher_loop()

    assert sleeps == [base * 1, base * 2, 1.0, base * 1]


def test_status_publisher_loop_429_passthrough_does_not_multiply():
    """An HTTP 429 returns Retry-After directly; the consecutive-error
    curve must not multiply it.
    """
    p = _bare_player()
    p.sp_client = MagicMock()
    import threading
    p.status_thread_stop = threading.Event()
    sleeps = []

    def fake_wait(timeout):
        sleeps.append(timeout)
        if len(sleeps) >= 3:
            p.status_thread_stop.set()
        return False

    p.status_thread_stop.wait = fake_wait

    base = PlayerSpotify._ERROR_BACKOFF_BASE
    results = iter([
        (base, False),   # generic err: backoff base * 1
        (180, False),    # 429 with Retry-After=180; must pass through
        (base, False),   # generic err: backoff base * 3 (counter at 3)
    ])
    with patch.object(p, '_poll_status_once', side_effect=lambda: next(results)):
        p._status_publisher_loop()

    assert sleeps[0] == base
    assert sleeps[1] == 180  # passthrough, NOT 180 * 2
    assert sleeps[2] == base * 3


# ---------------------------------------------------------------------------
# Phase 1 FU#3: no lazy device discovery in the loop entry
# ---------------------------------------------------------------------------
def test_status_publisher_loop_does_not_call_discover_device():
    """The loop entry must not kick off ``_discover_device`` — that
    duplicates the activation-time discovery introduced in Phase 1.

    Reversion check: re-add a ``self._discover_device()`` call at the
    top of ``_status_publisher_loop`` and this test fails.
    """
    p = _bare_player()
    p.sp_client = MagicMock()
    import threading
    p.status_thread_stop = threading.Event()
    p.status_thread_stop.set()  # exit immediately

    discover_calls = []

    def fake_discover():
        discover_calls.append('called')

    p._discover_device = fake_discover
    with patch.object(p, '_poll_status_once', return_value=(1.0, True)):
        p._status_publisher_loop()

    assert discover_calls == [], (
        "status_publisher_loop must not perform lazy device discovery — "
        "Phase 1 ensure_device_for_activation owns that responsibility."
    )


# ---------------------------------------------------------------------------
# Adaptive polling: assert the production constants are the documented values
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('attr,expected', [
    ('_POLL_INTERVAL_PLAYING', 1.0),
    ('_POLL_INTERVAL_IDLE', 5.0),
    ('_POLL_INTERVAL_NO_CLIENT', 10.0),
    ('_ERROR_BACKOFF_BASE', 30.0),
    ('_ERROR_BACKOFF_MAX', 300.0),
    ('_RATE_LIMIT_MIN_BACKOFF', 30.0),
])
def test_polling_constants_pinned_to_meta_plan_values(attr, expected):
    """Meta-plan §3c: 1s playing / 5s idle / 30+s on error.

    Pin the constants so a casual nudge ("let's poll every 2s")
    becomes a visible behaviour change requiring a test update.
    """
    assert getattr(PlayerSpotify, attr) == expected
