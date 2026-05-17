# -*- coding: utf-8 -*-
"""Pure-seam state machine for podcast playback (Phase 3b).

The pre-Phase-3b ``play_podcast_series`` was a ~150-line procedural blob
mixing four concerns: second-swipe detection, feed fetching, queue
building (with auto-reset / resume), and the actual MPD wire calls.
This module extracts the *decision* parts into small pure functions so
they can be tested directly against real fixtures
(:class:`PodcastStateManager`, :class:`EpisodeQueueManager`) without
mocking the production logic.

The seams (mirroring the Phase 3a ``decide_swipe`` / ``apply_poll``
pattern from playermpd's ``state_store``):

* :func:`decide_second_swipe` - given a state snapshot + MPD state
  string, return a :class:`SecondSwipeDecision` enum telling the caller
  whether to invoke the second-swipe action, clear the stale active
  flag, or proceed with a fresh playback.

* :func:`build_queue_plan` - given a fetched feed, the state manager
  and queue manager, return a :class:`QueuePlan` (the episode to play,
  the resume position, was_reset flag, full playable queue). All the
  feed-data validation and resume-or-start logic lives here.

The I/O - feed fetching, ``plugs.call`` invocations, lock acquisition -
stays in ``__init__.py``. Those operations are the parts that touch
real systems; the decisions themselves are testable in isolation.
"""

from __future__ import annotations

import enum
import logging
from typing import Any, Dict, List, NamedTuple, Optional


logger = logging.getLogger('jb.PodcastPlaybackState')


class SecondSwipeDecision(enum.Enum):
    """What the caller should do on receipt of a re-tap of the same card.

    The decision depends on two pieces of state:

    * ``playback_active`` + ``current_feed_url`` (or ``current_episode_guid``)
      tracked in :class:`PlayerPodcast`.
    * The MPD-side ``state`` (``play`` / ``pause`` / ``stop``) at the
      moment of the second tap.
    """

    #: Same podcast/episode is genuinely playing - run the configured
    #: second-swipe handler (toggle / next_episode / none).
    INVOKE_HANDLER = 'invoke_handler'

    #: ``playback_active`` flag is stale (MPD has stopped). Clear the
    #: flag and treat this swipe as a first tap (restart playback).
    CLEAR_STALE_AND_RESTART = 'clear_stale_and_restart'

    #: A different podcast/episode (or none) - just start fresh.
    FRESH_START = 'fresh_start'


def decide_second_swipe(
    *,
    playback_active: bool,
    current_feed_url: Optional[str],
    incoming_feed_url: str,
    mpd_state: Optional[str],
    current_episode_guid: Optional[str] = None,
    incoming_episode_guid: Optional[str] = None,
) -> SecondSwipeDecision:
    """Decide what a same-URI re-tap should do.

    Inputs are all plain values - no PlayerPodcast or MPD dependency.
    A caller takes a snapshot of state under its lock, releases the
    lock, fetches MPD's status, and passes both to this function.

    If ``incoming_episode_guid`` is ``None`` the caller is asking about
    a *series* swipe (matches by feed URL only). If it is supplied
    the caller is asking about a *specific episode* swipe (matches by
    both feed URL and episode guid).
    """
    if not playback_active or current_feed_url != incoming_feed_url:
        return SecondSwipeDecision.FRESH_START

    if (
        incoming_episode_guid is not None
        and current_episode_guid != incoming_episode_guid
    ):
        return SecondSwipeDecision.FRESH_START

    # Same podcast (and episode, if specified). Disambiguate stale flag
    # via MPD state: if MPD has actually stopped, the flag lies.
    if mpd_state == 'stop' or mpd_state is None:
        return SecondSwipeDecision.CLEAR_STALE_AND_RESTART

    return SecondSwipeDecision.INVOKE_HANDLER


class QueuePlan(NamedTuple):
    """The output of :func:`build_queue_plan`.

    ``episode_to_play`` is the first episode the caller should hand to
    MPD. ``resume_position`` is the seek-target in seconds (``0`` for
    a fresh start). ``was_reset`` indicates the queue manager wiped
    completion state because every episode had been completed.
    ``playable_episodes`` is the full ordered queue (newest-first by
    convention, less any completed entries). ``podcast_id`` is the
    deduplicated feed identifier the state manager keys on.
    """
    podcast_id: str
    episode_to_play: Dict[str, Any]
    resume_position: float
    was_reset: bool
    playable_episodes: List[Dict[str, Any]]
    start_index: int


def build_queue_plan(
    *,
    feed_data: Dict[str, Any],
    queue_manager: Any,
    state_manager: Any,
) -> Optional[QueuePlan]:
    """Build the play plan for a series-tap once the feed has been fetched.

    Returns ``None`` if the feed contains no episodes or the
    auto-reset/filter pipeline yielded an empty playable queue. The
    caller logs and aborts in that case.

    Side effect: this calls ``queue_manager.get_playable_queue`` which
    may invoke ``state_manager.reset_podcast_episodes`` (auto-reset
    when every episode has been completed). That mutation is part of
    the contract - the test fixtures exercise it directly.
    """
    podcast_id = feed_data['podcast_id']
    episodes = feed_data.get('episodes', [])
    if not episodes:
        return None

    playable_episodes, was_reset = queue_manager.get_playable_queue(
        episodes, podcast_id,
    )
    if not playable_episodes:
        return None

    # Resume detection: skip if the queue was just reset (every
    # episode previously completed - user wants to restart from
    # newest, not resume mid-stream).
    resume_info = queue_manager.find_resume_episode(playable_episodes)
    start_index = 0
    resume_position = 0.0
    if resume_info and not was_reset:
        resume_episode, resume_index = resume_info
        start_index = resume_index
        resume_position = float(
            state_manager.get_resume_position(resume_episode['guid'])
        )

    episode_to_play = playable_episodes[start_index]
    return QueuePlan(
        podcast_id=podcast_id,
        episode_to_play=episode_to_play,
        resume_position=resume_position,
        was_reset=was_reset,
        playable_episodes=playable_episodes,
        start_index=start_index,
    )
