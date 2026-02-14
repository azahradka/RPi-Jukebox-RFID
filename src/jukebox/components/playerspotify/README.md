# Spotify Player Plugin

Spotify streaming integration for Phoniebox V3 using spotipy (Spotify Web API) and librespot (audio daemon).

## Overview

This plugin enables Spotify Premium subscribers to stream music through their Phoniebox using RFID cards or RPC commands. It runs alongside the MPD player, allowing seamless switching between local files and Spotify content.

## Architecture

```
RFID Card → RPC Command → PlayerSpotify Plugin
                              ↓
                    Spotify Web API (spotipy)
                              ↓
                    librespot daemon (Spotify Connect)
                              ↓
                    PulseAudio → Speakers
```

### Components

- **`__init__.py`**: Core player plugin (PlayerSpotify class)
  - Implements full player interface (play, pause, stop, next, prev, etc.)
  - Thread-safe Spotify API access with RLock
  - Device discovery and management
  - Second swipe detection for RFID cards
  - Status publishing for Web App integration

- **`spotify_auth.py`**: Authentication manager (SpotifyAuthManager class)
  - OAuth 2.0 PKCE flow implementation
  - AES-256 encrypted token storage
  - Automatic token refresh (60-minute expiry)
  - PBKDF2 key derivation for encryption

- **`content_resolver.py`**: Content resolver (SpotifyContentResolver class)
  - Resolves Spotify URIs to track lists
  - Supports: playlists, albums, artists, tracks
  - Disk-based caching (1-hour TTL)
  - Handles pagination for large playlists

## Requirements

### Essential
- **Spotify Premium account** (required for playback API)
- **spotipy >= 2.23.0** (Spotify Web API Python library)
- **pycryptodome >= 3.20.0** (encryption for token storage)
- **librespot** (Spotify Connect daemon, separate binary)

### System
- Python 3.9+ (Phoniebox requirement)
- Internet connection
- PulseAudio (for audio output)

## Installation

See **[documentation/builders/spotify.md](../../../../documentation/builders/spotify.md)** for complete setup guide.

Quick summary:
1. Create Spotify Developer App
2. Install dependencies: `pip install spotipy pycryptodome`
3. Install librespot binary
4. Configure jukebox.yaml with client_id/client_secret
5. Run authentication: `python tools/spotify_auth_setup.py`
6. Start librespot service
7. Restart jukebox

## Configuration

Add to `shared/settings/jukebox.yaml`:

```yaml
modules:
  named:
    player_spotify: playerspotify  # Register plugin

playerspotify:
  client_id: 'YOUR_CLIENT_ID'
  client_secret: 'YOUR_CLIENT_SECRET'
  redirect_uri: 'http://127.0.0.1:8888/callback'
  credential_file: ../../shared/settings/spotify_credentials.json
  status_file: ../../shared/settings/spotify_player_status.json
  device_name: 'Phoniebox'
  second_swipe_action:
    alias: toggle  # toggle, play, skip, rewind, replay, none
  artist_track_limit: 20
  cache_enabled: true
  cache_path: ../../shared/cache/spotify/
```

## RPC Methods

All methods accessible via RPC (registered as `playerspotify.ctrl`):

### Playback Control
- `play()` - Resume playback
- `pause(state)` - Pause (1) or resume (0)
- `stop()` - Stop and reset position
- `toggle()` - Toggle play/pause
- `next()` - Next track
- `prev()` - Previous track
- `seek(seconds)` - Seek to position
- `rewind()` - Restart track

### Content
- `play_content(uri)` - Play Spotify URI
- `play_card(uri)` - RFID entry with second swipe detection
- `replay()` - Replay last content
- `replay_if_stopped()` - Replay if stopped

### Modes
- `shuffle(option)` - Control shuffle (toggle/on/off)
- `repeat(option)` - Control repeat (toggle/track/context/off)

### Status
- `playerstatus()` - Current state + track info
- `playlistinfo()` - Current queue
- `get_current_song(param)` - Track metadata
- `get_player_type_and_version()` - Player info

## RPC Command Aliases

Convenient aliases in `cards.yaml`:

```yaml
# Play any Spotify content
'card_1':
  alias: play_spotify_content
  args: ['spotify:playlist:37i9dQZF1DXcBWIGoYBM5M']

# Control cards
'card_toggle':
  alias: spotify_toggle

'card_next':
  alias: spotify_next
```

See `resources/default-settings/cards.spotify.example.yaml` for more examples.

## Supported URI Types

### Track
```
spotify:track:11dFghVXANMlKmJXsNCbNl
https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl
```

### Playlist
```
spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
```

### Album
```
spotify:album:6DEjYFkNZh67HP7R9PSZvv
https://open.spotify.com/album/6DEjYFkNZh67HP7R9PSZvv
```

### Artist (top 20 tracks)
```
spotify:artist:0OdUWJ0sBjDrqHygGUXeCF
https://open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF
```

## Usage Examples

### Command Line (RPC Tool)
```bash
./tools/run_rpc_tool.sh

> playerspotify.ctrl.play_content spotify:track:11dFghVXANMlKmJXsNCbNl
> playerspotify.ctrl.toggle
> playerspotify.ctrl.next
```

### RFID Cards
```yaml
# cards.yaml
'1234567890':
  alias: play_spotify_content
  args: ['spotify:playlist:37i9dQZF1DXcBWIGoYBM5M']
```

Swipe once: Plays playlist
Swipe twice: Toggles play/pause (configurable)

