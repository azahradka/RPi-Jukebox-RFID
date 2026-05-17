"""Single source of truth for RPC commands (Phase 5a).

This file defines two dictionaries that together form the Phoniebox RPC
contract surface:

* :data:`cmd_alias_definitions` — short aliases used in ``cards.yaml`` and
  GPIO triggers. Maps human-friendly names like ``play_card`` to the
  underlying ``(package, plugin, method)`` triple plus card-specific
  metadata (``ignore_card_removal_action``, ``ignore_same_id_delay``,
  ``title``, ``note``).

* :data:`web_command_definitions` — the comprehensive Web UI RPC catalog
  consumed by ``src/webapp/src/commands/index.js``. This dict is the
  *source of truth* for the JS commands file; the JS file is generated
  from it by ``src/webapp/scripts/generate-commands.js`` at build time.
  Each entry maps a JS command name (e.g. ``spotifySearch``) to its
  RPC binding and optional ``argKeys`` order.

Until Phase 5a, the JS file was hand-maintained in parallel with this
file — two parallel sources of truth that could (and did) drift. The
new contract:

1. Edit ONLY this Python file when adding or changing an RPC command.
2. Run ``npm run generate-commands`` (or ``npm run build``) to refresh
   the JS file.
3. The generator validates at build time that every command resolves to
   a registered Python plugin method; mismatches fail the build.

See also: :data:`KNOWN_PLUGIN_METHOD_ALLOWLIST` for entries the validator
cannot discover statically (e.g. flat modules that ``@plugs.register``
top-level functions).

See [RPC Commands](../../builders/rpc-commands.md)
"""

