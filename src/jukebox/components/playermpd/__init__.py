# -*- coding: utf-8 -*-
"""
Package for interfacing with the MPD Music Player Daemon

Status information in three topics
1) Player Status: published only on change
  This is a subset of the MPD status (and not the full MPD status) ??
  - folder
  - song
  - volume (volume is published only via player status, and not separatly to avoid too many Threads)
  - ...
2) Elapsed time: published every 250 ms, unless constant
  - elapsed
3) Folder Config: published only on change
   This belongs to the folder being played
   Publish:
   - random, resume, single, loop
   On save store this information:
   Contains the information for resume functionality of each folder
   - random, resume, single, loop
   - if resume:
     - current song, elapsed
   - what is PLAYSTATUS for?
   When to save
   - on stop
   Angstsave:
   - on pause (only if box get turned off without proper shutdown - else stop gets implicitly called)
   - on status change of random, resume, single, loop (for resume omit current status if currently playing- this has now meaning)
   Load checks:
   - if resume, but no song, elapsed -> log error and start from the beginning

Status storing:
  - Folder config for each folder (see above)
  - Information to restart last folder playback, which is:
    - last_folder -> folder_on_close
    - song, elapsed
    - random, resume, single, loop
    - if resume is enabled, after start we need to set last_played_folder, such that card swipe is detected as second swipe?!
      on the other hand: if resume is enabled, this is also saved to folder.config -> and that is checked by play card

Internal status
  - last played folder: Needed to detect second swipe


Saving {'player_status': {'last_played_folder': 'TraumfaengerStarkeLieder', 'CURRENTSONGPOS': '0', 'CURRENTFILENAME': 'TraumfaengerStarkeLieder/01.mp3'},
'audio_folder_status':
{'TraumfaengerStarkeLieder': {'ELAPSED': '1.0', 'CURRENTFILENAME': 'TraumfaengerStarkeLieder/01.mp3', 'CURRENTSONGPOS': '0', 'PLAYSTATUS': 'stop', 'RESUME': 'OFF', 'SHUFFLE': 'OFF', 'LOOP': 'OFF', 'SINGLE': 'OFF'},
'Giraffenaffen': {'ELAPSED': '1.0', 'CURRENTFILENAME': 'TraumfaengerStarkeLieder/01.mp3', 'CURRENTSONGPOS': '0', 'PLAYSTATUS': 'play', 'RESUME': 'OFF', 'SHUFFLE': 'OFF', 'LOOP': 'OFF', 'SINGLE': 'OFF'}}}

Activation vs. passive control (Phase 3a)
-----------------------------------------

The :class:`PlayerCoordinator` decides which backend is *active* (i.e.
audible). Phase 3a pinned a uniform rule for which RPCs trigger an
activation handoff via ``coordinator.activate()`` and which do not:

  **Activation events** -- start/restart/resume playback:
      ``play``, ``play_single``, ``resume``, ``play_folder``,
      ``play_album``, ``play_card`` (transitively via ``play_folder``),
      and ``replay`` / ``replay_if_stopped`` (transitively).
      Each calls ``self._activate_mpd()``.

  **Passive controls** -- modify the current session, never re-claim:
      ``stop``, ``pause``, ``toggle``, ``next``, ``prev``,
      ``shuffle``, ``repeat``, ``seek``, ``rewind``, ``set_volume``,
      ``get_volume``. These bypass the coordinator entirely.

Rationale: re-claiming on a passive op would *steal* playback from
whoever the user just handed off to. The only safe re-claim trigger
is a user-initiated playback start (RPC or RFID swipe). The same
rule applies to podcast and Spotify backends; see
:mod:`components.player.coordinator` for the cross-backend statement.

References:
https://github.com/Mic92/python-mpd2
https://python-mpd2.readthedocs.io/en/latest/topics/commands.html
https://mpd.readthedocs.io/en/latest/protocol.html

sudo -u mpd speaker-test -t wav -c 2
"""  # noqa: E501
# Warum ist "Second Swipe" im Player und nicht im RFID Reader?
# Second swipe ist abhängig vom Player State - nicht vom RFID state.
# Beispiel: RFID triggered Folder1, Web App triggered Folder2, RFID Folder1:
# Dann muss das 2. Mal Folder1 auch als "first swipe" gewertet werden.
# Wenn der RFID das basierend auf IDs macht, kann der nicht  unterscheiden und glaubt es ist 2. Swipe.
# Beispiel 2: Jemand hat RFID Reader (oder 1x RFID und 1x Barcode Scanner oder so) angeschlossen. Liest zuerst Karte mit
# Reader 1 und dann mit Reader 2: Reader 2 weiß nicht, was bei Reader 1 passiert ist und denkt es ist 1. swipe.
# Beispiel 3: RFID trigered Folder1, Playlist läuft durch und hat schon gestoppt, dann wird die Karte wieder vorgehalten.
# Dann muss das als 1. Swipe gewertet werden
# Beispiel 4: RFID triggered "Folder1", dann wird Karte "Volume Up" aufgelegt, dann wieder Karte "Folder1": Auch das ist
# aus Sicht ders Playbacks 2nd Swipe
# 2nd Swipe ist keine im Reader festgelegte Funktion extra fur den Player.
#
# In der aktuellen Implementierung weiß der Player (der second "swipe" dekodiert) überhaupt nichts vom RFID.
# Im Prinzip gibt es zwei "Play" Funktionen: (1) play always from start und (2) play with toggle action.
# Die Web App ruft immer (1) auf und die RFID immer (2). Jetzt kann man sogar für einige Karten sagen
# immer (1) - also kein Second Swipe und für andere (2).
# Sollte der Reader das Swcond swipe dekodieren, muss aber der Reader den Status des Player kennen.
# Das ist allerdings ein Problem. In Version 2 ist das nicht aufgefallen,
# weil alles uber File I/Os lief - Thread safe ist das nicht!
#
# Beispiel: Second swipe bei anderen Funktionen, hier: WiFi on/off.
# Was die Karte Action tut ist ein Toggle. Der Toggle hängt vom Wifi State ab, den der RFID Kartenleser nicht kennt.
# Den kann der Leser auch nicht tracken. Der State kann ja auch über die Web App oder Kommandozeile geändert werden.
# Toggle (und 2nd Swipe generell) ist immer vom Status des Zielsystems abhängig und kann damit nur vom Zielsystem geändert
# werden. Bei Wifi also braucht man 3 Funktionen: on / off / toggle. Toggle ist dann first swipe / second swipe

