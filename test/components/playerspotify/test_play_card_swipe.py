# -*- coding: utf-8 -*-
"""Integration tests for play_card's use of decide_spotify_swipe (Phase 3c).

The pure decision function is covered in test_swipe_decision.py. These
tests verify the *wiring*: play_card stamps ``last_card_uri`` and
dispatches to either ``play_content`` or ``second_swipe_action`` based
on the seam's decision. They exercise the real ``PlayerSpotify``
object — no parallel implementation of the rule.

Reversion check: if ``play_card`` stops calling ``decide_spotify_swipe``
and falls back to the old two-condition check, the
``test_in_app_play_then_card_swipe_calls_play_content_not_pause`` test
fails — the in-app start sets last_played_uri but leaves last_card_uri
None, so the seam returns FIRST while the old rule returned SECOND.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def cfg_mock():
    cfg = MagicMock()
    cfg.getn.side_effect = lambda *args, **kwargs: {
        ('playerspotify', 'client_id'): 'card_test_id',
        ('playerspotify', 'client_secret'): 'card_test_secret',
        ('playerspotify', 'redirect_uri'): 'http://127.0.0.1:8888/callback',
        ('playerspotify', 'device_name'): 'Phoniebox',
        ('playerspotify', 'credential_file'): '/tmp/swipe_test_creds.json',
        ('playerspotify', 'status_file'): '/tmp/swipe_test_status.json',
        ('playerspotify', 'cache_enabled'): False,
        ('playerspotify', 'cache_path'): '/tmp/swipe_test_cache/',
        ('playerspotify', 'second_swipe_action', 'alias'): 'toggle',
    }.get(tuple(args), kwargs.get('default'))
    return cfg


@pytest.fixture
def sp_client():
    client = MagicMock()
    client.devices.return_value = {
        'devices': [{'id': 'devX', 'name': 'Phoniebox'}]
    }
    client.current_playback.return_value = None
    client.playlist_items.return_value = {
        'items': [{'track': {'uri': 'spotify:track:t1'}}],
        'next': None,
    }
    return client


@pytest.fixture
def fresh_coordinator():
    """Reset the global coordinator's active backend between tests.

    PlayerSpotify uses the module-level singleton via get_coordinator().
    Tests need a deterministic starting state ('spotify' active) so the
    decide_spotify_swipe branch under test is the one we want.
    """
    from components.player.coordinator import get_coordinator
    coord = get_coordinator()
    with coord._lock:  # internal but stable
        prev = coord._current
        coord._current = 'spotify'
    yield coord
    with coord._lock:
        coord._current = prev


@pytest.fixture
def player(cfg_mock, sp_client, fresh_coordinator):
    """Construct a PlayerSpotify with mocked spotipy / publishing."""
    with patch('components.playerspotify.cfg', cfg_mock), \
         patch('components.playerspotify.SpotifyAuthManager') as mock_auth, \
         patch('components.playerspotify.spotipy.Spotify', return_value=sp_client), \
         patch('components.playerspotify.publishing.get_publisher'), \
         patch('components.playerspotify.os.path.exists', return_value=False):
        mock_auth.return_value.get_access_token.return_value = 'tok'
        mock_auth.return_value.is_token_expired.return_value = False
        from components.playerspotify import PlayerSpotify
        p = PlayerSpotify()
        # Quiet the status thread.
        p.status_thread_stop.set()
        p.status_thread.join(timeout=1)
        # Replace second_swipe_action with a recording mock so we can
        # assert dispatch without invoking the real toggle path.
        p._second_swipe_recorder = MagicMock()
        p.second_swipe_action = p._second_swipe_recorder
        yield p


def test_first_swipe_calls_play_content_and_stamps_last_card_uri(player, sp_client):
    """Fresh swipe — no prior URI — calls play_content and records the card."""
    uri = 'spotify:playlist:newcontent'
    with patch.object(player, 'play_content') as mock_play:
        player.play_card(uri)
    mock_play.assert_called_once_with(uri)
    assert player.player_status['last_card_uri'] == uri
    player._second_swipe_recorder.assert_not_called()


def test_repeat_card_swipe_calls_second_swipe_action(player):
    """Same URI, Spotify active, prior card swipe → SECOND_TOGGLE branch."""
    uri = 'spotify:playlist:repeated'
    player.player_status['last_played_uri'] = uri
    player.player_status['last_card_uri'] = uri

    with patch.object(player, 'play_content') as mock_play:
        player.play_card(uri)

    player._second_swipe_recorder.assert_called_once()
    mock_play.assert_not_called()
    assert player.player_status['last_card_uri'] == uri


def test_in_app_play_then_card_swipe_calls_play_content_not_pause(player):
    """Phase 3c regression: in-app play of URI, then physical card swipe
    of the matching card. Old rule incorrectly paused; new rule plays.

    REVERSION CHECK: if play_card reverts to the old
    ``last_uri == uri and coordinator.current() == 'spotify'`` rule
    without consulting ``last_card_uri``, this test fails because the
    in-app start populated ``last_played_uri`` while ``last_card_uri``
    is still None.
    """
    uri = 'spotify:playlist:started_in_app'
    # Simulate in-app start: play_content set last_played_uri but no
    # card was swiped (so last_card_uri stays None).
    player.player_status['last_played_uri'] = uri
    player.player_status['last_card_uri'] = None

    with patch.object(player, 'play_content') as mock_play:
        player.play_card(uri)

    # The card swipe must launch a fresh play, not toggle/pause.
    mock_play.assert_called_once_with(uri)
    player._second_swipe_recorder.assert_not_called()
    # And the swipe stamps the card pointer so a *subsequent* swipe is
    # correctly identified as a second swipe.
    assert player.player_status['last_card_uri'] == uri


def test_different_uri_card_swipe_when_other_uri_was_card_active(player):
    """Card swipe of URI_B while URI_A was the last card-driven play."""
    URI_A = 'spotify:playlist:aaa'
    URI_B = 'spotify:playlist:bbb'
    player.player_status['last_played_uri'] = URI_A
    player.player_status['last_card_uri'] = URI_A

    with patch.object(player, 'play_content') as mock_play:
        player.play_card(URI_B)

    mock_play.assert_called_once_with(URI_B)
    assert player.player_status['last_card_uri'] == URI_B
    player._second_swipe_recorder.assert_not_called()


def test_card_swipe_when_mpd_active_triggers_play_content(player, fresh_coordinator):
    """Spotify is NOT current → re-claim with fresh play."""
    uri = 'spotify:playlist:claim_back'
    player.player_status['last_played_uri'] = uri
    player.player_status['last_card_uri'] = uri
    with fresh_coordinator._lock:
        fresh_coordinator._current = 'mpd'

    with patch.object(player, 'play_content') as mock_play:
        player.play_card(uri)

    mock_play.assert_called_once_with(uri)
    player._second_swipe_recorder.assert_not_called()
