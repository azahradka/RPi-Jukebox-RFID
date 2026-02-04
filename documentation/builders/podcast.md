# Podcast Integration Guide

**Phoniebox V3 Podcast Player Plugin**

Listen to your favorite podcasts on Phoniebox using RFID cards! This guide covers setup, usage, and advanced features.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Card Setup](#card-setup)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Advanced Features](#advanced-features)

## Overview

The Podcast Player plugin integrates podcast streaming into Phoniebox V3 with:

- **Zero authentication required** - Uses iTunes Search API for discovery
- **Smart episode management** - Plays newest to oldest, skips completed episodes
- **Auto-resume** - Picks up where you left off
- **Auto-reset** - When all episodes completed, restarts from the beginning (perfect for kids!)
- **MPD integration** - Leverages existing audio infrastructure

## Features

### Podcast Discovery

- **iTunes Search API** - Search millions of podcasts without authentication
- **Manual RSS URL** - Add any podcast by pasting its RSS feed URL
- **No API keys required** - Works out of the box

### Playback Intelligence

- **Episode ordering** - Newest to oldest by default
- **Completion tracking** - Automatically marks episodes >90% played as completed
- **Skip completed** - Only plays unplayed/incomplete episodes
- **Auto-reset** - When all episodes are done, automatically resets for re-listening
- **Position saving** - Saves position every 10 seconds (configurable)
- **Resume playback** - Returns to saved position when card is tapped again

### RFID Card Support

- **Series mode** - Play entire podcast (all unplayed episodes)
- **Episode mode** - Play specific episode
- **Second swipe** - Pause/play toggle (configurable)

## Quick Start

### Prerequisites

1. **Phoniebox V3 installed** with MPD working
2. **Python 3.9+** with virtual environment
3. **Internet connection** for podcast feeds

### Installation

1. **Install dependencies:**

   ```bash
   source .venv/bin/activate
   pip install feedparser>=6.0.10
   ```

2. **Enable plugin in `jukebox.yaml`:**

   The plugin is enabled by default in `jukebox.default.yaml`. If you have a custom config:

   ```yaml
   modules:
     named:
       player_podcast: playerpodcast
   ```

3. **Restart jukebox:**

   ```bash
   systemctl --user restart jukebox-daemon
   ```

### First Podcast

1. **Find a podcast feed URL:**
   - Search via Web UI (recommended)
   - Or use RPC tool: `./tools/run_rpc_tool.sh -c playerpodcast.ctrl.search_podcasts "Serial"`

2. **Add to RFID card:**

   Edit `shared/settings/cards.yaml`:

   ```yaml
   card_001:
     alias: play_podcast_series
     args:
       - "http://feeds.serialpodcast.org/serialpodcast"
   ```

3. **Tap card** - Podcast starts playing from newest episode!

## Configuration

Configuration is in `resources/default-settings/jukebox.default.yaml` (or your custom `jukebox.yaml`):

```yaml
playerpodcast:
  enabled: true
  status_file: ../../shared/settings/podcast_player_status.json

  # Feed cache settings
  feed_cache_ttl: 3600  # 1 hour cache
  feed_cache_path: ../../shared/cache/podcasts/

  # Position tracking
  save_position_interval: 10  # Save every 10 seconds

  # Completion threshold
  completion_threshold: 0.9  # 90% = completed

  # Episode ordering
  episode_order: newest_first

  # Second swipe action
  second_swipe_action:
    alias: toggle  # Options: toggle, next_episode, none

  # iTunes Search API
  itunes_api:
    enabled: true
    search_limit: 20
```

### Configuration Options Explained

| Option | Description | Default |
|--------|-------------|---------|
| `feed_cache_ttl` | How long to cache RSS feeds (seconds) | 3600 (1 hour) |
| `save_position_interval` | How often to save playback position | 10 seconds |
| `completion_threshold` | Percentage played to mark as completed | 0.9 (90%) |
| `episode_order` | Episode sort order | `newest_first` |
| `second_swipe_action.alias` | Action when same card tapped twice | `toggle` |

## Card Setup

### Play Entire Podcast Series

```yaml
card_my_podcast:
  alias: play_podcast_series
  args:
    - "https://feeds.example.com/podcast.xml"
```

- Plays all unplayed episodes
- Newest to oldest
- Auto-resumes from last position
- Auto-resets when all completed

### Play Specific Episode

```yaml
card_specific_episode:
  alias: play_podcast_episode
  args:
    - "https://feeds.example.com/podcast.xml"
    - "episode-guid-12345"  # Get from Web UI or RPC
```

### With Second Swipe Detection

```yaml
card_podcast_with_toggle:
  alias: play_podcast_card
  args:
    - "https://feeds.example.com/podcast.xml"
```

First tap: Starts playback
Second tap: Pause/play toggle

### Control Cards

```yaml
# Pause/resume
card_podcast_toggle:
  alias: podcast_toggle

# Next episode
card_podcast_next:
  alias: podcast_next

# Previous episode
card_podcast_prev:
  alias: podcast_prev
```

## Usage Examples

### Example 1: Kids Podcast Collection

```yaml
card_wow_in_world:
  alias: play_podcast_series
  args:
    - "https://feeds.megaphone.fm/HSW4286072308"

card_circle_round:
  alias: play_podcast_series
  args:
    - "https://feeds.publicradio.org/public_feeds/circle-round/rss/rss"

card_story_pirates:
  alias: play_podcast_series
  args:
    - "https://feeds.megaphone.fm/FL7917050671"
```

**Behavior:**
- Each card plays that podcast's unplayed episodes
- Kids can tap same card daily to continue where they left off
- When all episodes done, automatically resets for re-listening

### Example 2: News Podcasts

```yaml
card_the_daily:
  alias: play_podcast_series
  args:
    - "https://feeds.simplecast.com/54nAGcIl"
```

**Behavior:**
- Plays newest episodes first (today's news)
- Automatically skips yesterday's episodes if already listened
- Updates when new episodes published (after cache expires)

### Example 3: Place-Not-Swipe Reader

For readers that detect card placement/removal:

```yaml
card_podcast_pauseable:
  alias: play_podcast_card
  args:
    - "http://feeds.example.com/podcast.xml"
  on_remove:
    alias: pause
```

**Behavior:**
- Card placed: Starts podcast
- Card removed: Pauses playback
- Card placed again: Resumes from position

## Troubleshooting

### Podcast Won't Play

1. **Check feed URL is accessible:**
   ```bash
   curl -I https://feeds.example.com/podcast.xml
   ```

2. **Test feed parsing:**
   ```bash
   ./tools/run_rpc_tool.sh -c playerpodcast.ctrl.get_episodes "feed_url"
   ```

3. **Check logs:**
   ```bash
   journalctl --user -u jukebox-daemon -f | grep -i podcast
   ```

### Common Issues

**"No episodes found"**
- Feed URL may be invalid
- Feed may require authentication (not supported)
- Feed format may be non-standard

**"Position not saving"**
- Check `status_file` path is writable
- Increase `save_position_interval` if SD card is slow
- Check logs for save errors

**"Episodes play in wrong order"**
- Check `episode_order` setting in jukebox.yaml
- Some feeds may have incorrect publish dates
- Force refresh feed: RPC call `refresh_podcast_feed`

**"Search returns no results"**
- iTunes API may be down (rare)
- Try manual RSS URL instead
- Check internet connection

### Performance (RPi Zero 2 W)

**Memory optimization:**
- Feeds are cached to disk, not memory
- Episode streaming (no pre-download)
- Background threads are lightweight

**Typical usage:**
- Feed fetch: ~2-5 seconds
- Episode start: Instant (MPD handles buffering)
- Memory overhead: ~10-20 MB

## Advanced Features

### RPC Commands

Interact with podcasts programmatically:

```bash
# Search podcasts
./tools/run_rpc_tool.sh -c playerpodcast.ctrl.search_podcasts "query"

# Get episodes
./tools/run_rpc_tool.sh -c playerpodcast.ctrl.get_episodes "feed_url"

# Force refresh feed
./tools/run_rpc_tool.sh -c playerpodcast.ctrl.refresh_feed "feed_url"

# Get statistics
./tools/run_rpc_tool.sh -c playerpodcast.ctrl.get_stats
```

### State File Structure

Location: `shared/settings/podcast_player_status.json`

```json
{
  "podcasts": {
    "podcast_id": {
      "feed_url": "https://...",
      "title": "Podcast Name",
      "last_fetched": "2024-01-01T00:00:00Z"
    }
  },
  "episodes": {
    "episode_guid": {
      "podcast_id": "...",
      "position_seconds": 1234,
      "completed": false,
      "duration_seconds": 3600
    }
  },
  "last_played": {
    "podcast_id": "...",
    "episode_guid": "...",
    "feed_url": "..."
  }
}
```

### Custom Episode Ordering

Edit `jukebox.yaml`:

```yaml
playerpodcast:
  episode_order: oldest_first  # Play from episode 1
```

### Integration with Other Plugins

**Volume control:**
```yaml
card_podcast_quiet:
  alias: play_podcast_series
  args:
    - "https://feeds.example.com/podcast.xml"
  # Then trigger volume adjustment
```

**Timer shutdown:**
```yaml
card_podcast_sleeptimer:
  alias: play_podcast_series
  args:
    - "https://feeds.example.com/podcast.xml"
# After playback starts, trigger timer_shutdown
```

## FAQ

**Q: Can I use Spotify podcasts?**
A: No, use the `playerspotify` plugin instead. This plugin is for RSS-based podcasts.

**Q: Can I download episodes for offline playback?**
A: Not in the current version. Episodes are streamed via MPD.

**Q: How do I reset a podcast to start over?**
A: All episodes are auto-reset when all are marked completed. Or manually edit the state file.

**Q: Can I play podcasts from private feeds?**
A: Yes! Just use the direct RSS URL. No authentication is supported though.

**Q: Does this work with video podcasts?**
A: No, audio only. MPD handles audio streaming.

**Q: How many podcasts can I subscribe to?**
A: No hard limit, but recommend <50 for best performance on RPi Zero 2 W.

## Support

- **Documentation:** This file and `cards.podcast.example.yaml`
- **Issues:** GitHub repository issues
- **Community:** Phoniebox forums/Discord

## Credits

- Plugin: Phoniebox V3 architecture
- Feed parsing: feedparser library
- Podcast discovery: Apple iTunes Search API
- Audio playback: MPD (Music Player Daemon)
