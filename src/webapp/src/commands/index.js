// THIS FILE IS AUTO-GENERATED — DO NOT EDIT BY HAND.
// Source of truth: src/jukebox/components/rpc_command_alias.py
//                  (web_command_definitions dictionary).
// Regenerate with: npm run generate-commands
// See Phase 5a, src/webapp/scripts/generate-commands.js for details.

const commands = {
  getSingleCoverArt: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'get_single_coverart',
  },
  getAlbumCoverArt: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'get_album_coverart',
  },
  directoryTreeOfAudiofolder: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'list_all_dirs',
  },
  albumList: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'list_albums',
  },
  songList: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'list_songs_by_artist_and_album',
  },
  getSongByUrl: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'get_song_by_url',
    argKeys: ['song_url'],
  },
  folderList: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'get_folder_content',
  },
  playerstatus: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'playerstatus',
  },
  play: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'play',
  },
  play_single: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'play_single',
    argKeys: ['song_url'],
  },
  play_folder: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'play_folder',
    argKeys: ['folder'],
  },
  play_album: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'play_album',
    argKeys: ['albumartist', 'album'],
  },
  pause: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'pause',
  },
  prev_song: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'prev',
  },
  next_song: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'next',
  },
  toggle: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'toggle',
  },
  shuffle: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'shuffle',
    argKeys: ['option'],
  },
  repeat: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'repeat',
    argKeys: ['option'],
  },
  seek: {
    _package: 'player',
    plugin: 'ctrl',
    method: 'seek',
  },
  cardsList: {
    _package: 'cards',
    plugin: 'list_cards',
  },
  registerCard: {
    _package: 'cards',
    plugin: 'register_card',
  },
  deleteCard: {
    _package: 'cards',
    plugin: 'delete_card',
  },
  setVolume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'set_volume',
    argKeys: ['volume'],
  },
  getVolume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'get_volume',
  },
  getMaxVolume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'get_soft_max_volume',
  },
  setMaxVolume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'set_soft_max_volume',
  },
  change_volume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'change_volume',
    argKeys: ['step'],
  },
  toggleMuteVolume: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'mute',
  },
  getAudioOutputs: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'get_outputs',
  },
  setAudioOutput: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'set_output',
    argKeys: ['sink_index'],
  },
  toggle_output: {
    _package: 'volume',
    plugin: 'ctrl',
    method: 'toggle_output',
  },
  timer_fade_volume: {
    _package: 'timers',
    plugin: 'timer_fade_volume',
    method: 'start',
    argKeys: ['wait_seconds'],
  },
  'timer_fade_volume.cancel': {
    _package: 'timers',
    plugin: 'timer_fade_volume',
    method: 'cancel',
  },
  'timer_fade_volume.get_state': {
    _package: 'timers',
    plugin: 'timer_fade_volume',
    method: 'get_state',
  },
  timer_shutdown: {
    _package: 'timers',
    plugin: 'timer_shutdown',
    method: 'start',
    argKeys: ['wait_seconds'],
  },
  'timer_shutdown.cancel': {
    _package: 'timers',
    plugin: 'timer_shutdown',
    method: 'cancel',
  },
  'timer_shutdown.get_state': {
    _package: 'timers',
    plugin: 'timer_shutdown',
    method: 'get_state',
  },
  timer_stop_player: {
    _package: 'timers',
    plugin: 'timer_stop_player',
    method: 'start',
    argKeys: ['wait_seconds'],
  },
  'timer_stop_player.cancel': {
    _package: 'timers',
    plugin: 'timer_stop_player',
    method: 'cancel',
  },
  'timer_stop_player.get_state': {
    _package: 'timers',
    plugin: 'timer_stop_player',
    method: 'get_state',
  },
  timer_idle_shutdown: {
    _package: 'timers',
    plugin: 'timer_idle_shutdown',
    method: 'start',
    argKeys: ['wait_seconds'],
  },
  'timer_idle_shutdown.cancel': {
    _package: 'timers',
    plugin: 'timer_idle_shutdown',
    method: 'cancel',
  },
  'timer_idle_shutdown.get_state': {
    _package: 'timers',
    plugin: 'timer_idle_shutdown',
    method: 'get_state',
  },
  getAutohotspotStatus: {
    _package: 'host',
    plugin: 'get_autohotspot_status',
  },
  startAutohotspot: {
    _package: 'host',
    plugin: 'start_autohotspot',
  },
  stopAutohotspot: {
    _package: 'host',
    plugin: 'stop_autohotspot',
  },
  getIpAddress: {
    _package: 'host',
    plugin: 'get_ip_address',
  },
  getDiskUsage: {
    _package: 'host',
    plugin: 'get_disk_usage',
  },
  reboot: {
    _package: 'host',
    plugin: 'reboot',
  },
  shutdown: {
    _package: 'host',
    plugin: 'shutdown',
  },
  say_my_ip: {
    _package: 'host',
    plugin: 'say_my_ip',
    argKeys: ['option'],
  },
  getAppSettings: {
    _package: 'misc',
    plugin: 'get_app_settings',
  },
  setAppSettings: {
    _package: 'misc',
    plugin: 'set_app_settings',
    argKeys: ['settings'],
  },
  sync_rfidcards_all: {
    _package: 'sync_rfidcards',
    plugin: 'ctrl',
    method: 'sync_all',
  },
  sync_rfidcards_change_on_rfid_scan: {
    _package: 'sync_rfidcards',
    plugin: 'ctrl',
    method: 'sync_change_on_rfid_scan',
    argKeys: ['option'],
  },
  searchPodcasts: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'search_podcasts',
    argKeys: ['query'],
  },
  getPodcastEpisodes: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'get_episodes',
    argKeys: ['feed_url', 'force_refresh'],
  },
  getPodcastInfo: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'get_podcast_info',
    argKeys: ['feed_url'],
  },
  refreshPodcastFeed: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'refresh_feed',
    argKeys: ['feed_url'],
  },
  podcastPlayerStatus: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'playerstatus',
  },
  getPodcastStats: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'get_stats',
  },
  play_podcast_series: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'play_podcast_series',
    argKeys: ['feed_url'],
  },
  play_podcast_episode: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'play_podcast_episode',
    argKeys: ['feed_url', 'episode_guid'],
  },
  getPodcastCacheStats: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'get_cache_stats',
  },
  clearPodcastCache: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'clear_episode_cache',
  },
  evictPodcastEpisode: {
    _package: 'player_podcast',
    plugin: 'ctrl',
    method: 'evict_episode',
    argKeys: ['episode_guid'],
  },
  spotifyGetConfig: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_spotify_config',
  },
  spotifySetConfig: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'set_spotify_config',
    argKeys: ['client_id', 'client_secret'],
  },
  spotifyGetAuthStatus: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_auth_status',
  },
  spotifyGetAuthUrl: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_auth_url',
  },
  spotifyAuthenticate: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'authenticate',
    argKeys: ['auth_code'],
  },
  spotifyLogout: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'logout',
  },
  spotifySearch: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'search',
    argKeys: ['query', 'content_type', 'limit'],
  },
  spotifyGetUserPlaylists: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_user_playlists',
    argKeys: ['limit', 'offset'],
  },
  spotifyGetUserAlbums: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_user_albums',
    argKeys: ['limit', 'offset'],
  },
  spotifyGetContentDetails: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'get_content_details',
    argKeys: ['uri'],
  },
  spotifyPlayContent: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'play_content',
    argKeys: ['uri'],
  },
  play_spotify_card: {
    _package: 'player_spotify',
    plugin: 'ctrl',
    method: 'play_card',
    argKeys: ['uri'],
  },
};

export default commands;