# --------------------------------------------------------------
# Pre-defined aliases (card actions / GPIO triggers)
# These aliases can be used by all modules
# Module-specific behaviour modifiers can be simply appended
# Use the functions utils.decode_rpc_command to decode the entries!
# --------------------------------------------------------------
cmd_alias_definitions = {
    # Player
    'play_card': {
        'title': 'Play music folder triggered by card swipe',
        'note': "This function you'll want to use most often",
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'play_card'},
    'play_album': {
        'title': 'Play Album triggered by card swipe',
        'note': "This function plays the content of a given album",
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'play_album'},
    'play_single': {
        'title': 'Play a single song triggered by card swipe',
        'note': "This function plays the content of a given song URL",
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'play_single'},
    'play_folder': {
        'title': 'Play a folder URL triggered by card swipe',
        'note': "This function plays the content of a given folder URL",
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'play_folder'},
    'play': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'play',
        'note': 'Play the currently selected song',
        'ignore_card_removal_action': True},
    'pause': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'pause',
        'note': "This is what you want as card removal action for place capable readers",
        'ignore_card_removal_action': True},
    'next_song': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'next',
        'ignore_card_removal_action': True},
    'prev_song': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'prev',
        'ignore_card_removal_action': True},
    'toggle': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'toggle',
        'ignore_card_removal_action': True},
    'shuffle': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'shuffle',
        'note': 'Shuffle',
        'ignore_card_removal_action': True},
    'repeat': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'repeat',
        'note': 'Repeat',
        'ignore_card_removal_action': True},
    'flush_coverart_cache': {
        'package': 'player',
        'plugin': 'ctrl',
        'method': 'flush_coverart_cache'},

    # SPOTIFY PLAYER
    'play_spotify_content': {
        'title': 'Play Spotify content (playlist/album/track/artist)',
        'note': 'Use this for RFID cards with Spotify URIs. Requires Spotify Premium account.',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'play_content'},
    'play_spotify_card': {
        'title': 'Play Spotify content triggered by card swipe',
        'note': 'Like play_spotify_content but with second swipe detection',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'play_card'},
    'spotify_toggle': {
        'title': 'Toggle Spotify playback (play/pause)',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'toggle',
        'ignore_card_removal_action': True},
    'spotify_next': {
        'title': 'Skip to next Spotify track',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'next',
        'ignore_card_removal_action': True},
    'spotify_prev': {
        'title': 'Skip to previous Spotify track',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'prev',
        'ignore_card_removal_action': True},
    'spotify_shuffle': {
        'title': 'Toggle Spotify shuffle mode',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'shuffle',
        'ignore_card_removal_action': True},
    'spotify_repeat': {
        'title': 'Toggle Spotify repeat mode',
        'package': 'player_spotify',
        'plugin': 'ctrl',
        'method': 'repeat',
        'ignore_card_removal_action': True},


    # PODCAST PLAYER
    'play_podcast_series': {
        'title': 'Play entire podcast series (newest to oldest)',
        'note': 'Plays all unplayed episodes, auto-resumes from last position, auto-resets when all completed',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'play_podcast_series'},
    'play_podcast_episode': {
        'title': 'Play specific podcast episode',
        'note': 'Plays single episode with resume capability',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'play_podcast_episode'},
    'play_podcast_card': {
        'title': 'Play podcast triggered by card swipe',
        'note': 'Like play_podcast_series but with second swipe detection',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'play_card'},
    'search_podcasts': {
        'title': 'Search for podcasts via iTunes API',
        'note': 'Returns list of podcast search results',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'search_podcasts'},
    'get_podcast_episodes': {
        'title': 'Get episodes from podcast feed',
        'note': 'Returns list of episodes from RSS feed',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'get_episodes'},
    'get_podcast_info': {
        'title': 'Get podcast metadata',
        'note': 'Returns podcast title, author, image, description from feed',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'get_podcast_info'},
    'refresh_podcast_feed': {
        'title': 'Force refresh podcast feed',
        'note': 'Bypasses cache and fetches fresh feed data',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'refresh_feed'},
    'podcast_toggle': {
        'title': 'Toggle podcast playback (play/pause)',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'pause',
        'ignore_card_removal_action': True},
    'podcast_next': {
        'title': 'Skip to next podcast episode',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'next',
        'ignore_card_removal_action': True},
    'podcast_prev': {
        'title': 'Skip to previous podcast episode',
        'package': 'player_podcast',
        'plugin': 'ctrl',
        'method': 'prev',
        'ignore_card_removal_action': True},


    # VOLUME
    'set_volume': {
        'package': 'volume',
        'plugin': 'ctrl',
        'method': 'set_volume',
        'ignore_card_removal_action': True},
    'change_volume': {
        'note': "For place-capable readers increment volume as long as card is on reader",
        'package': 'volume',
        'plugin': 'ctrl',
        'method': 'change_volume',
        'ignore_card_removal_action': True,
        'ignore_same_id_delay': True},
    'set_soft_max_volume': {
        'package': 'volume',
        'plugin': 'ctrl',
        'method': 'set_soft_max_volume',
        'ignore_card_removal_action': True},
    'toggle_output': {
        'package': 'volume',
        'plugin': 'ctrl',
        'method': 'toggle_output',
        'ignore_card_removal_action': True},
    # HOST
    'shutdown': {
        'package': 'host',
        'plugin': 'shutdown',
        'ignore_card_removal_action': True},
    'reboot': {
        'package': 'host',
        'plugin': 'reboot',
        'ignore_card_removal_action': True},
    'say_my_ip': {
        'package': 'host',
        'plugin': 'say_my_ip',
        'ignore_card_removal_action': True},
    # TIMER
    'timer_shutdown': {
        'package': 'timers',
        'plugin': 'timer_shutdown',
        'method': 'start',
        'title': 'Start the shutdown timer',
        'ignore_card_removal_action': True},
    'timer_fade_volume': {
        'package': 'timers',
        'plugin': 'timer_fade_volume',
        'method': 'start',
        'title': 'Start the volume fade out timer and shutdown',
        'ignore_card_removal_action': True},
    'timer_stop_player': {
        'package': 'timers',
        'plugin': 'timer_stop_player',
        'method': 'start',
        'title': 'Start the stop music timer',
        'ignore_card_removal_action': True},
    # SYNCHRONISATION
    'sync_rfidcards_all': {
        'package': 'sync_rfidcards',
        'plugin': 'ctrl',
        'method': 'sync_all',
        'title': 'Sync all audiofiles and card entries',
        'ignore_card_removal_action': True},
    'sync_rfidcards_change_on_rfid_scan': {
        'package': 'sync_rfidcards',
        'plugin': 'ctrl',
        'method': 'sync_change_on_rfid_scan',
        'title': "Change activation of 'on RFID scan'",
        'ignore_card_removal_action': True},
}

# --------------------------------------------------------------
# Web UI command catalog (Phase 5a — single source of truth)
# --------------------------------------------------------------
# Consumed by ``src/webapp/scripts/generate-commands.js`` to emit
# ``src/webapp/src/commands/index.js``.
#
# Schema per entry:
#   {
#       'package': str,         # required — RPC package alias from
#                               #   jukebox.yaml modules.named (left side)
#       'plugin':  str,         # required — registered plugin name
#                               #   (often 'ctrl' for player backends, or a
#                               #   top-level function name for flat modules)
#       'method':  str | None,  # optional — method on the plugin; omit or
#                               #   None for 2-part calls (package.plugin)
#       'argKeys': list[str],   # optional — ordered kwarg names the JS
#                               #   caller passes as positional args
#       'note':    str,         # optional — developer-facing description
#       'internal': bool,       # optional — when True, NOT emitted to the
#                               #   JS file. Use for backend-only RPCs
#                               #   (e.g. play_single_passive — see
#                               #   project_phase_3b_followups.md #2).
#   }
#
# Naming convention: keep JS keys camelCase for UI-only commands
# (getSongByUrl, spotifySearch) and snake_case for commands also exposed
# as card-action aliases (play_card, play_single, change_volume). Keys
# starting with ``timer_`` use dotted suffixes (.cancel, .get_state) per
# the existing convention.

