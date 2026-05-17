# -*- coding: utf-8 -*-
"""Pure swipe-decision seam for :mod:`components.playerspotify` (Phase 3c).

``PlayerSpotify.play_card`` used to inline a one-line rule::

    if last_uri == uri and coordinator.current() == 'spotify':
        second_swipe_action()
    else:
        play_content(uri)

That rule has a subtle edge case (the *"card swiped while Spotify is
already playing the same URI"* bug fixed in Phase 3c): if the user had
started a URI via the web UI (``play_content`` directly, no card swipe),
``last_played_uri`` will already equal the URI of the card they swipe.
The old rule then incorrectly treats the *first* card swipe as a
*second* swipe and pauses playback instead of treating the card as a
fresh user intent.

The fix is to track *card activation time* separately from
``last_played_uri``. A card swipe only counts as a "second swipe" when:

1. ``last_played_uri`` equals the incoming URI, AND
2. Spotify is still the active player, AND
3. The last activation came via a *card swipe* (``last_card_activation_time``
   is set and references the same URI).

In-app starts of the URI do not satisfy (3), so the first card swipe of
that same URI is treated as a fresh play. Subsequent card swipes do.

The decision is a pure function of small inputs — no I/O, no plugin
framework — so the tests can exercise the *real production rule*
instead of a parallel reimplementation. This is the Phase 3a
seam-extraction pattern (cf. ``project_phase_3a_pattern.md``).
"""

from __future__ import annotations

import enum
from typing import NamedTuple, Optional


class SpotifySwipeDecision(enum.Enum):
    """Outcome of :func:`decide_spotify_swipe`.

    Mirrors :class:`components.playermpd.state_store.SwipeDecision` —
    deliberately distinct so the two backends evolve independently and
    each backend's tests can pin the values they emit.
    """

    #: Treat as a fresh card swipe — call ``play_content`` with the URI.
    FIRST = 'first'
    #: Treat as a repeat card swipe — call the configured
    #: ``second_swipe_action`` (toggle/pause/skip/...).
    SECOND_TOGGLE = 'second_toggle'


class SpotifySwipeContext(NamedTuple):
    """Inputs to :func:`decide_spotify_swipe`.

    A tiny container so the test cases read as plain data tables — much
    easier to reason about than a pile of positional ``decide_*`` args.

    Fields:
        incoming_uri: The URI the caller is asking us to play.
        last_played_uri: The URI most recently played (from any path —
            card swipe or in-app start). May be ``None`` on cold start.
        last_card_uri: The URI most recently triggered *specifically by
            a card swipe*. ``None`` if the last activation came from the
            web UI / direct ``play_content``.
        coordinator_current: The currently-active backend name from
            :meth:`PlayerCoordinator.current`. ``None`` if no backend
            has claimed the slot.
    """

    incoming_uri: str
    last_played_uri: Optional[str]
    last_card_uri: Optional[str]
    coordinator_current: Optional[str]


def decide_spotify_swipe(ctx: SpotifySwipeContext) -> SpotifySwipeDecision:
    """Decide whether a card swipe is a first or second swipe.

    Returns :attr:`SpotifySwipeDecision.SECOND_TOGGLE` iff *all three*
    conditions hold:

    1. ``ctx.incoming_uri == ctx.last_played_uri`` — same content,
    2. ``ctx.coordinator_current == 'spotify'`` — Spotify is the
       audible backend (the user hasn't handed off to MPD/podcast),
    3. ``ctx.last_card_uri == ctx.incoming_uri`` — the previous
       activation of this URI came from a card swipe, not from the
       web UI / a direct RPC call.

    Condition (3) is the Phase 3c addition. Without it, a user who
    starts a playlist via the web UI and then swipes the corresponding
    card would have the swipe interpreted as a "second swipe" — usually
    pausing the music. With (3), the first card swipe of a URI that
    was started in-app is treated as a fresh play.

    Otherwise returns :attr:`SpotifySwipeDecision.FIRST`.
    """
    if ctx.incoming_uri is None:
        # Defensive — the caller's RPC parser should reject this, but
        # don't crash here either.
        return SpotifySwipeDecision.FIRST
    if ctx.last_played_uri != ctx.incoming_uri:
        return SpotifySwipeDecision.FIRST
    if ctx.coordinator_current != 'spotify':
        return SpotifySwipeDecision.FIRST
    if ctx.last_card_uri != ctx.incoming_uri:
        return SpotifySwipeDecision.FIRST
    return SpotifySwipeDecision.SECOND_TOGGLE
