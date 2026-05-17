# Phoniebox Functional Specification

This document describes what the Phoniebox jukebox does today, as observed from
its code and configuration. It is a target reference for the phased hardening
roadmap: a description of the system that is being preserved, not a guide for
new development. Where current behavior is known to be defective, the intended
behavior is recorded here and the defect is called out in
[Section 9](#9-known-quirks-and-footguns).

## Contents

- [1. What Phoniebox Is](#1-what-phoniebox-is)
- [2. Hardware](#2-hardware)
- [3. Card Behavior](#3-card-behavior)
- [4. Players](#4-players)
- [5. Web UI Screens](#5-web-ui-screens)
- [6. RPC Commands](#6-rpc-commands)
- [7. Configuration](#7-configuration)
- [8. System Services](#8-system-services)
- [9. Known Quirks and Footguns](#9-known-quirks-and-footguns)

## 1. What Phoniebox Is

Phoniebox is an RFID-driven music box for the Raspberry Pi. A user places a
card on the reader and music starts; lifting the card pauses playback.
Different cards can call different actions: play a folder of local audio,
start a podcast feed, play a Spotify playlist, adjust volume, set a sleep
timer, or shut the box down.

The jukebox plays from three sources in parallel:

- **Local audio files** stored on the Pi's SD card, served by the Music
  Player Daemon (MPD).
- **Podcasts** discovered via the iTunes Search API and streamed (then
  cached) through MPD.
- **Spotify** content (playlists, albums, tracks) streamed via a librespot
  Spotify Connect endpoint, controlled by the spotipy web API.

A web app served by nginx provides a phone-friendly browser interface for
status, library browsing, card registration, and settings. A ZMQ RPC channel
and a publish-subscribe channel sit between the web app, the daemon, and
other clients (GPIO buttons, command-line tool).

Minimum hardware is a Raspberry Pi Zero 2 W; Pi 2, Pi 3, Pi 4, and Pi 5 all
run the same software. Minimum Python is 3.9. The project is a hard fork of
an existing v2 jukebox, rebuilt as a single Python daemon with a plugin
model and a React web app. The intended audience is makers building their
own box, not commercial deployment.

## 2. Hardware

### 2.1 Raspberry Pi Models

Any Raspberry Pi with Wi-Fi and a 40-pin header runs the software. Pi 2, Pi 3,
Pi 4, Pi 5, and Pi Zero 2 W are all known-good. Pi Zero 2 W is the recommended
small-footprint build; the Pi 1 and original Pi Zero are too slow.

### 2.2 RFID Readers

Seven reader integrations ship with the jukebox. They cover the three common
bus types (SPI, I2C, serial UART) plus generic USB. Two are place-capable in
the sense of [Section 3](#3-card-behavior): they emit a continuous signal
while a card sits on the reader.

- **MFRC522 (SPI)** &mdash; the most common reader, sold under names like RC522
  and RFID-RC522. 13.56 MHz, place-capable.
- **PN532 (I2C)** &mdash; based on the py532lib driver. 13.56 MHz,
  place-capable.
- **RDM6300 (serial UART)** &mdash; 125 kHz, place-capable.
- **Generic USB** &mdash; any HID-class USB RFID reader that emits the card ID
  as a keyboard-style key sequence. Typically swipe-only.
- **Generic NFCPy** &mdash; any USB NFC reader supported by the nfcpy library.
- **Fake Reader (GUI)** &mdash; a Tk-based desktop window with a card-id
  selector, used for development on a workstation without RFID hardware.
- **Template Reader** &mdash; a stub directory that documents the contract
  for adding a new reader.

Cards must match the reader's frequency band: 125 kHz (RDM6300) or 13.56 MHz
(MFRC522, PN532, most USB). Multiple readers can be configured on a single
box; the daemon merges their input streams.

### 2.3 Audio Output

The audio path runs through PulseAudio. A primary output (always present at
boot) and an optional secondary output (typically a Bluetooth speaker that
connects on demand) are supported. Output options:

- **I2S amplifier HAT** &mdash; Adafruit Speaker Bonnet, Hifiberry, IQaudio
  DAC. Best quality because the digital path bypasses analog jack noise.
- **USB DAC or USB sound card** &mdash; any device PulseAudio recognises.
- **Pi headphone jack** &mdash; the built-in 3.5 mm analog output.
- **Bluetooth A2DP** &mdash; bluez-managed speakers or headsets. A2DP volume
  is controlled independently from PulseAudio levels.

The PulseAudio chain passes audio through a mono down-mix sink and an
optional 10-band equaliser sink before reaching the hardware sink; details
in [Section 9](#9-known-quirks-and-footguns).

### 2.4 Reference Build

The development test rig is not required, but the rest of this spec is
calibrated against it.

- **Amplifier:** Adafruit Speaker Bonnet (MAX98357A I2S stereo, 3 W per
  channel into 4&ndash;8 &Omega;, GPIO 18 / 19 / 21, gain 6 dB by default).
- **Speaker:** Peerless PLS-65F25AL04-04 (2.5-inch fullrange aluminium
  driver, 4 &Omega;, 25 W, 100&ndash;10000 Hz, 84.6 dB at 2.83 V).
- **Reader:** MFRC522 SPI breakout, place-capable.

### 2.5 GPIO and Other Input

Buttons, rotary encoders, LEDs, and buzzers wired to the GPIO header can be
mapped to RPC commands via [`gpio.yaml`](#73-gpioyaml) (gpiozero wrapped by
the jukebox's gpioz plugin). USB game controllers and similar keyboard /
joystick devices are an alternative input route via
[`evdev.yaml`](#74-evdevyaml). Both are optional.

## 3. Card Behavior

A card is any RFID tag readable by the configured reader. The jukebox does not
care about brand, form factor (sticker, card, key fob), or memory contents; it
keys actions off the tag's unique identifier (UID). UIDs are stored as strings
in the card database (`shared/settings/cards.yaml`); numeric-looking UIDs must
still be quoted as strings.

### 3.1 Reader Modes

Every reader operates in one of two modes:

- **Swipe** &mdash; the reader reports the UID once when the card enters its
  field. Generic USB readers behave this way by default.
- **Place-not-swipe** &mdash; the reader reports the UID continuously while
  the card sits on it, and signals when the card leaves. MFRC522, PN532, and
  RDM6300 support this mode when their reader configuration sets
  `place_not_swipe.enabled: true`.

### 3.2 On Card Detection

When a card is detected, the daemon looks up its UID in
`shared/settings/cards.yaml` and invokes the configured RPC command. If the
UID is unknown, nothing happens (apart from optional debug logging).

For a place-not-swipe reader the same UID arrives repeatedly at the polling
rate. The daemon suppresses repeats using the `same_id_delay` value on the
reader (typically one second). The per-card flag `ignore_same_id_delay: true`
overrides that suppression for "repeat as long as the card is present"
behavior &mdash; a volume up/down card, for example.

### 3.3 On Card Removal

For place-not-swipe readers, the daemon runs a *card removal action* when
the card leaves the field. The action is configured once per reader in
`shared/settings/rfid.yaml` and applies to every card; the typical choice is
`pause`. Removal actions can be suppressed per card with
`ignore_card_removal_action: true` (used for command cards like shutdown
timer or volume preset). Setting `ignore_same_id_delay: true` implies
`ignore_card_removal_action: true`.

### 3.4 Per-Card Configuration

Each card entry in `cards.yaml` is a mapping under the card's UID string. The
recognised keys are:

```yaml
'1234567890':
  alias: play_card              # or package + plugin + method
  args: ['Children/LullabyAlbum']
  kwargs: {recursive: true}
  ignore_same_id_delay: true
  ignore_card_removal_action: true
```

Either `alias` (a name defined in [Section 6.1](#61-aliases)) or the explicit
triple `package` + `plugin` + `method` must be present. `args` must be a list
even for a single argument. `kwargs` is a mapping.

### 3.5 Second Swipe

When a card is swiped again while the corresponding content is still the most
recently played item on its player, the daemon may run a *second swipe
action* rather than restarting playback. Each player owns the rule (only the
player knows what "the same content" means and whether it is restorable) and
defines its own configurable response. See [Section 4](#4-players).

### 3.6 Card Database Operations

Six RPCs operate on the card database: `list_cards` (decoded list for
display), `register_card` (add by alias), `register_card_custom` (stub for
full RPC entries, not yet wired), `delete_card`, `load_card_database` (reload
from disk), `save_card_database` (persist). The web app uses `cardsList`,
`registerCard`, `deleteCard` from the Cards screens
([Section 5.6](#56-cards-overview)).

## 4. Players

The jukebox runs all three player backends in parallel. Each owns a
`playerstatus` RPC and its own card-driven entry points but they share the
audio output. The active player is whichever most recently received a
`play_*` call; generic `player.ctrl.*` controls (pause, next, prev) are
routed to the backend currently driving sound.

Coexistence works because each backend writes its activity to a status JSON
under `shared/settings/`, the MPD player checks the podcast player's
`is_podcast_active` flag before routing next/prev, and Spotify maintains
its own active-player record plus its own remote control path through the
librespot device.

### 4.1 MPD Player (local audio)

The MPD player plays files in `shared/audiofolders` via the Music Player
Daemon. It is the default backend and the only one exposing a full MPD
library API to the web app (album list, folder browsing, song search).

**What it plays.** Any file MPD can decode, organised in folders. The library
is indexed on startup if `library.update_on_startup: true`; MPD's
`auto_update` is also on, so files copied in appear without manual rescan.

**Card actions exposed.** `play_card` (the main entry: plays a folder with
second-swipe detection), `play_folder` (ignores second swipe), `play_album`
(by album-artist + album name), `play_single` (by song URL). Shared
controls: `play`, `pause`, `toggle`, `next_song`, `prev_song`, `shuffle`,
`repeat`.

**State and resume.** Last played folder, song position, and elapsed time
persist to `shared/settings/music_player_status.json`. The `replay` and
`resume` RPCs restart the last folder; `replay_if_stopped` does so only
when playback has stopped.

**Second swipe.** Configured under `playermpd.second_swipe_action.alias` in
`jukebox.yaml`. Options are `toggle` (pause/resume), `play`, `skip` (next
track), `rewind` (restart playlist), `replay` (restart last folder), and
`none`. Default is `toggle`.

**Stopped-state behavior.** When the playlist has stopped and a next/prev
arrives, the daemon consults `stopped_prev_action` / `stopped_next_action`
(defaults `prev` and `next`). At the end of a playlist, `next` consults
`end_of_playlist_next_action` (default `none`).

**Audio routing.** Through PulseAudio (`type "pulse"`), not direct ALSA. The
consequences of getting this wrong are in
[Section 9](#9-known-quirks-and-footguns).

### 4.2 Podcast Player

The podcast player searches the iTunes directory, fetches RSS feeds, caches
episode audio locally, and hands the file path to MPD for playback. MPD's
database refresh is triggered via `update_wait`.

**What it plays.** Any podcast RSS feed reachable from the box. Discovery uses
the iTunes Search API; manual entry of a feed URL also works. Episodes can be
played as a series (all unplayed episodes, newest first by default) or by
specific GUID.

**Episode lifecycle.** Episodes are streamed once and cached as files under
`shared/cache/podcasts/episodes/`. That directory is symlinked into MPD's
audio folder as `audiofolders/podcast-cache`, so MPD plays podcast files
through the same relative-path mechanism as local audio. Episodes
&gt; 90 % played are marked completed; once every episode in a feed is
completed, the player auto-resets and replays from newest. Playback position
is saved every 10 seconds.

**Card actions exposed.** `play_podcast_series` (entire feed, newest first),
`play_podcast_episode` (single GUID; supports `feed_url::guid` URIs),
`play_card` (second-swipe-aware), `search_podcasts`, `get_episodes`,
`get_podcast_info`, `refresh_feed`. Controls: `pause` (alias
`podcast_toggle`), `next` (`podcast_next`), `prev` (`podcast_prev`),
`stop`, `play`.

**State and resume.** Per-episode completion and resume position persist to
a state JSON under `shared/settings/`. A re-swiped feed resumes rather than
restarts.

**Second swipe.** Configured under `playerpodcast.second_swipe_action.alias`.
Options are `toggle` (pause/resume) and `next_episode`. Default is `toggle`.

**Audio routing.** Identical to MPD, since the podcast player is a thin layer
on top of MPD. Episodes play as ordinary MPD tracks.

**Coexistence with MPD.** When the podcast player is active, generic
`player.ctrl.next` / `prev` are forwarded to the podcast player so it can
advance episodes rather than playlist tracks. The forwarding gate is the
`is_podcast_active` RPC, which checks the current MPD file path against
the podcast cache prefix.

### 4.3 Spotify Player

The Spotify player drives a librespot Spotify Connect endpoint running as a
sibling systemd user service. Playback control goes through the spotipy web
API; audio never passes through the jukebox daemon &mdash; librespot
connects directly to PulseAudio.

**What it plays.** Spotify playlists, albums, tracks, shows, and individual
episodes. Artist URIs are not supported because Spotify retired the "artist
top tracks" endpoint. URLs of the form `https://open.spotify.com/...` are
normalised to `spotify:...` URIs.

**Authentication.** OAuth with the Spotify Web API. The user supplies a
client ID / secret from the Spotify developer dashboard, completes the OAuth
flow from the web app, and the resulting token persists to
`shared/settings/spotify_credentials.json`. Spotify Premium is required for
playback control.

**Card actions exposed.** `play_content` (the explicit entry point) and
`play_card` (the second-swipe variant), plus controls `play`, `pause`,
`toggle`, `next`, `prev`, `seek`, `rewind`, `replay`, `shuffle`, `repeat`.
Configuration and content browsing RPCs: `get_spotify_config`,
`set_spotify_config`, `get_auth_status`, `get_auth_url`, `authenticate`,
`logout`, `search`, `get_user_playlists`, `get_user_albums`,
`get_content_details`.

**State and resume.** Last played URI persists to
`shared/settings/spotify_player_status.json` and drives second-swipe
detection and `replay`. Playback position is whatever Spotify records on
the account.

**Second swipe.** Configured under `playerspotify.second_swipe_action.alias`.
Options are `toggle`, `play`, `skip`, `rewind`, `replay`, and `none`. Default
is `toggle`. The handler also checks
[active-player coordination](#4-players) so that a Spotify card swiped while
MPD or podcast is active triggers a fresh play rather than the second-swipe
action.

**Audio routing.** Librespot announces itself as a Spotify Connect device
(default name "Phoniebox") and outputs through PulseAudio. Configured in
[`librespot.service`](#82-librespotservice).

**Fallback.** Optional `playerspotify.fallback_action` triggers a fallback
RPC (typically `playermpd.play_card`) when Spotify is unreachable.

### 4.4 Player Coordination

Switching between players happens implicitly. A card swipe that routes to a
specific backend (`play_card`, `play_podcast_card`, `play_spotify_card`)
makes that backend active. Generic control aliases such as `pause`, `toggle`,
and GPIO mappings target the MPD controller, which delegates to the podcast
player when podcast playback is active and leaves Spotify to its own
`spotify_*` aliases.

The web app shows a single Player view ([Section 5.1](#51-player)). The view
queries `player.ctrl.playerstatus`; the podcast player's `playerstatus`
mirrors that with episode metadata overlaid; Spotify keeps its own status
JSON polled separately.

## 5. Web UI Screens

The web app is a single-page React app served by nginx from
`src/webapp/build`. Four top-level routes nest into nine screens. RPC calls
go through a ZMQ websocket; publish-subscribe updates flow over a second
websocket and drive live status.

### 5.1 Player

**Route:** `/` (index). The default landing screen shows the active track's
artwork, title, artist, album, elapsed / duration, seek bar, transport
controls (play/pause, prev, next, shuffle, repeat), and volume slider with
mute. A status banner shows podcast download progress when applicable.

**RPC calls:** `playerstatus`, `play`, `pause`, `prev_song`, `next_song`,
`toggle`, `shuffle`, `repeat`, `seek`, `getVolume`, `setVolume`,
`toggleMuteVolume`, `getSingleCoverArt`. Live status arrives via the
publish-subscribe channel under the `playerstatus` topic.

### 5.2 Library: Albums

**Route:** `/library/albums` and `/library/albums/:artist/:album`. Albums
grouped by album-artist plus album. Tapping an album opens a song list with
"play album now" and (in card-selection mode) "register to card". The
Library header includes a text filter.

**RPC calls:** `albumList`, `songList`, `play_album`, `play_single`,
`getAlbumCoverArt`.

### 5.3 Library: Folders

**Route:** `/library/folders/:dir`. A hierarchical browser over
`shared/audiofolders`. Tapping a folder descends; tapping a file plays it
as a single. "Play this folder" plays the current directory. Card-selection
mode adds a per-folder "register to card".

**RPC calls:** `folderList`, `play_folder`, `play_single`,
`directoryTreeOfAudiofolder`.

### 5.4 Library: Podcasts

**Route:** `/library/podcasts`. Two-step interface: search by name (iTunes
Search API), pick a podcast, see its episodes. Each card shows artwork,
title, author. "Register to card" saves the feed URL (or `feed_url::guid`
for a specific episode) under a swiped card.

**RPC calls:** `searchPodcasts`, `getPodcastInfo`, `getPodcastEpisodes`,
`refreshPodcastFeed`, `play_podcast_series`, `play_podcast_episode`,
`getPodcastCacheStats`, `clearPodcastCache`, `evictPodcastEpisode`.

### 5.5 Library: Spotify

**Route:** `/library/spotify`. Visible only when Spotify is configured and
authenticated. Three sub-views: search (playlists, albums, tracks), user
playlists, user saved albums. Each result shows artwork, name, owner /
artist, total tracks. Selecting an item offers "play now" plus "register
to card".

**RPC calls:** `spotifyGetAuthStatus`, `spotifySearch`,
`spotifyGetUserPlaylists`, `spotifyGetUserAlbums`,
`spotifyGetContentDetails`, `spotifyPlayContent`, `play_spotify_card`.

### 5.6 Cards: Overview

**Route:** `/cards`. A list of every card in the database, sorted by UID.
Each row shows UID, action label, and an edit button. A floating "+"
launches registration; delete is exposed per row.

**RPC calls:** `cardsList`, `deleteCard`.

### 5.7 Cards: Edit

**Route:** `/cards/:cardId/edit`. A per-card editor showing the decoded
action, arguments, and `ignore_*` flags. Saving rewrites the entry via
`registerCard` with `overwrite=true`.

**RPC calls:** `cardsList`, `registerCard`.

### 5.8 Cards: Register

**Route:** `/cards/register`. The registration wizard: swipe the card, pick
an action category (music, podcast, Spotify, command, volume preset),
collect arguments &mdash; either by opening a Library screen in selection
mode or by entering arguments directly &mdash; confirm and write the entry.

**RPC calls:** `registerCard` plus the library RPCs for the chosen category.

### 5.9 Settings

**Route:** `/settings`. A single screen split into eight panels:

- **Status** &mdash; CPU temperature, disk usage, IP address, autohotspot
  state. Read-only.
- **General** &mdash; user preferences (language, `show_covers` toggle).
  `getAppSettings`, `setAppSettings`.
- **Timers** &mdash; volume fade, stop player, shutdown, idle shutdown.
  Each can be started, cancelled, or queried.
- **Audio** &mdash; PulseAudio sink selection, soft maximum volume,
  output toggle. `getAudioOutputs`, `setAudioOutput`, `setMaxVolume`.
- **Spotify** &mdash; client ID / secret entry, OAuth connect / disconnect,
  current auth status. `spotifyGetConfig`, `spotifySetConfig`,
  `spotifyGetAuthUrl`, `spotifyAuthenticate`, `spotifyLogout`.
- **System Controls** &mdash; shutdown and reboot buttons with confirmation
  (`host.shutdown` / `host.reboot`).
- **Second Swipe** &mdash; selectors for MPD, podcast, and Spotify
  second-swipe actions, persisted to `jukebox.yaml`.
- **Autohotspot** &mdash; status and on/off toggle for the autohotspot
  fallback that turns the Pi into a Wi-Fi access point.

## 6. RPC Commands

Every action the jukebox can perform is reachable as an RPC call. The full
form is a package, plugin, and (often) method tuple plus positional and
keyword arguments:

```yaml
package: volume
plugin: ctrl
method: change_volume
args: [5]
```

A short form &mdash; an *alias* &mdash; expands to the same tuple at runtime.
Aliases are defined in `src/jukebox/components/rpc_command_alias.py` and
listed in [Section 6.1](#61-aliases). The React code uses a parallel command
catalogue listed in [Section 6.2](#62-web-ui-commands). The package name in
every call is the *alias* from `jukebox.yaml`'s `modules.named` &mdash; not
the directory name on disk; see [Section 9](#9-known-quirks-and-footguns).

### 6.1 Aliases

| Alias | Package | Plugin | Method | Description | Ignore card removal |
|---|---|---|---|---|---|
| `play_card` | player | ctrl | play_card | Play music folder triggered by card swipe (with second-swipe detection) | no |
| `play_album` | player | ctrl | play_album | Play album by album-artist + album name | no |
| `play_single` | player | ctrl | play_single | Play a single song by URL | no |
| `play_folder` | player | ctrl | play_folder | Play folder content without second-swipe detection | no |
| `play` | player | ctrl | play | Play / resume the currently selected song | yes |
| `pause` | player | ctrl | pause | Pause playback (the typical card-removal action) | yes |
| `next_song` | player | ctrl | next | Skip to next track | yes |
| `prev_song` | player | ctrl | prev | Skip to previous track | yes |
| `toggle` | player | ctrl | toggle | Toggle pause/resume | yes |
| `shuffle` | player | ctrl | shuffle | Toggle / enable / disable shuffle | yes |
| `repeat` | player | ctrl | repeat | Toggle / enable / disable repeat modes | yes |
| `flush_coverart_cache` | player | ctrl | flush_coverart_cache | Empty the cached cover-art images | no |
| `play_spotify_content` | player_spotify | ctrl | play_content | Play a Spotify URI (playlist / album / track) | no |
| `play_spotify_card` | player_spotify | ctrl | play_card | Play Spotify content with second-swipe detection | no |
| `spotify_toggle` | player_spotify | ctrl | toggle | Toggle Spotify play / pause | yes |
| `spotify_next` | player_spotify | ctrl | next | Skip to next Spotify track | yes |
| `spotify_prev` | player_spotify | ctrl | prev | Skip to previous Spotify track | yes |
| `spotify_shuffle` | player_spotify | ctrl | shuffle | Toggle Spotify shuffle | yes |
| `spotify_repeat` | player_spotify | ctrl | repeat | Toggle Spotify repeat | yes |
| `play_podcast_series` | player_podcast | ctrl | play_podcast_series | Play full podcast series, newest unplayed first | no |
| `play_podcast_episode` | player_podcast | ctrl | play_podcast_episode | Play a single podcast episode | no |
| `play_podcast_card` | player_podcast | ctrl | play_card | Play podcast with second-swipe detection | no |
| `search_podcasts` | player_podcast | ctrl | search_podcasts | Search podcasts via iTunes Search API | no |
| `get_podcast_episodes` | player_podcast | ctrl | get_episodes | List episodes for a podcast feed | no |
| `get_podcast_info` | player_podcast | ctrl | get_podcast_info | Podcast feed metadata (title, author, image, description) | no |
| `refresh_podcast_feed` | player_podcast | ctrl | refresh_feed | Force-refresh a feed bypassing cache | no |
| `podcast_toggle` | player_podcast | ctrl | pause | Toggle podcast play / pause | yes |
| `podcast_next` | player_podcast | ctrl | next | Skip to next podcast episode | yes |
| `podcast_prev` | player_podcast | ctrl | prev | Skip to previous podcast episode | yes |
| `set_volume` | volume | ctrl | set_volume | Set volume to an absolute level | yes |
| `change_volume` | volume | ctrl | change_volume | Increment / decrement volume by a step | yes |
| `set_soft_max_volume` | volume | ctrl | set_soft_max_volume | Set the soft maximum volume cap | yes |
| `toggle_output` | volume | ctrl | toggle_output | Toggle between primary and secondary audio output | yes |
| `shutdown` | host | shutdown | &mdash; | Shut down the Pi | yes |
| `reboot` | host | reboot | &mdash; | Reboot the Pi | yes |
| `say_my_ip` | host | say_my_ip | &mdash; | Speak the box's IP address via text-to-speech | yes |
| `timer_shutdown` | timers | timer_shutdown | start | Start the shutdown timer | yes |
| `timer_fade_volume` | timers | timer_fade_volume | start | Start the fade-out-and-shutdown timer | yes |
| `timer_stop_player` | timers | timer_stop_player | start | Start the stop-player timer | yes |
| `sync_rfidcards_all` | sync_rfidcards | ctrl | sync_all | Sync all audio files and card entries | yes |
| `sync_rfidcards_change_on_rfid_scan` | sync_rfidcards | ctrl | sync_change_on_rfid_scan | Change activation of 'sync on RFID scan' | yes |

`change_volume` additionally sets `ignore_same_id_delay: true`, so a volume
card on a place-capable reader fires continuously.

### 6.2 Web UI Commands

The React command catalogue maps JavaScript identifiers to RPC tuples.
Grouped by the comment sections in `src/webapp/src/commands/index.js`.

| Name | Package | Plugin | Method | argKeys |
|---|---|---|---|---|
| `getSingleCoverArt` | player | ctrl | get_single_coverart | &mdash; |
| `getAlbumCoverArt` | player | ctrl | get_album_coverart | &mdash; |
| `directoryTreeOfAudiofolder` | player | ctrl | list_all_dirs | &mdash; |
| `albumList` | player | ctrl | list_albums | &mdash; |
| `songList` | player | ctrl | list_songs_by_artist_and_album | &mdash; |
| `getSongByUrl` | player | ctrl | get_song_by_url | song_url |
| `folderList` | player | ctrl | get_folder_content | &mdash; |
| `cardsList` | cards | list_cards | &mdash; | &mdash; |
| `registerCard` | cards | register_card | &mdash; | &mdash; |
| `deleteCard` | cards | delete_card | &mdash; | &mdash; |
| `playerstatus` | player | ctrl | playerstatus | &mdash; |
| `play` | player | ctrl | play | &mdash; |
| `play_single` | player | ctrl | play_single | song_url |
| `play_folder` | player | ctrl | play_folder | folder |
| `play_album` | player | ctrl | play_album | albumartist, album |
| `pause` | player | ctrl | pause | &mdash; |
| `prev_song` | player | ctrl | prev | &mdash; |
| `next_song` | player | ctrl | next | &mdash; |
| `toggle` | player | ctrl | toggle | &mdash; |
| `shuffle` | player | ctrl | shuffle | option |
| `repeat` | player | ctrl | repeat | option |
| `seek` | player | ctrl | seek | &mdash; |
| `setVolume` | volume | ctrl | set_volume | volume |
| `getVolume` | volume | ctrl | get_volume | &mdash; |
| `getMaxVolume` | volume | ctrl | get_soft_max_volume | &mdash; |
| `setMaxVolume` | volume | ctrl | set_soft_max_volume | &mdash; |
| `change_volume` | volume | ctrl | change_volume | step |
| `toggleMuteVolume` | volume | ctrl | mute | &mdash; |
| `getAudioOutputs` | volume | ctrl | get_outputs | &mdash; |
| `setAudioOutput` | volume | ctrl | set_output | sink_index |
| `toggle_output` | volume | ctrl | toggle_output | &mdash; |
| `timer_fade_volume.cancel` | timers | timer_fade_volume | cancel | &mdash; |
| `timer_fade_volume.get_state` | timers | timer_fade_volume | get_state | &mdash; |
| `timer_fade_volume` | timers | timer_fade_volume | start | wait_seconds |
| `timer_shutdown.cancel` | timers | timer_shutdown | cancel | &mdash; |
| `timer_shutdown.get_state` | timers | timer_shutdown | get_state | &mdash; |
| `timer_shutdown` | timers | timer_shutdown | start | wait_seconds |
| `timer_stop_player.cancel` | timers | timer_stop_player | cancel | &mdash; |
| `timer_stop_player.get_state` | timers | timer_stop_player | get_state | &mdash; |
| `timer_stop_player` | timers | timer_stop_player | start | wait_seconds |
| `timer_idle_shutdown.cancel` | timers | timer_idle_shutdown | cancel | &mdash; |
| `timer_idle_shutdown.get_state` | timers | timer_idle_shutdown | get_state | &mdash; |
| `timer_idle_shutdown` | timers | timer_idle_shutdown | start | wait_seconds |
| `getAutohotspotStatus` | host | get_autohotspot_status | &mdash; | &mdash; |
| `startAutohotspot` | host | start_autohotspot | &mdash; | &mdash; |
| `stopAutohotspot` | host | stop_autohotspot | &mdash; | &mdash; |
| `getIpAddress` | host | get_ip_address | &mdash; | &mdash; |
| `getDiskUsage` | host | get_disk_usage | &mdash; | &mdash; |
| `reboot` | host | reboot | &mdash; | &mdash; |
| `shutdown` | host | shutdown | &mdash; | &mdash; |
| `say_my_ip` | host | say_my_ip | &mdash; | option |
| `getAppSettings` | misc | get_app_settings | &mdash; | &mdash; |
| `setAppSettings` | misc | set_app_settings | &mdash; | settings |
| `sync_rfidcards_all` | sync_rfidcards | ctrl | sync_all | &mdash; |
| `sync_rfidcards_change_on_rfid_scan` | sync_rfidcards | ctrl | sync_change_on_rfid_scan | option |
| `searchPodcasts` | player_podcast | ctrl | search_podcasts | query |
| `getPodcastEpisodes` | player_podcast | ctrl | get_episodes | feed_url, force_refresh |
| `getPodcastInfo` | player_podcast | ctrl | get_podcast_info | feed_url |
| `refreshPodcastFeed` | player_podcast | ctrl | refresh_feed | feed_url |
| `podcastPlayerStatus` | player_podcast | ctrl | playerstatus | &mdash; |
| `getPodcastStats` | player_podcast | ctrl | get_stats | &mdash; |
| `play_podcast_series` | player_podcast | ctrl | play_podcast_series | feed_url |
| `play_podcast_episode` | player_podcast | ctrl | play_podcast_episode | feed_url, episode_guid |
| `getPodcastCacheStats` | player_podcast | ctrl | get_cache_stats | &mdash; |
| `clearPodcastCache` | player_podcast | ctrl | clear_episode_cache | &mdash; |
| `evictPodcastEpisode` | player_podcast | ctrl | evict_episode | episode_guid |
| `spotifyGetConfig` | player_spotify | ctrl | get_spotify_config | &mdash; |
| `spotifySetConfig` | player_spotify | ctrl | set_spotify_config | client_id, client_secret |
| `spotifyGetAuthStatus` | player_spotify | ctrl | get_auth_status | &mdash; |
| `spotifyGetAuthUrl` | player_spotify | ctrl | get_auth_url | &mdash; |
| `spotifyAuthenticate` | player_spotify | ctrl | authenticate | auth_code |
| `spotifyLogout` | player_spotify | ctrl | logout | &mdash; |
| `spotifySearch` | player_spotify | ctrl | search | query, content_type, limit |
| `spotifyGetUserPlaylists` | player_spotify | ctrl | get_user_playlists | limit, offset |
| `spotifyGetUserAlbums` | player_spotify | ctrl | get_user_albums | limit, offset |
| `spotifyGetContentDetails` | player_spotify | ctrl | get_content_details | uri |
| `spotifyPlayContent` | player_spotify | ctrl | play_content | uri |
| `play_spotify_card` | player_spotify | ctrl | play_card | uri |

## 7. Configuration

All configuration is YAML. Defaults ship in `resources/default-settings/`;
the installer copies them to `shared/settings/` for the user to edit.
Relative paths inside YAML resolve against `src/jukebox`; the sole exception
is `playermpd.mpd_conf`, which honours `~`.

### 7.1 jukebox.yaml

**Path:** `shared/settings/jukebox.yaml` (default
`resources/default-settings/jukebox.default.yaml`)

The top-level daemon configuration. Loaded once at startup.

| Top-level key | Purpose |
|---|---|
| `system` | Box name and identity fields. |
| `modules` | Plugin manifest. `modules.named` defines alias &harr; directory mapping; order matters (plugins load top-to-bottom). |
| `pulse` | Startup volume, soft maximum, output toggle behavior, primary / secondary output definitions. |
| `jingle` / `jinglemp3` / `alsawave` | Startup / shutdown sound paths and per-service jingle parameters. |
| `playermpd` | MPD status file path, second-swipe action, library update-on-startup, MPD config path, stopped-state behavior. |
| `playerspotify` | Spotify credentials, redirect URI, status / cache paths, librespot device name, second-swipe action, optional fallback, cache toggle. |
| `playerpodcast` | Feed cache TTL, position-save interval, completion threshold, episode ordering, second-swipe action, iTunes API limit, episode cache settings. |
| `rpc` | ZMQ TCP and websocket port numbers. |
| `publishing` | Publishing-channel TCP and websocket port numbers. |
| `rfid` | Paths to `rfid.yaml` (reader config) and `cards.yaml` (card database). |
| `gpioz` | Enable flag and path to `gpio.yaml`. |
| `timers` | Idle-shutdown timeout plus defaults for shutdown, stop-player, and volume-fade timers. |
| `host` | Debug mode, temperature publishing, Wi-Fi power-down override, HDMI power-down toggle. |
| `bluetooth_audio_buttons` | Enable flag for auto-listening to Bluetooth speaker / headset buttons. |
| `speaking_text` | espeak language, speed, voice for "say my IP" and similar speech-synthesis features. |
| `sync_rfidcards` | Enable flag and path to `sync_rfidcards.yaml`. |
| `webapp` | Cover-art cache path and `show_covers` toggle. |

### 7.2 cards.yaml

**Path:** `shared/settings/cards.yaml` (examples in
`resources/default-settings/cards.example.yaml`,
`cards.spotify.example.yaml`, `cards.podcast.example.yaml`)

The card database. Top-level keys are card UIDs (strings); each value is an
RPC command spec plus optional flags ([Section 3.4](#34-per-card-configuration)).
The web app rewrites this file via `cards.register_card` and
`cards.delete_card`; hand-editing is supported and reloads emit
`cards.database.has_changed` on the publishing channel.

### 7.3 gpio.yaml

**Path:** `shared/settings/gpio.yaml` (example
`resources/default-settings/gpio.example.yaml`)

GPIO device declarations. Three top-level keys: `pin_factory` (gpiozero
backend, typically `rpigpio.RPiGPIOFactory`), `output_devices` (LEDs,
buzzers), `input_devices` (buttons, rotary encoders, twin buttons). Each
device has a name, a type from the gpioz catalogue, `kwargs` passed to the
gpiozero constructor, and either `connect` (outputs subscribe to publishing
topics like volume / RFID status) or `actions` (inputs map events such as
`on_press`, `on_rotate_*`, `on_short_press_a` to RPC commands using the same
alias / full-form syntax as cards).

### 7.4 evdev.yaml

**Path:** `shared/settings/evdev.yaml` (example
`resources/default-settings/evdev.example.yaml`)

Alternative input mapping for USB game controllers, foot pedals, or any
kernel-evdev device. Top-level `devices` maps nicknames to evdev device
matchers, each with its own `input_devices` block mapping key codes to
action aliases &mdash; the same shape as `gpio.yaml` but keyed by USB device
name.

### 7.5 logger.yaml

**Path:** `shared/settings/logger.yaml` (default
`resources/default-settings/logger.default.yaml`)

Python logging config. Two formatters (color console, plain files), four
handlers (console, rotating `app.log`, rotating `errors.log`, and a
publishing handler that forwards warnings and above over the
publish-subscribe channel), one colorising filter, and a root logger under
the `jb` namespace. Log files live in `shared/logs/`.

### 7.6 sync_rfidcards.yaml

**Path:** `shared/settings/sync_rfidcards.yaml` (default
`resources/default-settings/sync_rfidcards.default.yaml`)

Optional remote-sync config for keeping audio files and card entries in step
with a master copy on another machine. Two modes: `mount` (SMB / NFS) or
`ssh`. `sync_rfidcards.credentials` carries server, port, timeout, path,
username. `on_rfid_scan_enabled` controls whether a card swipe triggers a
sync before play.

### 7.7 rfid.yaml

**Path:** `shared/settings/rfid.yaml` (generated by the
`setup_rfid_reader.sh` tool; no shipping default)

Reader configuration. `rfid.readers` is a mapping of reader nicknames
(`read_00`, `read_01`, ...) to per-reader settings: `module` (package under
`components/rfid/hardware/`), `config` (reader-specific parameters chosen
by the setup tool), `same_id_delay`, `log_ignored_cards`, and
`place_not_swipe` (with nested `enabled` and `card_removal_action`). See
[Section 3.1](#31-reader-modes).

### 7.8 cards examples

The three example card files (`cards.example.yaml`,
`cards.spotify.example.yaml`, `cards.podcast.example.yaml`) ship as
reference recipes for the three card categories. They are not loaded by the
daemon. Builders copy entries from them into the active `cards.yaml`.

## 8. System Services

The jukebox runs as a small set of cooperating systemd units. On a Raspberry
Pi OS Lite install, four are in active use.

### 8.1 jukebox-daemon.service

User-level systemd unit running the Python daemon (defined in
`resources/default-services/jukebox-daemon.service`). Starts after
`network.target`, `sound.target`, `mpd.service`, `pulseaudio.service`;
requires `mpd.service` and `pulseaudio.service`. Calls `run_jukebox.sh`,
which activates the Python virtual environment and starts the daemon.
Managed as a user service: `systemctl --user start jukebox-daemon`.

### 8.2 librespot.service

User-level systemd unit for the Spotify Connect endpoint (defined in
`resources/default-settings/librespot.service`). Runs `librespot` with
backend `pulseaudio`, device name "Phoniebox", bitrate 160 kbps, volume
normalisation on, initial volume 70, linear volume control. Memory (100 MB)
and CPU (50 %) caps target the Pi Zero 2 W. The jukebox daemon restarts
librespot when Spotify auth tokens change so the device appears under the
freshly authenticated account.

### 8.3 MPD and PulseAudio

`mpd.service` runs as user `boxadmin` (not the system `mpd` user) and reads
`~/.config/mpd/mpd.conf`. The shipped default sets music directory to
`shared/audiofolders`, playlist directory to `shared/playlists`, database
file to `~/.config/mpd/tag_cache`. MPD listens on TCP `localhost:6600` and
outputs to PulseAudio (`type "pulse"`); `auto_update` is on at depth 10.

`pulseaudio.service` is a user service. The shipped configuration loads
`module-device-restore`, `module-stream-restore` (with
`restore_device=false`), and `module-card-restore`, then the chain in
[Section 9.1](#91-audio-stack-rules).

### 8.4 nginx

System-level service. Default site config
(`resources/default-settings/nginx.default`) serves the React build from
`src/webapp/build` on port 80 and proxies the RPC and publishing
websockets. Reload nginx after deploying a new web build.

### 8.5 Logs

The daemon writes `shared/logs/app.log` (rotating, debug) and
`shared/logs/errors.log` (rotating, warning and above). Rotations are
`*.log.1`, `*.log.2`. The publishing handler also forwards warnings and
above over the publish-subscribe channel. `journalctl --user -u
jukebox-daemon` captures stdout / stderr.

## 9. Known Quirks and Footguns

This section records behaviors that are correct but counter-intuitive, plus
known defects whose intended behavior is documented elsewhere in this spec.

### 9.1 Audio Stack Rules

The PulseAudio sink chain runs: MPD &rarr; `phoniebox_speaker` (mono remap,
volume control) &rarr; `eq_main` (10-band equaliser) &rarr; `alsa_output`
(hardware) &rarr; I2S &rarr; speaker. Two rules follow from this layout:

- Only `phoniebox_speaker` controls volume. `eq_main` and `alsa_output` must
  stay at 100 % passthrough. If an intermediate sink drops below 100 %, the
  effective volume stacks multiplicatively and the box becomes much quieter
  than the UI slider suggests. `module-device-restore` persists sink volumes
  across reboots, so a one-time misconfiguration sticks.
- MPD must output through PulseAudio with `type "pulse"`, not direct ALSA.
  ALSA's `hw:0,0` only allows one program at a time; direct MPD output races
  with the jingle player and PulseAudio's own ALSA grab, producing "Device
  or resource busy" errors.

### 9.2 MPD Specifics

- MPD runs as user `boxadmin`, not the system `mpd` user.
- MPD's config file is `~/.config/mpd/mpd.conf`, not `/etc/mpd.conf`.
- MPD's `music_directory` is `/home/boxadmin/RPi-Jukebox-RFID/shared/audiofolders`.
- MPD listens on TCP `localhost:6600`. No Unix socket is configured.
- MPD does not allow local file access via TCP; paths in RPC calls must be
  relative to `music_directory`, never absolute.
- `auto_update` is on at depth 10, so files dropped into the audio folder are
  picked up without a manual rescan. Symlinks count.

### 9.3 Podcast Specifics

- The episode cache (`shared/cache/podcasts/episodes/`) is symlinked into
  MPD's audio folder as `audiofolders/podcast-cache`. MPD treats it as a
  normal music subdirectory.
- For MPD playback the podcast player uses the relative path
  `podcast-cache/<filename>.mp3`, never an absolute path. See
  [Section 9.2](#92-mpd-specifics).
- After downloading a new episode the podcast player calls
  `player.ctrl.update_wait` so MPD's database picks up the new file before
  playback starts.
- Re-trigger protection compares the swiped feed URL against the most
  recently played feed and consults MPD's playback state. The decision is
  play, resume, or no-op &mdash; not a second-swipe toggle.

### 9.4 Spotify Specifics

- The Spotify backend must not call the Spotify API from `__init__` on the
  main daemon process; doing so blocks RPC startup. Startup-time Spotify
  work is deferred to a background worker or first use.
- The `spotipy.Spotify` client is always built with `requests_timeout=10,
  retries=0`. Without these the client can hang indefinitely on a network
  hiccup.
- Read-only API calls (search, playlists, status fetches) do not hold the
  player's mutual exclusion guard. `spotipy`'s `requests.Session` is safe
  for concurrent reads; only playback mutations are serialised. Guarding
  reads stalls the web UI.
- The status publisher worker calls the private `_fetch_and_update_status()`
  directly, never `playerstatus()`. `playerstatus()` swallows exceptions
  and returns cached status, hiding 429s from back-off code.
- Status polling is adaptive: 1 s while playing, 5 s idle, 30 s+ on error.
  A 429 with `Retry-After` is honoured.
- `spotipy.Spotify.search()` takes `q=` and `type=`, not `query=` /
  `content_type=`. The wrong names silently mis-match.

### 9.5 RPC Package Naming

In any RPC call, configuration entry, or web-app command, the package name is
the *alias* from `jukebox.yaml`'s `modules.named` section, not the directory
name on disk. The alias is the key (left side), the directory is the value
(right side):

```yaml
modules:
  named:
    player_podcast: playerpodcast      # alias: directory
    player_spotify: playerspotify
    player: playermpd
    cards: rfid.cards
    rfid: rfid.reader
    host: hostif.linux
    gpio: gpio.gpioz.plugin
```

Using `playerpodcast` instead of `player_podcast` produces "Package not
registered". Common alias / directory pairs: `player` &harr; `playermpd`,
`player_podcast` &harr; `playerpodcast`, `player_spotify` &harr;
`playerspotify`, `cards` &harr; `rfid.cards`, `rfid` &harr; `rfid.reader`,
`host` &harr; `hostif.linux`, `gpio` &harr; `gpio.gpioz.plugin`.

### 9.6 Second Swipe After Reboot

The MPD second-swipe rule compares the swiped folder against
`music_player_status.json`'s `last_played_folder`. That value is restored
across reboots. After a fresh boot, the first swipe of the most recently
played card is treated as a second swipe rather than a first swipe &mdash;
typically firing a `toggle` against a stopped player and producing no music.
The user-facing fix is to swipe a different card first; the durable fix is
out of scope for this document.

### 9.7 Plugin Loading Silent Failures

The plugin loader catches every exception during a plugin's import or
`@plugs.initialize` step and continues without that plugin. The daemon
still starts; the missing functionality is gone. Symptoms are "Package not
registered" errors at first use and missing menu entries in the web app.
The diagnostic source is `shared/logs/app.log`.

### 9.8 RFID Reader Hang Risk

RFID readers run in worker processes calling into C extensions or USB
ioctls. A misbehaving reader can block its worker indefinitely. The
supervising daemon does not enforce a timeout on these reads, so a hung
reader presents as "RFID stopped working". The remedy today is a
power-cycle.

### 9.9 Other Behaviors Worth Knowing

- Folders named `scratch*` anywhere under the repo are git-ignored. They
  are the canonical place for local experiments.
- The web app must be built on a development machine, not on the Pi. The
  React build process exhausts memory on the Pi Zero 2 W.
- Configuration paths inside YAML files are relative to `src/jukebox`, with
  the single exception of `playermpd.mpd_conf` which accepts `~`.
- Card IDs must be quoted as strings in `cards.yaml`. Numeric-looking IDs
  written without quotes load as integers and fail to match the string
  returned by the readers.