web_command_definitions = {
    # ------------------------------------------------------------------
    # Player (MPD)
    # ------------------------------------------------------------------
    'getSingleCoverArt': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'get_single_coverart'},
    'getAlbumCoverArt': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'get_album_coverart'},
    'directoryTreeOfAudiofolder': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'list_all_dirs'},
    'albumList': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'list_albums'},
    'songList': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'list_songs_by_artist_and_album'},
    'getSongByUrl': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'get_song_by_url',
        'argKeys': ['song_url']},
    'folderList': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'get_folder_content'},
    'playerstatus': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'playerstatus'},

    # Player actions (also exposed as card aliases — same triples)
    'play': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'play'},
    'play_single': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'play_single',
        'argKeys': ['song_url']},
    'play_folder': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'play_folder',
        'argKeys': ['folder']},
    'play_album': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'play_album',
        'argKeys': ['albumartist', 'album']},
    'pause': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'pause'},
    'prev_song': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'prev'},
    'next_song': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'next'},
    'toggle': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'toggle'},
    'shuffle': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'shuffle',
        'argKeys': ['option']},
    'repeat': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'repeat',
        'argKeys': ['option']},
    'seek': {
        'package': 'player', 'plugin': 'ctrl', 'method': 'seek'},

    # NOTE: ``play_single_passive`` is intentionally not exposed here.
    # See project_phase_3b_followups.md #2 — it's a backend-only RPC
    # used by playerpodcast to drive the MPD wire WITHOUT claiming the
    # coordinator's active-backend slot. External callers (Web UI, card
    # YAML, GPIO) must use ``play_single`` instead, which calls
    # ``coordinator.activate('mpd')``. Marking it ``'internal': True``
    # documents the omission and is enforced by the generator (the
    # validator checks it against KNOWN_INTERNAL_PLUGIN_METHODS below).

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------
    'cardsList': {
        'package': 'cards', 'plugin': 'list_cards'},
    'registerCard': {
        'package': 'cards', 'plugin': 'register_card'},
    'deleteCard': {
        'package': 'cards', 'plugin': 'delete_card'},

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------
    'setVolume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'set_volume',
        'argKeys': ['volume']},
    'getVolume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'get_volume'},
    'getMaxVolume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'get_soft_max_volume'},
    'setMaxVolume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'set_soft_max_volume'},
    'change_volume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'change_volume',
        'argKeys': ['step']},
    'toggleMuteVolume': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'mute'},
    'getAudioOutputs': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'get_outputs'},
    'setAudioOutput': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'set_output',
        'argKeys': ['sink_index']},
    'toggle_output': {
        'package': 'volume', 'plugin': 'ctrl', 'method': 'toggle_output'},

    # ------------------------------------------------------------------
    # Timers — each timer plugin exposes start (default), cancel, get_state
    # ------------------------------------------------------------------
    'timer_fade_volume': {
        'package': 'timers', 'plugin': 'timer_fade_volume', 'method': 'start',
        'argKeys': ['wait_seconds']},
    'timer_fade_volume.cancel': {
        'package': 'timers', 'plugin': 'timer_fade_volume', 'method': 'cancel'},
    'timer_fade_volume.get_state': {
        'package': 'timers', 'plugin': 'timer_fade_volume', 'method': 'get_state'},
    'timer_shutdown': {
        'package': 'timers', 'plugin': 'timer_shutdown', 'method': 'start',
        'argKeys': ['wait_seconds']},
    'timer_shutdown.cancel': {
        'package': 'timers', 'plugin': 'timer_shutdown', 'method': 'cancel'},
    'timer_shutdown.get_state': {
        'package': 'timers', 'plugin': 'timer_shutdown', 'method': 'get_state'},
    'timer_stop_player': {
        'package': 'timers', 'plugin': 'timer_stop_player', 'method': 'start',
        'argKeys': ['wait_seconds']},
    'timer_stop_player.cancel': {
        'package': 'timers', 'plugin': 'timer_stop_player', 'method': 'cancel'},
    'timer_stop_player.get_state': {
        'package': 'timers', 'plugin': 'timer_stop_player', 'method': 'get_state'},
    'timer_idle_shutdown': {
        'package': 'timers', 'plugin': 'timer_idle_shutdown', 'method': 'start',
        'argKeys': ['wait_seconds']},
    'timer_idle_shutdown.cancel': {
        'package': 'timers', 'plugin': 'timer_idle_shutdown', 'method': 'cancel'},
    'timer_idle_shutdown.get_state': {
        'package': 'timers', 'plugin': 'timer_idle_shutdown', 'method': 'get_state'},

    # ------------------------------------------------------------------
    # Host
    # ------------------------------------------------------------------
    'getAutohotspotStatus': {
        'package': 'host', 'plugin': 'get_autohotspot_status'},
    'startAutohotspot': {
        'package': 'host', 'plugin': 'start_autohotspot'},
    'stopAutohotspot': {
        'package': 'host', 'plugin': 'stop_autohotspot'},
    'getIpAddress': {
        'package': 'host', 'plugin': 'get_ip_address'},
    'getDiskUsage': {
        'package': 'host', 'plugin': 'get_disk_usage'},
    'reboot': {
        'package': 'host', 'plugin': 'reboot'},
    'shutdown': {
        'package': 'host', 'plugin': 'shutdown'},
    'say_my_ip': {
        'package': 'host', 'plugin': 'say_my_ip',
        'argKeys': ['option']},

    # ------------------------------------------------------------------
    # Misc (flat module: src/jukebox/components/misc.py)
    # ------------------------------------------------------------------
    'getAppSettings': {
        'package': 'misc', 'plugin': 'get_app_settings'},
    'setAppSettings': {
        'package': 'misc', 'plugin': 'set_app_settings',
        'argKeys': ['settings']},

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------
    'sync_rfidcards_all': {
        'package': 'sync_rfidcards', 'plugin': 'ctrl', 'method': 'sync_all'},
    'sync_rfidcards_change_on_rfid_scan': {
        'package': 'sync_rfidcards', 'plugin': 'ctrl',
        'method': 'sync_change_on_rfid_scan',
        'argKeys': ['option']},

    # ------------------------------------------------------------------
    # Podcasts
    # ------------------------------------------------------------------
    'searchPodcasts': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'search_podcasts',
        'argKeys': ['query']},
    'getPodcastEpisodes': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'get_episodes',
        'argKeys': ['feed_url', 'force_refresh']},
    'getPodcastInfo': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'get_podcast_info',
        'argKeys': ['feed_url']},
    'refreshPodcastFeed': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'refresh_feed',
        'argKeys': ['feed_url']},
    'podcastPlayerStatus': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'playerstatus'},
    'getPodcastStats': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'get_stats'},
    'play_podcast_series': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'play_podcast_series',
        'argKeys': ['feed_url']},
    'play_podcast_episode': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'play_podcast_episode',
        'argKeys': ['feed_url', 'episode_guid']},
    'getPodcastCacheStats': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'get_cache_stats'},
    'clearPodcastCache': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'clear_episode_cache'},
    'evictPodcastEpisode': {
        'package': 'player_podcast', 'plugin': 'ctrl', 'method': 'evict_episode',
        'argKeys': ['episode_guid']},

    # ------------------------------------------------------------------
    # Spotify
    # ------------------------------------------------------------------
    'spotifyGetConfig': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_spotify_config'},
    'spotifySetConfig': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'set_spotify_config',
        'argKeys': ['client_id', 'client_secret']},
    'spotifyGetAuthStatus': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_auth_status'},
    'spotifyGetAuthUrl': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_auth_url'},
    'spotifyAuthenticate': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'authenticate',
        'argKeys': ['auth_code']},
    'spotifyLogout': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'logout'},
    'spotifySearch': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'search',
        'argKeys': ['query', 'content_type', 'limit']},
    'spotifyGetUserPlaylists': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_user_playlists',
        'argKeys': ['limit', 'offset']},
    'spotifyGetUserAlbums': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_user_albums',
        'argKeys': ['limit', 'offset']},
    'spotifyGetContentDetails': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'get_content_details',
        'argKeys': ['uri']},
    'spotifyPlayContent': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'play_content',
        'argKeys': ['uri']},
    'play_spotify_card': {
        'package': 'player_spotify', 'plugin': 'ctrl', 'method': 'play_card',
        'argKeys': ['uri']},
}


