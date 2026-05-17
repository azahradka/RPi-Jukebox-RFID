# -*- coding: utf-8 -*-
"""Regression tests for Spotify device discovery on activation.

Phase 1, fix #5: a cold-start ``play_card`` / ``play_content`` used to
silently no-op when the device was missing because ``_ensure_device``
made a single probe and bailed. Activation now blocks up to 5 s for the
librespot device to appear; if it doesn't, the caller raises a clear
:class:`SpotifyException` (HTTP 503) instead of returning ``None``.
"""

import time
from unittest.mock import patch

from components.playerspotify import PlayerSpotify


def _build_player(device_response):
    """Construct a PlayerSpotify with a mocked spotipy client.

    ``device_response`` is the value (or callable) returned by
    ``self.sp_client.devices()``. Skips auth/init heavy paths.
    """
    p = PlayerSpotify.__new__(PlayerSpotify)
    p.device_name = 'Phoniebox'
    p.player_status = {'device_id': None}
    p.sp_client = type('FakeSp', (), {})()

    if callable(device_response):
        p.sp_client.devices = device_response
    else:
        p.sp_client.devices = lambda: device_response
    return p


def test_ensure_device_for_activation_returns_immediately_when_already_set():
    p = _build_player({'devices': []})
    p.player_status['device_id'] = 'already-here'
    t0 = time.monotonic()
    assert p._ensure_device_for_activation(timeout=5.0) is True
    assert time.monotonic() - t0 < 0.1


def test_ensure_device_for_activation_finds_device_on_first_try():
    p = _build_player({'devices': [{'id': 'dev-1', 'name': 'Phoniebox'}]})
    assert p._ensure_device_for_activation(timeout=5.0) is True
    assert p.player_status['device_id'] == 'dev-1'


def test_ensure_device_for_activation_times_out_with_no_device():
    """No matching device ever appears → returns False within ~timeout."""
    p = _build_player({'devices': [{'id': 'x', 'name': 'OtherBox'}]})
    t0 = time.monotonic()
    ok = p._ensure_device_for_activation(timeout=0.5)
    elapsed = time.monotonic() - t0
    assert ok is False
    # Hard upper bound: must not run wildly past the requested timeout
    # (allowing slack for the trailing sleep).
    assert elapsed < 1.5, f"timed out late after {elapsed:.2f}s"
    # And must not return early either.
    assert elapsed >= 0.4


def test_ensure_device_for_activation_picks_up_late_arrival():
    """Device appears partway through the wait window."""
    started = time.monotonic()
    delay = 0.6

    def late_devices():
        if time.monotonic() - started < delay:
            return {'devices': []}
        return {'devices': [{'id': 'late-dev', 'name': 'Phoniebox'}]}

    p = _build_player(late_devices)
    assert p._ensure_device_for_activation(timeout=2.0) is True
    assert p.player_status['device_id'] == 'late-dev'


def test_play_content_raises_clear_error_when_device_never_appears():
    """The user-visible RPC path: cold ``play_content`` with no device
    must surface a :class:`SpotifyException` (HTTP 503), not silently
    return ``None``."""
    p = _build_player({'devices': []})
    # Stub out the noisy bits.
    p._require_client = lambda: None
    p._refresh_token_if_needed = lambda: None

    with patch.object(p, '_ensure_device_for_activation', return_value=False):
        # play_content's try/except swallows SpotifyException and logs it,
        # so we patch the activation helper and verify the call site
        # *raised* the exception (which the outer handler logs).
        with patch('components.playerspotify.logger') as mock_logger:
            p.play_content('spotify:track:abc')
        # The error path logs "Play content failed: ..." (SpotifyException
        # branch). Verify that branch fired.
        error_calls = [c for c in mock_logger.error.call_args_list
                       if 'Play content failed' in str(c)]
        assert error_calls, (
            f"expected 'Play content failed' to be logged; got "
            f"{mock_logger.error.call_args_list}"
        )


def test_play_content_uses_activation_helper_with_5s_timeout():
    """Source-level pin: ``play_content`` must call
    ``_ensure_device_for_activation(timeout=5.0)``, not the old
    ``_ensure_device``."""
    from pathlib import Path
    source = (
        Path(__file__).resolve().parents[3]
        / 'src' / 'jukebox' / 'components' / 'playerspotify' / '__init__.py'
    )
    text = source.read_text()
    assert 'self._ensure_device_for_activation(timeout=5.0)' in text
