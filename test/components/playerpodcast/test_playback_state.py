# -*- coding: utf-8 -*-
"""Tests for :mod:`components.playerpodcast.playback_state` (Phase 3b).

The pure-seam decision functions extracted from the 150-line
``play_podcast_series`` blob. Following the Phase 3a pattern
(``decide_swipe`` / ``apply_poll`` in playermpd.state_store) these
tests exercise the *real* production logic against minimal fixtures -
NOT a parallel implementation in the test file.

Reversion check: each test's purpose is documented inline so the
reviewer can mentally revert the corresponding production change
and confirm the test fails.
"""

import sys
from pathlib import Path


# Make jukebox source importable for the state-manager / queue-manager fixtures.
_JUKEBOX_SRC = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


# ---------------------------------------------------------------------------
# decide_second_swipe
# ---------------------------------------------------------------------------

class TestDecideSecondSwipe:
    """Cover the second-swipe decision matrix for series and episode taps.

    Reversion-check note: if the production logic that conditions on
    ``playback_active`` + ``current_feed_url`` (and ``mpd_state``) is
    reverted to the pre-Phase-1 "always toggle when feed matches"
    behaviour, the stale-flag tests below will fail.
    """

    def test_fresh_tap_different_feed_returns_fresh_start(self, playback_state_module):
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/b',
            mpd_state='play',
        )
        assert decision is playback_state_module.SecondSwipeDecision.FRESH_START

    def test_same_feed_actively_playing_returns_invoke_handler(self, playback_state_module):
        """The canonical second-swipe path: re-tapping a playing podcast
        must surface the configured second_swipe_action (toggle/etc.)."""
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state='play',
        )
        assert decision is playback_state_module.SecondSwipeDecision.INVOKE_HANDLER

    def test_same_feed_but_mpd_stopped_returns_clear_stale(self, playback_state_module):
        """``playback_active`` flag lying because MPD has stopped (e.g.
        Spotify took over via the coordinator handoff). Production
        must treat this as a first tap, not a toggle."""
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state='stop',
        )
        assert decision is playback_state_module.SecondSwipeDecision.CLEAR_STALE_AND_RESTART

    def test_same_feed_mpd_state_none_returns_clear_stale(self, playback_state_module):
        """MPD status RPC returned None (wire stall). Conservative
        choice: treat as stale, not as toggle."""
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state=None,
        )
        assert decision is playback_state_module.SecondSwipeDecision.CLEAR_STALE_AND_RESTART

    def test_not_playback_active_returns_fresh_start(self, playback_state_module):
        """No prior playback - any tap is a fresh start regardless of
        MPD state."""
        decision = playback_state_module.decide_second_swipe(
            playback_active=False,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state='play',
        )
        assert decision is playback_state_module.SecondSwipeDecision.FRESH_START

    def test_same_feed_different_episode_returns_fresh_start(self, playback_state_module):
        """``play_podcast_episode`` (specific guid): same feed but
        different episode is a fresh start, not a toggle."""
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state='play',
            current_episode_guid='ep1',
            incoming_episode_guid='ep2',
        )
        assert decision is playback_state_module.SecondSwipeDecision.FRESH_START

    def test_same_feed_same_episode_actively_playing_returns_invoke(self, playback_state_module):
        decision = playback_state_module.decide_second_swipe(
            playback_active=True,
            current_feed_url='http://feed/a',
            incoming_feed_url='http://feed/a',
            mpd_state='pause',
            current_episode_guid='ep1',
            incoming_episode_guid='ep1',
        )
        # pause counts as "actively playing" (just paused) - toggle
        # should resume.
        assert decision is playback_state_module.SecondSwipeDecision.INVOKE_HANDLER


# ---------------------------------------------------------------------------
# build_queue_plan
# ---------------------------------------------------------------------------

def _make_state_manager(tmp_state_dir):
    """Real PodcastStateManager pointed at a tmp file."""
    sys.path.insert(0, str(_JUKEBOX_SRC))
    from components.playerpodcast.state_manager import PodcastStateManager
    return PodcastStateManager(
        status_file=str(tmp_state_dir / 'podcast_state.json'),
        completion_threshold=0.9,
    )