# --------------------------------------------------------------
# Validator allowlists (Phase 5a)
# --------------------------------------------------------------
# The generator's validator builds a registry of registered plugin
# callables by AST-scanning ``src/jukebox/components/``. Some entries
# cannot be discovered statically:
#
# * flat modules that ``@plugs.register`` top-level functions and whose
#   package name does not match the directory (e.g. ``misc.py``);
# * timer plugins that register subclass instances dynamically.
#
# Entries here are accepted by the validator without further proof.
# Adding to this list should be rare and reviewed — every entry
# bypasses the contract drift guarantee.
KNOWN_PLUGIN_METHOD_ALLOWLIST = frozenset({
    # misc.py registers top-level functions; AST sees them, but the
    # package alias 'misc' is a flat-module case we whitelist for clarity.
    ('misc', 'get_app_settings', None),
    ('misc', 'set_app_settings', None),
    ('misc', 'empty_rpc_call', None),
    # Timer plugins register start/cancel/get_state via Timer subclass
    # instances in timers/__init__.py — not discoverable via @plugs.tag
    # because the methods live on the Timer base class.
    ('timers', 'timer_shutdown', 'start'),
    ('timers', 'timer_shutdown', 'cancel'),
    ('timers', 'timer_shutdown', 'get_state'),
    ('timers', 'timer_fade_volume', 'start'),
    ('timers', 'timer_fade_volume', 'cancel'),
    ('timers', 'timer_fade_volume', 'get_state'),
    ('timers', 'timer_stop_player', 'start'),
    ('timers', 'timer_stop_player', 'cancel'),
    ('timers', 'timer_stop_player', 'get_state'),
    ('timers', 'timer_idle_shutdown', 'start'),
    ('timers', 'timer_idle_shutdown', 'cancel'),
    ('timers', 'timer_idle_shutdown', 'get_state'),
})


