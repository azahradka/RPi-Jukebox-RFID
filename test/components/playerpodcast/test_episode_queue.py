# -*- coding: utf-8 -*-
"""
Unit tests for Episode Queue Manager
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone

# Import the module to test
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'jukebox'))

from components.playerpodcast.episode_queue import EpisodeQueueManager


@pytest.fixture
def mock_state_manager():
    """Create mock state manager"""
    state_manager = Mock()
    state_manager.is_episode_completed = Mock(return_value=False)
    state_manager.get_podcast_progress = Mock(return_value={
        'total': 5,
        'completed': 0,
        'incomplete': 5,
        'all_completed': False
    })
    state_manager.reset_podcast_episodes = Mock()
    state_manager.get_last_played = Mock(return_value={
        'episode_guid': None
    })
    return state_manager


@pytest.fixture
def queue_manager(mock_state_manager):
    """Create EpisodeQueueManager instance"""
    return EpisodeQueueManager(mock_state_manager)


@pytest.fixture
def sample_episodes():
    """Create sample episode list"""
    return [
        {
            'guid': 'ep1',
            'title': 'Episode 1',
            'url': 'https://example.com/ep1.mp3',
            'publish_date': '2024-01-01T00:00:00+00:00',
            'duration_seconds': 3600
        },
        {
            'guid': 'ep2',
            'title': 'Episode 2',
            'url': 'https://example.com/ep2.mp3',
            'publish_date': '2024-01-02T00:00:00+00:00',
            'duration_seconds': 3600
        },
        {
            'guid': 'ep3',
            'title': 'Episode 3',
            'url': 'https://example.com/ep3.mp3',
            'publish_date': '2024-01-03T00:00:00+00:00',
            'duration_seconds': 3600
        }
    ]


def test_sort_episodes_newest_first(queue_manager, sample_episodes):
    """Test episode sorting by date (newest first)"""
    # Shuffle episodes
    shuffled = [sample_episodes[1], sample_episodes[0], sample_episodes[2]]

    sorted_eps = queue_manager.sort_episodes_newest_first(shuffled)

    assert len(sorted_eps) == 3
    assert sorted_eps[0]['guid'] == 'ep3'  # Newest (2024-01-03)
    assert sorted_eps[1]['guid'] == 'ep2'  # Middle (2024-01-02)
    assert sorted_eps[2]['guid'] == 'ep1'  # Oldest (2024-01-01)


def test_filter_incomplete_episodes(queue_manager, mock_state_manager, sample_episodes):
    """Test filtering incomplete episodes"""
    # Mark ep2 as completed
    mock_state_manager.is_episode_completed.side_effect = lambda guid: guid == 'ep2'

    incomplete = queue_manager.filter_incomplete_episodes(sample_episodes)

    assert len(incomplete) == 2
    assert incomplete[0]['guid'] == 'ep1'
    assert incomplete[1]['guid'] == 'ep3'


def test_get_playable_queue_normal(queue_manager, mock_state_manager, sample_episodes):
    """Test playable queue generation (normal case)"""
    mock_state_manager.get_podcast_progress.return_value = {
        'total': 3,
        'completed': 1,
        'incomplete': 2,
        'all_completed': False
    }
    mock_state_manager.is_episode_completed.side_effect = lambda guid: guid == 'ep2'

    playable, was_reset = queue_manager.get_playable_queue(sample_episodes, 'podcast123')

    assert was_reset is False
    assert len(playable) == 2
    # Should be sorted newest first, with completed filtered out
    assert playable[0]['guid'] == 'ep3'
    assert playable[1]['guid'] == 'ep1'


def test_get_playable_queue_auto_reset(queue_manager, mock_state_manager, sample_episodes):
    """Test auto-reset when all episodes completed"""
    mock_state_manager.get_podcast_progress.return_value = {
        'total': 3,
        'completed': 3,
        'incomplete': 0,
        'all_completed': True
    }
    mock_state_manager.is_episode_completed.return_value = True

    playable, was_reset = queue_manager.get_playable_queue(sample_episodes, 'podcast123')

    assert was_reset is True
    assert len(playable) == 3  # All episodes playable after reset
    mock_state_manager.reset_podcast_episodes.assert_called_once()


def test_find_resume_episode(queue_manager, mock_state_manager, sample_episodes):
    """Test finding resume episode"""
    mock_state_manager.get_last_played.return_value = {
        'episode_guid': 'ep2'
    }
    mock_state_manager.is_episode_completed.return_value = False

    sorted_eps = queue_manager.sort_episodes_newest_first(sample_episodes)
    result = queue_manager.find_resume_episode(sorted_eps)

    assert result is not None
    episode, index = result
    assert episode['guid'] == 'ep2'
    assert index == 1  # ep3 (index 0), ep2 (index 1), ep1 (index 2)


def test_find_resume_episode_none(queue_manager, mock_state_manager, sample_episodes):
    """Test resume when no last played episode"""
    mock_state_manager.get_last_played.return_value = {
        'episode_guid': None
    }

    result = queue_manager.find_resume_episode(sample_episodes)
    assert result is None


def test_generate_mpd_playlist(queue_manager, sample_episodes):
    """Test MPD playlist generation"""
    playlist = queue_manager.generate_mpd_playlist(sample_episodes)

    assert len(playlist) == 3
    assert playlist[0] == 'https://example.com/ep1.mp3'
    assert playlist[1] == 'https://example.com/ep2.mp3'
    assert playlist[2] == 'https://example.com/ep3.mp3'


def test_get_episode_by_guid(queue_manager, sample_episodes):
    """Test finding episode by GUID"""
    episode = queue_manager.get_episode_by_guid(sample_episodes, 'ep2')

    assert episode is not None
    assert episode['title'] == 'Episode 2'

    # Non-existent episode
    episode = queue_manager.get_episode_by_guid(sample_episodes, 'ep999')
    assert episode is None


def test_get_next_episode(queue_manager, sample_episodes):
    """Test getting next episode"""
    next_ep = queue_manager.get_next_episode('ep1', sample_episodes)

    assert next_ep is not None
    assert next_ep['guid'] == 'ep2'

    # Last episode has no next
    next_ep = queue_manager.get_next_episode('ep3', sample_episodes)
    assert next_ep is None


def test_get_queue_info(queue_manager, mock_state_manager, sample_episodes):
    """Test comprehensive queue info"""
    mock_state_manager.get_podcast_progress.return_value = {
        'total': 3,
        'completed': 1,
        'incomplete': 2,
        'all_completed': False
    }
    mock_state_manager.is_episode_completed.side_effect = lambda guid: guid == 'ep2'

    info = queue_manager.get_queue_info(sample_episodes, 'podcast123')

    assert info['total_episodes'] == 3
    assert info['completed'] == 1
    assert info['incomplete'] == 2
    assert info['playable_count'] == 2
    assert info['all_completed'] is False
    assert info['newest_episode']['guid'] == 'ep3'
    assert info['oldest_episode']['guid'] == 'ep1'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
