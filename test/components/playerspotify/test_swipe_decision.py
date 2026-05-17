# -*- coding: utf-8 -*-
"""Behavioural tests for :func:`decide_spotify_swipe` (Phase 3c).

Exercises the *real production decision function*. The Phase 3a
reviewer's golden rule applies here: revert the production check
``ctx.last_card_uri != ctx.incoming_uri`` and the
``test_in_app_play_then_card_swipe_is_first_swipe`` test must fail.
Confirmed by inspection — see commit body for the reversion-check
walkthrough.
"""

from __future__ import annotations

import pytest

from components.playerspotify.swipe_decision import (
    SpotifySwipeContext,
    SpotifySwipeDecision,
    decide_spotify_swipe,
)


URI_A = 'spotify:playlist:aaaaaaaaaaaaaaaaaaaaaa'
URI_B = 'spotify:playlist:bbbbbbbbbbbbbbbbbbbbbb'


# ---------------------------------------------------------------------------
# Fresh-swipe cases (FIRST)
# ---------------------------------------------------------------------------
def test_cold_start_returns_first():
    """Nothing has played yet → fresh swipe."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=None,
        last_card_uri=None,
        coordinator_current=None,
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


def test_different_uri_returns_first():
    """Different URI from last play → fresh swipe."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_B,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


def test_same_uri_but_mpd_is_active_returns_first():
    """User has handed off to another backend → re-claim, fresh swipe."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current='mpd',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


def test_same_uri_no_active_backend_returns_first():
    """Coordinator says no one is active → fresh swipe."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current=None,
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


# ---------------------------------------------------------------------------
# Second-swipe case (SECOND_TOGGLE)
# ---------------------------------------------------------------------------
def test_repeat_card_swipe_of_same_uri_returns_second_toggle():
    """Card was previously swiped for this URI, Spotify still active → toggle."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.SECOND_TOGGLE


# ---------------------------------------------------------------------------
# The Phase 3c headline bug: in-app start, then card swipe
# ---------------------------------------------------------------------------
def test_in_app_play_then_card_swipe_is_first_swipe():
    """Phase 3c regression test.

    Scenario: user starts URI_A via the web UI (so ``last_played_uri``
    becomes URI_A but ``last_card_uri`` stays None — no card was
    swiped). Spotify is the active backend. The user then taps the
    RFID card mapped to URI_A.

    Old buggy behaviour: ``last_played_uri == uri and current() ==
    'spotify'`` is True → pauses playback. Bad UX — the card swipe
    looks broken.

    New correct behaviour: ``last_card_uri != uri`` → FIRST.

    REVERSION CHECK: removing condition (3) from
    :func:`decide_spotify_swipe` makes this test fail, because conditions
    (1) and (2) are both satisfied.
    """
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,  # set by in-app start
        last_card_uri=None,     # no card has been swiped this session
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


def test_in_app_start_of_different_uri_then_card_swipe_for_third_uri():
    """In-app play of URI_B, then card swipe of URI_A → fresh swipe."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_B,
        last_card_uri=None,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


def test_card_then_in_app_then_card_returns_second_toggle_when_uris_match():
    """User swipes card (URI_A), then uses in-app controls to keep
    playing URI_A (last_played_uri stays URI_A, last_card_uri also
    stays URI_A), then swipes card again. → SECOND_TOGGLE.
    """
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.SECOND_TOGGLE


def test_card_swipe_then_in_app_switches_to_different_uri_then_card_swipe_of_original():
    """Card swiped URI_A, user picked URI_B in-app, then swipes the
    URI_A card again. last_card_uri is URI_A but last_played_uri is
    URI_B (most recent play). Rule (1) fails → FIRST.
    """
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_B,
        last_card_uri=URI_A,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


# ---------------------------------------------------------------------------
# Defensive cases
# ---------------------------------------------------------------------------
def test_none_incoming_uri_returns_first():
    """Defensive: a None incoming URI defaults to FIRST so the caller
    doesn't trip a confusing toggle on garbage input.
    """
    ctx = SpotifySwipeContext(
        incoming_uri=None,  # type: ignore[arg-type]
        last_played_uri=None,
        last_card_uri=None,
        coordinator_current='spotify',
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST


@pytest.mark.parametrize('current_backend', ['mpd', 'podcast', None, ''])
def test_only_spotify_active_qualifies_for_second_swipe(current_backend):
    """Even with matching URIs and a prior card swipe, if Spotify isn't
    the active backend (because the user handed off to another), the
    swipe must re-claim with a fresh play — not toggle."""
    ctx = SpotifySwipeContext(
        incoming_uri=URI_A,
        last_played_uri=URI_A,
        last_card_uri=URI_A,
        coordinator_current=current_backend,
    )
    assert decide_spotify_swipe(ctx) is SpotifySwipeDecision.FIRST