def _make_queue_manager(state_manager):
    from components.playerpodcast.episode_queue import EpisodeQueueManager
    return EpisodeQueueManager(state_manager)


def _episode(guid: str, *, publish_date: str = '2024-01-01T00:00:00+00:00',
             url: str = 'http://cdn/ep.mp3', title: str = 'Episode'):
    return {
        'guid': guid,
        'podcast_id': 'pod1',
        'title': title,
        'url': url,
        'publish_date': publish_date,
        'duration_seconds': 100,
    }


class TestBuildQueuePlan:
    """Exercise the real ``EpisodeQueueManager`` + ``PodcastStateManager``
    against a tmp state file.

    Reversion check: if ``build_queue_plan`` is reverted to skip the
    ``was_reset`` guard around resume detection (the bug it
    consolidates), ``test_no_resume_when_queue_was_reset`` fails. If
    reverted to always start at index 0, ``test_resume_from_position``
    fails.
    """

    def test_returns_none_when_no_episodes(self, playback_state_module, tmp_state_dir):
        state_mgr = _make_state_manager(tmp_state_dir)
        queue_mgr = _make_queue_manager(state_mgr)
        feed_data = {'podcast_id': 'pod1', 'episodes': []}

        plan = playback_state_module.build_queue_plan(
            feed_data=feed_data,
            queue_manager=queue_mgr,
            state_manager=state_mgr,
        )
        assert plan is None

    def test_fresh_first_swipe_returns_newest_at_index_zero(
        self, playback_state_module, tmp_state_dir,
    ):
        state_mgr = _make_state_manager(tmp_state_dir)
        queue_mgr = _make_queue_manager(state_mgr)
        eps = [
            _episode('old', publish_date='2024-01-01T00:00:00+00:00'),
            _episode('mid', publish_date='2024-06-01T00:00:00+00:00'),
            _episode('new', publish_date='2024-12-01T00:00:00+00:00'),
        ]
        feed_data = {'podcast_id': 'pod1', 'episodes': eps}

        plan = playback_state_module.build_queue_plan(
            feed_data=feed_data,
            queue_manager=queue_mgr,
            state_manager=state_mgr,
        )
        assert plan is not None
        # Newest-first ordering means 'new' lives at index 0.
        assert plan.episode_to_play['guid'] == 'new'
        assert plan.start_index == 0
        assert plan.resume_position == 0.0
        assert plan.was_reset is False

    def test_skips_completed_episodes(self, playback_state_module, tmp_state_dir):
        """A completed episode is filtered out of the playable queue.

        Reversion check: drop the ``filter_incomplete_episodes`` step
        and this test fails (the completed 'new' episode would be
        returned)."""
        state_mgr = _make_state_manager(tmp_state_dir)
        queue_mgr = _make_queue_manager(state_mgr)
        # Mark the newest episode as completed - it should be skipped.
        state_mgr.update_episode_position('new', 100.0, 100.0)
        eps = [
            _episode('old', publish_date='2024-01-01T00:00:00+00:00'),
            _episode('mid', publish_date='2024-06-01T00:00:00+00:00'),
            _episode('new', publish_date='2024-12-01T00:00:00+00:00'),
        ]
        feed_data = {'podcast_id': 'pod1', 'episodes': eps}

        plan = playback_state_module.build_queue_plan(
            feed_data=feed_data,
            queue_manager=queue_mgr,
            state_manager=state_mgr,
        )
        assert plan is not None
        # 'new' was completed - the next-newest 'mid' should now play.
        assert plan.episode_to_play['guid'] == 'mid'
        assert plan.was_reset is False
        # Completed episode must NOT appear in the playable queue.
        guids = [e['guid'] for e in plan.playable_episodes]
        assert 'new' not in guids
        assert 'mid' in guids

    def test_resume_from_saved_position(self, playback_state_module, tmp_state_dir):
        """A prior partial play recorded by ``update_episode_position``
        (under the completion threshold) plus an ``update_last_played``
        triggers resume.

        Reversion check: remove the ``resume_info`` lookup in
        ``build_queue_plan`` and ``start_index`` would stay at 0,
        and ``resume_position`` would be 0 - this test fails."""
        state_mgr = _make_state_manager(tmp_state_dir)
        queue_mgr = _make_queue_manager(state_mgr)
        eps = [
            _episode('old', publish_date='2024-01-01T00:00:00+00:00'),
            _episode('mid', publish_date='2024-06-01T00:00:00+00:00'),
            _episode('new', publish_date='2024-12-01T00:00:00+00:00'),
        ]
        # Record partial playback of 'mid' (50/100s - well under the
        # 0.9 completion threshold).
        state_mgr.update_episode_position('mid', 50.0, 100.0)
        state_mgr.update_last_played('pod1', 'mid', 'http://feed/a')

        feed_data = {'podcast_id': 'pod1', 'episodes': eps}
        plan = playback_state_module.build_queue_plan(
            feed_data=feed_data,
            queue_manager=queue_mgr,
            state_manager=state_mgr,
        )
        assert plan is not None
        # Resume should pick 'mid' (the last-played episode) at 50s.
        assert plan.episode_to_play['guid'] == 'mid'
        assert plan.resume_position == 50.0
        # Index 1 = the position of 'mid' in newest-first ordering
        # [new, mid, old].
        assert plan.start_index == 1
        assert plan.was_reset is False

    def test_no_resume_when_queue_was_reset(self, playback_state_module, tmp_state_dir):
        """If every episode had been completed and the queue manager
        auto-resets, the resume position should NOT be honoured -
        the user wants to restart from newest, not jump back to
        whatever was last completed.

        Reversion check: remove the ``and not was_reset`` guard in
        ``build_queue_plan`` and this test fails - the plan would
        resume the last-completed episode instead of starting at
        the newest."""
        state_mgr = _make_state_manager(tmp_state_dir)
        queue_mgr = _make_queue_manager(state_mgr)
        eps = [
            _episode('old', publish_date='2024-01-01T00:00:00+00:00'),
            _episode('mid', publish_date='2024-06-01T00:00:00+00:00'),
            _episode('new', publish_date='2024-12-01T00:00:00+00:00'),
        ]
        # Mark all as completed.
        for guid in ('old', 'mid', 'new'):
            state_mgr.update_episode_position(guid, 100.0, 100.0)
        # And record 'mid' as last played - this is the trap the
        # was_reset guard avoids.
        state_mgr.update_last_played('pod1', 'mid', 'http://feed/a')

        feed_data = {'podcast_id': 'pod1', 'episodes': eps}
        plan = playback_state_module.build_queue_plan(
            feed_data=feed_data,
            queue_manager=queue_mgr,
            state_manager=state_mgr,
        )
        assert plan is not None
        assert plan.was_reset is True
        # Start at newest, not at 'mid'.
        assert plan.episode_to_play['guid'] == 'new'
        assert plan.start_index == 0
        assert plan.resume_position == 0.0

    def test_returns_none_when_only_completed_episodes_but_no_reset(
        self, playback_state_module, tmp_state_dir,
    ):
        """Edge case: every episode is completed AND the queue
        manager's reset happens, returning the full queue. We test
        the explicit empty path via a hand-built feed with zero
        playable episodes after filter (mocked queue manager)."""
        # Easier: a feed with no episodes after sorting also exercises
        # the early-out, but we already tested that. Instead exercise
        # the "queue_manager.get_playable_queue returns empty list +
        # was_reset=False" path with a fake queue manager.
        class _EmptyQM:
            def get_playable_queue(self, episodes, podcast_id):
                return [], False

            def find_resume_episode(self, episodes):
                return None

        plan = playback_state_module.build_queue_plan(
            feed_data={'podcast_id': 'pod1', 'episodes': [_episode('x')]},
            queue_manager=_EmptyQM(),
            state_manager=None,  # never reached
        )
        assert plan is None