import os
import mpd
import logging
import time
import functools
from pathlib import Path
import components.player
from components.player.coordinator import get_coordinator
import jukebox.cfghandler
import jukebox.utils as utils
import jukebox.plugs as plugs
import jukebox.multitimer as multitimer
import jukebox.publishing as publishing
import jukebox.playlistgenerator as playlistgenerator
import misc

from .playcontentcallback import PlayContentCallbacks, PlayCardState
from .coverart_cache_manager import CoverartCacheManager
from .state_store import MPDStateStore, SwipeDecision, decide_swipe
from .mpd_client import MPDClientWrapper

logger = logging.getLogger('jb.PlayerMPD')
cfg = jukebox.cfghandler.get_handler('jukebox')


# Phase 6: per-plugin config schema (see jukebox.plug_schema). ``host``
# is the only field whose absence would crash the MPD client wrapper
# immediately on connect, so it's the only required field. Other
# fields have defaults elsewhere in the code or are honoured if
# present.
plugs_config_section = ['playermpd']
plugs_config_schema = {
    'host': {
        'type': str,
        'required': True,
    },
    'status_file': str,
    'music_library_path': str,
    'second_swipe_action': dict,
}


class PlayerMPD:
    """Interface to MPD Music Player Daemon"""

    def __init__(self):
        self.mpd_host = cfg.getn('playermpd', 'host')
        self.status_file = cfg.getn('playermpd', 'status_file')

        # State persistence: dict, JSON load/save, and the state_lock all
        # live in MPDStateStore (Phase 3a). The ``music_player_status``,
        # ``current_folder_status``, and ``state_lock`` attributes below
        # are kept as aliases for back-compat — the test suite and a few
        # call sites still reach for them directly.
        self.state_store = MPDStateStore(self.status_file)
        # DEPRECATED: prefer self.state_store.state_lock; remove after
        # call-site sweep in a later phase.
        self.state_lock = self.state_store.state_lock

        self.second_swipe_action_dict = {'toggle': self.toggle,
                                         'play': self.play,
                                         'skip': self.next,
                                         'rewind': self.rewind,
                                         'replay': self.replay,
                                         'replay_if_stopped': self.replay_if_stopped}
        self.second_swipe_action = None
        self.decode_2nd_swipe_option()

        self.end_of_playlist_next_action = utils.get_config_action(cfg,
                                                                   'playermpd',
                                                                   'end_of_playlist_next_action',
                                                                   'none',
                                                                   {'rewind': self.rewind,
                                                                    'stop': self.stop,
                                                                    'none': lambda: None},
                                                                   logger)
        self.stopped_prev_action = utils.get_config_action(cfg,
                                                           'playermpd',
                                                           'stopped_prev_action',
                                                           'prev',
                                                           {'rewind': self.rewind,
                                                            'prev': self._prev_in_stopped_state,
                                                            'none': lambda: None},
                                                           logger)
        self.stopped_next_action = utils.get_config_action(cfg,
                                                          'playermpd',
                                                          'stopped_next_action',
                                                          'next',
                                                          {'rewind': self.rewind,
                                                           'next': self._next_in_stopped_state,
                                                           'none': lambda: None},
                                                          logger)

        self.mpd_client = mpd.MPDClient()
        self.coverart_cache_manager = CoverartCacheManager()

        # The timeout refer to the low-level socket time-out
        # If these are too short and the response is not fast enough (due to the PI being busy),
        # the current MPC command times out. Leave these at blocking calls, since we do not react on a timed out socket
        # in any relevant matter anyway
        self.mpd_client.timeout = None               # network timeout in seconds (floats allowed), default: None
        self.mpd_client.idletimeout = None           # timeout for fetching the result of the idle command
        # MPDClientWrapper (Phase 3a) owns the wire mutex + lazy-reconnect
        # path. ``self.mpd_lock`` is kept as an alias so the dozens of
        # ``with self.mpd_lock:`` call sites need no churn.
        self.mpd_wrapper = MPDClientWrapper(self.mpd_client, self.mpd_host, 6600)
        # DEPRECATED: prefer self.mpd_wrapper (or self.mpd_client.* for
        # direct access); remove after call-site sweep in a later phase.
        self.mpd_lock = self.mpd_wrapper
        self.connect()
        logger.info(f"Connected to MPD Version: {self.mpd_client.mpd_version}")

        last_played_folder = self.state_store.last_played_folder()
        if last_played_folder:
            existing = self.state_store.get_folder_status(last_played_folder)
            if existing is not None:
                self.state_store.current_folder_status = existing
            # Restore the playlist status in mpd
            # But what about playback position?
            self.mpd_client.clear()
            #  This could fail and cause load fail of entire package:
            # self.mpd_client.add(last_played_folder)
            logger.info(f"Last Played Folder: {last_played_folder}")

        # Phase 3a fix: clear only the *swipe* marker on startup, not the
        # last-played folder itself. The prior code wiped last_played_folder
        # here, which had two consequences:
        #   (1) the first swipe after reboot of the same card always looked
        #       like a first swipe (correct, by accident);
        #   (2) ``replay`` / ``replay_if_stopped`` lost their resume target
        #       across reboots (incorrect, the user-visible bug).
        # With ``last_swiped_folder`` as the second-swipe marker we can
        # clear it independently and keep last_played_folder for resume.
        self.state_store.clear_last_swiped_folder()

        self.old_song = None
        self.mpd_status = {}
        self.mpd_status_poll_interval = 0.25
        # ``state_lock`` (from MPDStateStore) guards mutations of
        # ``music_player_status``, ``current_folder_status``, and
        # ``mpd_status`` between the poll thread and RPC threads. Distinct
        # from ``mpd_lock`` (which serialises the MPD wire) so we can take
        # both without ordering hazards: poll thread takes mpd_lock for
        # the wire call, releases it, then takes state_lock for the dict
        # updates.
        self.status_is_closing = False
        # self.status_thread = threading.Timer(self.mpd_status_poll_interval, self._mpd_status_poll).start()

        self.status_thread = multitimer.GenericEndlessTimerClass('mpd.timer_status',
                                                                 self.mpd_status_poll_interval, self._mpd_status_poll)
        self.status_thread.start()

    # DEPRECATED: prefer self.state_store.* / self.mpd_client.*; remove
    # after call-site sweep in a later phase.
    @property
    def music_player_status(self):
        """Back-compat alias for ``state_store.music_player_status``.

        Tests and a few legacy call sites read this attribute directly;
        retaining the property avoids a wide call-site sweep in this phase.
        New code should go through ``self.state_store`` instead.
        """
        return self.state_store.music_player_status

    # DEPRECATED: prefer self.state_store.current_folder_status; remove
    # after call-site sweep in a later phase.
    @property
    def current_folder_status(self):
        """Back-compat alias for ``state_store.current_folder_status``."""
        return self.state_store.current_folder_status

    @current_folder_status.setter
    def current_folder_status(self, value):
        self.state_store.current_folder_status = value

    def _save_state(self):
        """Persist state via :class:`MPDStateStore` (atomic snapshot)."""
        return self.state_store.save()

    def exit(self):
        logger.debug("Exit routine of playermpd started")
        self.status_is_closing = True
        self.status_thread.cancel()
        self.mpd_client.disconnect()
        self._save_state()
        return self.status_thread.timer_thread

    def connect(self):
        self.mpd_wrapper.connect()

    def decode_2nd_swipe_option(self):
        cfg_2nd_swipe_action = cfg.setndefault('playermpd', 'second_swipe_action', 'alias', value='none').lower()
        if cfg_2nd_swipe_action not in [*self.second_swipe_action_dict.keys(), 'none', 'custom']:
            logger.error(f"Config mpd.second_swipe_action must be one of "
                         f"{[*self.second_swipe_action_dict.keys(), 'none', 'custom']}. Ignore setting.")
        if cfg_2nd_swipe_action in self.second_swipe_action_dict.keys():
            self.second_swipe_action = self.second_swipe_action_dict[cfg_2nd_swipe_action]
        if cfg_2nd_swipe_action == 'custom':
            custom_action = utils.decode_rpc_call(cfg.getn('playermpd', 'second_swipe_action', default=None))
            self.second_swipe_action = functools.partial(plugs.call_ignore_errors,
                                                         custom_action['package'],
                                                         custom_action['plugin'],
                                                         custom_action['method'],
                                                         custom_action['args'],
                                                         custom_action['kwargs'])

    def mpd_retry_with_mutex(self, mpd_cmd, *args):
        """Thin pass-through to :meth:`MPDClientWrapper.call_with_retry`.

        Phase 3a moved the lock + error-swallow logic into the wrapper.
        This shim is kept for two reasons: (1) it is part of the
        class's public surface and other plugs may reach for it, and
        (2) the name is referenced by source-grep tests we don't want
        to churn in this commit.
        """
        return self.mpd_wrapper.call_with_retry(mpd_cmd, *args)

    def _activate_mpd(self):
        """Claim the active-player slot via the coordinator.

        The coordinator runs the outgoing backend's pause-then-stop
        (so Spotify's resume position is preserved before its session
        is torn down), bounded by a 5s timeout. Idempotent when MPD
        is already current.
        """
        coordinator = get_coordinator()
        with coordinator.activate('mpd'):
            pass

    def _mpd_status_poll(self):
        """
        this method polls the status from mpd and stores the important inforamtion in the music_player_status,
        it will repeat itself in the intervall specified by self.mpd_status_poll_interval

        ``state_lock`` guards the dict mutations against concurrent RPC reads
        (``_save_state``, status RPCs) so neither side observes a torn dict.
        The MPD wire call sits *outside* the state_lock — we read from MPD
        first, then merge under state_lock.
        """
        new_status = self.mpd_retry_with_mutex(self.mpd_client.status) or {}
        new_song = self.mpd_retry_with_mutex(self.mpd_client.currentsong) or {}

        # ``plugs.call`` to player_podcast may be slow; do it outside the lock.
        # The dict update is harmless and is re-protected below.
        podcast_overlay = None
        candidate_file = new_song.get('file', '')
        if candidate_file and (candidate_file.startswith('http://') or candidate_file.startswith('https://')):
            try:
                podcast_status = plugs.call('player_podcast', 'ctrl', 'playerstatus')
                if podcast_status and podcast_status.get('title'):
                    podcast_overlay = {
                        'title': podcast_status.get('title'),
                        'artist': podcast_status.get('artist'),
                        'album': podcast_status.get('album'),
                        'songid': podcast_status.get('songid'),
                        'coverart_url': podcast_status.get('coverart_url'),
                    }
            except Exception:
                pass  # Podcast player not active or not available

        # All dict-merge logic lives in ``MPDStateStore.apply_poll`` so
        # the rules are regression-tested without booting MPD (Phase 3a
        # follow-up; reviewer ask #2). The podcast overlay merges in
        # after apply_poll because the published snapshot must include
        # podcast fields while the persisted state must not.
        published_snapshot = self.state_store.apply_poll(
            new_status, new_song, self.mpd_status,
        )
        if podcast_overlay:
            # Re-take the lock briefly to fold the overlay into both the
            # running buffer and the snapshot we publish. The overlay is
            # informational (title/artist for podcast HTTP URLs) so we
            # don't gate it on the state-merge above.
            with self.state_lock:
                self.mpd_status.update(podcast_overlay)
                published_snapshot.update(podcast_overlay)

        if get_coordinator().current() == 'mpd':
            publishing.get_publisher().send('playerstatus', published_snapshot)

    # MPD can play absolute paths but can find songs in its database only by relative path
    # This function aims to prepare the song_url accordingly
    def harmonize_mpd_url(self, song_url):
        _music_library_path_absolute = os.path.expanduser(components.player.get_music_library_path())
        song_url = song_url.replace(f'{_music_library_path_absolute}/', '')

        return song_url

    @plugs.tag
    def get_player_type_and_version(self):
        # python-mpd2 exposes ``mpd_version`` as a *property* (string-valued),
        # not a callable. The previous parenthesised form raised TypeError on
        # real MPD clients and was only masked in tests by the
        # ``_MPDVersionString`` shim in ``test/conftest.py`` (removed in this
        # commit — Phase 0b loose end).
        with self.mpd_lock:
            value = self.mpd_client.mpd_version
        return value

    @plugs.tag
    def update(self):
        with self.mpd_lock:
            state = self.mpd_client.update()
        return state

    @plugs.tag
    def update_wait(self):
        state = self.update()
        self._db_wait_for_update(state)
        return state

    @plugs.tag
    def play(self):
        self._activate_mpd()
        with self.mpd_lock:
            self.mpd_client.play()

    @plugs.tag
    def stop(self):
        with self.mpd_lock:
            self.mpd_client.stop()

    @plugs.tag
    def pause(self, state: int = 1):
        """Enforce pause to state (1: pause, 0: resume)

        This is what you want as card removal action: pause the playback, so it can be resumed when card is placed
        on the reader again. What happens on re-placement depends on configured second swipe option
        """
        with self.mpd_lock:
            self.mpd_client.pause(state)

    def _is_podcast_active(self):
        """Check if the podcast player is currently driving playback.

        Returns False if the podcast plugin is not loaded or not active."""
        try:
            return plugs.call('player_podcast', 'ctrl', 'is_podcast_active')
        except Exception:
            return False

    @plugs.tag
    def prev(self):
        logger.debug("Prev")
        # Delegate to podcast player if it is driving playback
        if self._is_podcast_active():
            logger.debug('Podcast active, delegating prev to podcast player')
            return plugs.call('player_podcast', 'ctrl', 'prev')
        if self.mpd_status['state'] == 'stop':
            logger.debug('Player is stopped, calling stopped_prev_action')
            return self.stopped_prev_action()
        try:
            with self.mpd_lock:
                self.mpd_client.previous()
        except mpd.base.CommandError:
            # This shouldn't happen in reality, but we still catch
            # this error to avoid crashing the player thread:
            logger.warning('Failed to go to previous song, ignoring')

    def _prev_in_stopped_state(self):
        with self.mpd_lock:
            self.mpd_client.play(max(0, int(self.mpd_status['pos']) - 1))

    @plugs.tag
    def next(self):
        """Play next track in current playlist"""
        logger.debug("Next")
        # Delegate to podcast player if it is driving playback
        if self._is_podcast_active():
            logger.debug('Podcast active, delegating next to podcast player')
            return plugs.call('player_podcast', 'ctrl', 'next')
        if self.mpd_status['state'] == 'stop':
            logger.debug('Player is stopped, calling stopped_next_action')
            return self.stopped_next_action()
        playlist_len = int(self.mpd_status.get('playlistlength', -1))
        current_pos = int(self.mpd_status.get('pos', 0))
        if current_pos == playlist_len - 1:
            logger.debug(f'next() called during last song ({current_pos}) of '
                         f'playlist (len={playlist_len}), running end_of_playlist_next_action.')
            return self.end_of_playlist_next_action()
        try:
            with self.mpd_lock:
                self.mpd_client.next()
        except mpd.base.CommandError:
            # This shouldn't happen in reality, but we still catch
            # this error to avoid crashing the player thread:
            logger.warning('Failed to go to next song, ignoring')

    def _next_in_stopped_state(self):
        pos = int(self.mpd_status['pos']) + 1
        if pos > int(self.mpd_status['playlistlength']) - 1:
            return self.end_of_playlist_next_action()
        with self.mpd_lock:
            self.mpd_client.play(pos)

    @plugs.tag
    def seek(self, new_time):
        with self.mpd_lock:
            # Try using seek(songpos, time) first - works better for HTTP streams
            # If that fails, fall back to seekcur
            try:
                status = self.mpd_client.status()
                songpos = int(status.get('song', 0))
                logger.info(f"[SEEK-DEBUG] Attempting seek to position {songpos}, time {new_time}")
                self.mpd_client.seek(songpos, new_time)
                logger.info("[SEEK-DEBUG] Seek successful using seek(songpos, time)")
            except Exception as e:
                # Fallback to seekcur for compatibility
                logger.warning(f"[SEEK-DEBUG] seek(songpos, time) failed: {e}, trying seekcur")
                self.mpd_client.seekcur(new_time)
                logger.info("[SEEK-DEBUG] Seek successful using seekcur")

    @plugs.tag
    def rewind(self):
        """
        Re-start current playlist from first track

        Note: Will not re-read folder config, but leave settings untouched"""
        logger.debug("Rewind")
        with self.mpd_lock:
            self.mpd_client.play(0)

    @plugs.tag
    def replay(self):
        """
        Re-start playing the last-played folder

        Will reset settings to folder config"""
        logger.debug("Replay")
        with self.mpd_lock:
            self.play_folder(self.state_store.last_played_folder())

    @plugs.tag
    def toggle(self):
        """Toggle pause state, i.e. do a pause / resume depending on current state"""
        with self.mpd_lock:
            self.mpd_client.pause()

    @plugs.tag
    def replay_if_stopped(self):
        """
        Re-start playing the last-played folder unless playlist is still playing

        > [!NOTE]
        > To me this seems much like the behaviour of play,
        > but we keep it as it is specifically implemented in box 2.X"""
        with self.mpd_lock:
            if self.mpd_status['state'] == 'stop':
                self.play_folder(self.state_store.last_played_folder())

    # Shuffle
    def _shuffle(self, random):
        # As long as we don't work with waiting lists (aka playlist), this implementation is ok!
        self.mpd_retry_with_mutex(self.mpd_client.random, 1 if random else 0)

    @plugs.tag
    def shuffle(self, option='toggle'):
        if option == 'toggle':
            if self.mpd_status['random'] == '0':
                self._shuffle(1)
            else:
                self._shuffle(0)
        elif option == 'enable':
            self._shuffle(1)
        elif option == 'disable':
            self._shuffle(0)
        else:
            logger.error(f"'{option}' does not exist for 'shuffle'")

    # Repeat
    def _repeatmode(self, mode):
        if mode == 'repeat':
            repeat = 1
            single = 0
        elif mode == 'single':
            repeat = 1
            single = 1
        else:
            repeat = 0
            single = 0

        with self.mpd_lock:
            self.mpd_client.repeat(repeat)
            self.mpd_client.single(single)

    @plugs.tag
    def repeat(self, option='toggle'):
        if option == 'toggle':
            if self.mpd_status['repeat'] == '0':
                self._repeatmode('repeat')
            elif self.mpd_status['repeat'] == '1' and self.mpd_status['single'] == '0':
                self._repeatmode('single')
            else:
                self._repeatmode(None)
        elif option == 'toggle_repeat':
            if self.mpd_status['repeat'] == '0':
                self._repeatmode('repeat')
            else:
                self._repeatmode(None)
        elif option == 'toggle_repeat_single':
            if self.mpd_status['single'] == '0':
                self._repeatmode('single')
            else:
                self._repeatmode(None)
        elif option == 'enable_repeat':
            self._repeatmode('repeat')
        elif option == 'enable_repeat_single':
            self._repeatmode('single')
        elif option == 'disable':
            self._repeatmode(None)
        else:
            logger.error(f"'{option}' does not exist for 'repeat'")

    @plugs.tag
    def get_current_song(self, param):
        return self.mpd_status

    @plugs.tag
    def map_filename_to_playlist_pos(self, filename):
        # self.mpd_client.playlistfind()
        raise NotImplementedError

    @plugs.tag
    def remove(self):
        raise NotImplementedError

    @plugs.tag
    def move(self):
        # song_id = param.get("song_id")
        # step = param.get("step")
        # MPDClient.playlistmove(name, from, to)
        # MPDClient.swapid(song1, song2)
        raise NotImplementedError

    @plugs.tag
    def play_single(self, song_url):
        self._activate_mpd()
        with self.mpd_lock:
            self.mpd_client.clear()
            self.mpd_client.addid(song_url)
            self.mpd_client.play()

    @plugs.tag
    def play_single_passive(self, song_url):
        """Drive MPD wire to play a single URL without claiming activation.

        Phase 2 FU#2 / Phase 3b: ``play_single`` calls ``_activate_mpd()``
        which moves the coordinator's active backend to ``'mpd'``. That
        is the right behaviour when MPD itself is the user-facing
        backend, but **wrong** for the podcast player. Podcast plays
        *through* MPD's wire but the user-facing backend is
        ``'podcast'`` - so podcast pins itself as active via
        ``_activate_podcast()`` before driving MPD here. Calling the
        regular ``play_single`` from podcast would race the coordinator
        back to ``'mpd'`` and make ``coordinator.current()`` lie to the
        UI about which backend originated the playback.

        Only ``playerpodcast`` is expected to use this. Future
        cross-backend wrappers (e.g. a hypothetical playlist
        aggregator) could use it too provided they own the coordinator
        slot themselves.
        """
        with self.mpd_lock:
            self.mpd_client.clear()
            self.mpd_client.addid(song_url)
            self.mpd_client.play()

    @plugs.tag
    def resume(self):
        self._activate_mpd()
        with self.mpd_lock:
            songpos = self.current_folder_status["CURRENTSONGPOS"]
            elapsed = self.current_folder_status["ELAPSED"]
            self.mpd_client.seek(songpos, elapsed)
            self.mpd_client.play()

    @plugs.tag
    def play_card(self, folder: str, recursive: bool = False):
        """
        Main entry point for trigger music playing from RFID reader. Decodes second swipe options before playing folder content

        Checks for second (or multiple) trigger of the same folder and calls first swipe / second swipe action
        accordingly.

        :param folder: Folder path relative to music library path
        :param recursive: Add folder recursively
        """
        # Developer notes (preserved from the prior implementation):
        #
        #   * A 2nd-swipe trigger may also happen if the playlist has
        #     already stopped playing → generally treat as first swipe
        #     (current code does *not* distinguish; left as a known
        #     limitation, not regressed by this commit).
        #   * 2nd swipe of the same Card ID after a different song was
        #     played via the WebUI → treat as first swipe; handled
        #     correctly because ``last_swiped_folder`` is rewritten by
        #     whatever swipe triggered the WebUI flow.
        #   * place-not-swipe: card stays on reader until playlist
        #     expires; on re-placement we want first-swipe behaviour
        #     → also handled correctly because the card removal action
        #     does not clear ``last_swiped_folder`` (see rfid.yaml).
        #
        # Phase 3a fix: second-swipe detection now compares against
        # ``last_swiped_folder``, not ``last_played_folder``. The store
        # clears ``last_swiped_folder`` at startup so the first swipe
        # after reboot of the last-played card plays it (instead of
        # being misread as a 2nd swipe). ``last_played_folder`` is
        # preserved across reboots for the resume / replay use case.
        #
        # The decision itself lives in ``decide_swipe`` (state_store.py)
        # — a pure function over (store, folder, second_swipe_action) —
        # so the four behavioural scenarios (first / repeat-same /
        # different / post-reboot) are unit-testable without booting
        # MPD or the plugin system. ``play_card`` owns the *mutation*
        # (``set_last_swiped_folder``) so the decision function stays
        # side-effect-free.
        decision = decide_swipe(self.state_store, folder, self.second_swipe_action)
        logger.debug(
            f"last_swiped_folder = {self.state_store.last_swiped_folder()!r}, "
            f"folder = {folder!r}, decision = {decision.value}"
        )

        # Record this swipe regardless of outcome. The marker survives
        # within a session; the store clears it on next startup.
        self.state_store.set_last_swiped_folder(folder)

        if decision is SwipeDecision.SECOND_TOGGLE:
            logger.debug('Calling second swipe action')

            # run callbacks before second_swipe_action is invoked
            play_card_callbacks.run_callbacks(folder, PlayCardState.secondSwipe)

            self.second_swipe_action()
        else:
            logger.debug('Calling first swipe action')

            # run callbacks before play_folder is invoked
            play_card_callbacks.run_callbacks(folder, PlayCardState.firstSwipe)

            self.play_folder(folder, recursive)

    @plugs.tag
    def get_single_coverart(self, song_url):
        # Check if this is a podcast URL (http/https)
        if song_url and (song_url.startswith('http://') or song_url.startswith('https://')):
            # Delegate to podcast player for podcast cover art
            try:
                logger.info(f"Delegating coverart request for podcast URL: {song_url}")
                result = plugs.call('player_podcast', 'ctrl', 'get_coverart', args=(song_url,))
                logger.info(f"Podcast coverart result: {result}")
                return result
            except Exception as e:
                logger.error(f"Failed to get podcast coverart: {e}", exc_info=True)
                return ''  # Podcast player not available or no cover art

        # Handle local files normally
        mp3_file_path = Path(components.player.get_music_library_path(), song_url).expanduser()
        cache_filename = self.coverart_cache_manager.get_cache_filename(mp3_file_path)

        return cache_filename

    @plugs.tag
    def get_album_coverart(self, albumartist: str, album: str):
        song_list = self.list_songs_by_artist_and_album(albumartist, album)

        return self.get_single_coverart(song_list[0]['file'])

    @plugs.tag
    def flush_coverart_cache(self):
        """
        Deletes the Cover Art Cache
        """

        return self.coverart_cache_manager.flush_cache()

    @plugs.tag
    def get_folder_content(self, folder: str):
        """
        Get the folder content as content list with meta-information. Depth is always 1.

        Call repeatedly to descend in hierarchy

        :param folder: Folder path relative to music library path
        """
        plc = playlistgenerator.PlaylistCollector(components.player.get_music_library_path())
        plc.get_directory_content(folder)
        return plc.playlist

    def _record_play_folder_state(self, folder: str) -> None:
        """State-update path for play_folder (Phase 3a split).

        Updates ``last_played_folder`` (the resume target) and points
        ``current_folder_status`` at the entry for ``folder`` (creating
        it if missing), then persists to disk. No MPD wire activity.

        Separated from the playback trigger so tests can assert state
        bookkeeping in isolation, and so future call sites that want
        to record a folder *without* triggering playback have a hook.
        """
        self.state_store.set_last_played_folder(folder)
        self.state_store.set_current_folder_status(folder)
        self._save_state()

    def _trigger_play_folder(self, folder: str, recursive: bool) -> None:
        """Playback-trigger path for play_folder (Phase 3a split).

        Activates MPD via the coordinator, clears the queue, enumerates
        the folder via :class:`playlistgenerator.PlaylistCollector`,
        adds tracks one-by-one, then calls play(). Does NOT touch
        persisted state — see :meth:`_record_play_folder_state`.
        """
        self._activate_mpd()
        with self.mpd_lock:
            logger.info(f"Play folder: '{folder}'")
            self.mpd_client.clear()

            plc = playlistgenerator.PlaylistCollector(components.player.get_music_library_path())
            plc.parse(folder, recursive)
            uri = '--unset--'
            try:
                for uri in plc:
                    self.mpd_client.addid(uri)
            except mpd.base.CommandError as e:
                logger.error(f"{e.__class__.__qualname__}: {e} at uri {uri}")
            except Exception as e:
                logger.error(f"{e.__class__.__qualname__}: {e} at uri {uri}")

            self.mpd_client.play()

    @plugs.tag
    def play_folder(self, folder: str, recursive: bool = False) -> None:
        """
        Playback a music folder.

        Folder content is added to the playlist as described by :mod:`jukebox.playlistgenerator`.
        The playlist is cleared first.

        Internally split (Phase 3a) into a state-update step and a
        playback-trigger step. The state step runs *first* so a wedged
        MPD wire still leaves last_played_folder consistent with the
        user's intent (matches the prior behaviour where the writes
        sat inside the same with-block).

        :param folder: Folder path relative to music library path
        :param recursive: Add folder recursively
        """
        self._record_play_folder_state(folder)
        self._trigger_play_folder(folder, recursive)

    @plugs.tag
    def play_album(self, albumartist: str, album: str):
        """
        Playback a album found in MPD database.

        All album songs are added to the playlist
        The playlist is cleared first.

        :param albumartist: Artist of the Album provided by MPD database
        :param album: Album name provided by MPD database
        """
        self._activate_mpd()
        with self.mpd_lock:
            logger.info(f"Play album: '{album}' by '{albumartist}")
            self.mpd_client.clear()
            self.mpd_retry_with_mutex(self.mpd_client.findadd, 'albumartist', albumartist, 'album', album)
            self.mpd_client.play()

    @plugs.tag
    def queue_load(self, folder):
        # There was something playing before -> stop and save state
        # Clear the queue
        # Check / Create the playlist
        #  - not needed if same folder is played again? Buf what if files have been added a mpc update has been run?
        #  - and this a re-trigger to start the new playlist
        # If we must update the playlists everytime anyway why write them to file and not just keep them in the queue?
        # Load the playlist
        # Get folder config and apply settings
        pass

    @plugs.tag
    def playerstatus(self):
        return self.mpd_status

    @plugs.tag
    def playlistinfo(self):
        with self.mpd_lock:
            value = self.mpd_client.playlistinfo()
        return value

    # Attention: MPD.listal will consume a lot of memory with large libs.. should be refactored at some point
    @plugs.tag
    def list_all_dirs(self):
        with self.mpd_lock:
            result = self.mpd_client.listall()
            # list = [entry for entry in list if 'directory' in entry]
        return result

    @plugs.tag
    def list_albums(self):
        with self.mpd_lock:
            album_list = self.mpd_retry_with_mutex(self.mpd_client.list, 'album', 'group', 'albumartist')

        return album_list

    @plugs.tag
    def list_songs_by_artist_and_album(self, albumartist, album):
        with self.mpd_lock:
            song_list = self.mpd_retry_with_mutex(self.mpd_client.find, 'albumartist', albumartist, 'album', album)

        return song_list

    @plugs.tag
    def get_song_by_url(self, song_url):
        song_url = self.harmonize_mpd_url(song_url)

        with self.mpd_lock:
            song = self.mpd_retry_with_mutex(self.mpd_client.find, 'file', song_url)

        return song

    def get_volume(self):
        """
        Get the current volume

        For volume control do not use directly, but use through the plugin 'volume',
        as the user may have configured a volume control manager other than MPD"""
        with self.mpd_lock:
            volume = self.mpd_client.status().get('volume')
        return int(volume)

    def set_volume(self, volume):
        """
        Set the volume

        For volume control do not use directly, but use through the plugin 'volume',
        as the user may have configured a volume control manager other than MPD"""
        with self.mpd_lock:
            self.mpd_client.setvol(volume)
        return self.get_volume()

    def _db_wait_for_update(self, update_id: int):
        logger.debug("Waiting for update to finish")
        while self._db_is_updating(update_id):
            # a little throttling
            time.sleep(0.1)

    def _db_is_updating(self, update_id: int):
        with self.mpd_lock:
            _status = self.mpd_client.status()
            _cur_update_id = _status.get('updating_db')
            if _cur_update_id is not None and int(_cur_update_id) <= int(update_id):
                return True
            else:
                return False