### Python Code
```python
import jukebox.plugs as plugs

# Get player instance
player = plugs.call('playerspotify', 'ctrl')

# Play content
player.play_content('spotify:track:11dFghVXANMlKmJXsNCbNl')

# Control playback
player.toggle()
player.next()

# Get status
status = player.playerstatus()
print(status['current_track']['name'])
```

## Thread Safety

All Spotify API calls are protected by `threading.RLock`:

```python
with self.lock:
    self.sp_client.start_playback(device_id=device_id, uris=uris)
```

This ensures safe concurrent access from:
- RPC command thread
- Status publishing thread
- RFID reader thread
- Web App requests

## Token Management

Tokens are automatically refreshed:
- **Expiry**: 60 minutes
- **Check**: Before every API call
- **Refresh**: Transparent to caller
- **Storage**: AES-256 encrypted on disk

```python
def _refresh_token_if_needed(self):
    if self.auth_manager.is_token_expired():
        token = self.auth_manager.get_access_token()
        self.sp_client.set_auth(token)
```

## Caching

Content is cached to reduce API calls:
- **TTL**: 1 hour
- **Storage**: `shared/cache/spotify/content_cache.json`
- **Cache key**: Spotify URI
- **Invalidation**: Automatic (time-based)

Example:
```python
# First call - hits API
tracks = resolver.resolve_uri('spotify:playlist:xxxxx')

# Second call (within 1 hour) - uses cache
tracks = resolver.resolve_uri('spotify:playlist:xxxxx')
```

## Error Handling

Graceful degradation for common errors:

```python
try:
    self.sp_client.start_playback(device_id=device_id, uris=uris)
except SpotifyException as e:
    logger.error(f"Playback failed: {e}")
    # Player continues running, next command may succeed
```

Common errors:
- **Device not found**: Logged, no crash
- **Network timeout**: Logged, retry on next command
- **Token expired**: Automatic refresh
- **Invalid URI**: Logged, empty track list returned

## Performance

Optimized for Raspberry Pi Zero 2 W (416 MB RAM):

- **Memory footprint**: ~10-15 MB (plugin)
- **Spotify client**: ~20-30 MB
- **librespot**: ~50-100 MB
- **Total**: ~80-145 MB

Optimizations:
- Lazy initialization
- Background thread for status updates (1 Hz)
- Caching to minimize API calls
- Efficient data structures (no large buffers)

## Testing

Run unit tests:
```bash
source .venv/bin/activate
pytest test/components/playerspotify/ -v
```

Test coverage:
- `test_auth.py`: 15 tests - Authentication and encryption
- `test_content_resolver.py`: 17 tests - URI resolution and caching
- `test_player.py`: 25 tests - Player methods and RPC

## Debugging

Enable debug logging:
```bash
./run_jukebox.sh -vv  # Info level
./run_jukebox.sh -vvv # Debug level
```

Check logs:
```bash
journalctl --user -u jukebox-daemon -f | grep -i spotify
```

Test API connection:
```python
from components.playerspotify.spotify_auth import SpotifyAuthManager
import spotipy

auth = SpotifyAuthManager(client_id, client_secret, redirect_uri, cred_file)
sp = spotipy.Spotify(auth=auth.get_access_token())
print(sp.current_user())
```

## Known Limitations

1. **Premium Required**: Free accounts cannot use playback API
2. **Internet Required**: No offline playback (use MPD for offline)
3. **No Podcasts**: Only music content supported
4. **Single Device**: Only one Spotify device can play at a time
5. **No Local Files**: Spotify local files not accessible via API

## Coexistence with MPD

Both players run simultaneously:
- **Switch players**: Swipe a card for respective player
- **Control cards**: Work with active player
- **No conflict**: Separate audio paths

Example:
```yaml
# MPD card
'mpd_card':
  alias: play_card
  args: ['Rock']

# Spotify card
'spotify_card':
  alias: play_spotify_content
  args: ['spotify:playlist:xxxxx']

# Works with both
'toggle_card':
  alias: toggle
```

## Security

- ✅ OAuth 2.0 PKCE flow
- ✅ AES-256 encrypted tokens
- ✅ PBKDF2 key derivation (100k iterations)
- ✅ No plaintext credentials
- ✅ HTTPS for all API calls

Credentials stored at: `shared/settings/spotify_credentials.json` (encrypted)

## Contributing

When modifying this plugin:
1. Run flake8: `./run_flake8.sh`
2. Run tests: `pytest test/components/playerspotify/`
3. Test on actual hardware (RPi Zero 2 W)
4. Update documentation
5. Follow PEP 8 style guide

## Support

- **User Guide**: [documentation/builders/spotify.md](../../../../documentation/builders/spotify.md)
- **Setup Tool**: [tools/spotify_auth_setup.py](../../../../tools/spotify_auth_setup.py)
- **Example Cards**: [resources/default-settings/cards.spotify.example.yaml](../../../../resources/default-settings/cards.spotify.example.yaml)
- **Issues**: GitHub Issues (fork or upstream)

## References

- [Spotify Web API Documentation](https://developer.spotify.com/documentation/web-api/)
- [spotipy Documentation](https://spotipy.readthedocs.io/)
- [librespot GitHub](https://github.com/librespot-org/librespot)
- [Phoniebox Documentation](https://github.com/MiczFlor/RPi-Jukebox-RFID/wiki)

## License

Same as Phoniebox project (MIT License)

---

**Status**: ✅ Production ready, tested on RPi Zero 2 W
**Version**: 1.0.0
**Last Updated**: 2026-02-02