# Backend-only RPCs the generator MUST NOT emit to the JS commands file.
# See project_phase_3b_followups.md #2 for the rationale behind
# ``playermpd.ctrl.play_single_passive`` (it bypasses coordinator
# activation; only ``playerpodcast`` is allowed to call it).
KNOWN_INTERNAL_PLUGIN_METHODS = frozenset({
    ('player', 'ctrl', 'play_single_passive'),
})

# TODO: Transfer RFID command from v2.3...

#
# ### Stop player
# CMDSTOP="%CMDSTOP%"
# ### Mute player
# CMDMUTE="%CMDMUTE%"
# ### Skip next track
# CMDNEXT="%CMDNEXT%"
# ### Skip previous track
# CMDPREV="%CMDPREV%"
# ### Restart the playlist
# CMDREWIND="%CMDREWIND%"
# ### Seek ahead 15 sec.
# CMDSEEKFORW="%CMDSEEKFORW%"
# ### Seek back 15 sec.
# CMDSEEKBACK="%CMDSEEKBACK%"
# ### Pause player
# CMDPAUSE="%CMDPAUSE%"
# ### Resume audio playout
# CMDPLAY="%CMDPLAY%"
# ### Toggle between speakers and bluetooth headphones
# CMDBLUETOOTHTOGGLE="%CMDBLUETOOTHTOGGLE%"
#
# CMDSHUFFLE="%CMDSHUFFLE%" --> Attention shuffle vs random is mixedup
#
#
#
#
# ## Wifi: switch on/off and other
# ### Enable Wifi
# ENABLEWIFI="%ENABLEWIFI%"
# ### Disable Wifi
# DISABLEWIFI="%DISABLEWIFI%"
# ### Toggle Wifi on/off
# TOGGLEWIFI="%TOGGLEWIFI%"
# ### Read out the Wifi IP over the Phoniebox speakers
# CMDREADWIFIIP="%CMDREADWIFIIP%"
#
# ## Recording audio commands
# ### Start recording for 10 sec. duration
# RECORDSTART10="%RECORDSTART10%"
# ### Start recording for 60 sec. duration
# RECORDSTART60="%RECORDSTART60%"
# ### Start recording for 600 sec. duration
# RECORDSTART600="%RECORDSTART600%"
# ### Stop recording
# RECORDSTOP="%RECORDSTOP%"
# ### Replay latest recording
# RECORDPLAYBACKLATEST="%RECORDPLAYBACKLATEST%"
#
#
# ### Switch between primary/secondary audio iFace --> this seems highly dodgy. Only changes iFace in global config, not mpd!
# CMDSWITCHAUDIOIFACE="%CMDSWITCHAUDIOIFACE%"
# ### Play custom playlist --> does not seem to be implemented (or rather only links to a single specifc folder)
# With new concept, simply choose a folder with m3u inside
# CMDPLAYCUSTOMPLS="%CMDPLAYCUSTOMPLS%"