# ---------------------------------------------------------------------------
# Plugin Initializer / Finalizer
# ---------------------------------------------------------------------------

player_ctrl: PlayerMPD
#: Callback handler instance for play_card events.
#: - is executed when play_card function is called
#: States:
#: - See :class:`PlayCardState`
#: See :class:`PlayContentCallbacks`
play_card_callbacks: PlayContentCallbacks[PlayCardState]


@plugs.initialize
def initialize():
    global player_ctrl
    player_ctrl = PlayerMPD()
    plugs.register(player_ctrl, name='ctrl')

    # Register with the player coordinator so cross-backend handoffs
    # (Spotify/podcast claiming the active slot) pause then stop MPD
    # cleanly before the new backend takes over.
    get_coordinator().register(
        name='mpd',
        pause_fn=lambda: player_ctrl.pause(1),
        stop_fn=player_ctrl.stop,
    )

    global play_card_callbacks
    play_card_callbacks = PlayContentCallbacks[PlayCardState]('play_card_callbacks', logger, context=player_ctrl.mpd_lock)

    # Update mpc library
    library_update = cfg.setndefault('playermpd', 'library', 'update_on_startup', value=True)
    if library_update:
        player_ctrl.update()

    # Check user rights on music library
    library_check_user_rights = cfg.setndefault('playermpd', 'library', 'check_user_rights', value=True)
    if library_check_user_rights is True:
        music_library_path = components.player.get_music_library_path()
        if music_library_path is not None:
            logger.info(f"Change user rights for {music_library_path}")
            misc.recursive_chmod(music_library_path, mode_files=0o666, mode_dirs=0o777)


@plugs.atexit
def atexit(**ignored_kwargs):
    global player_ctrl
    return player_ctrl.exit()
