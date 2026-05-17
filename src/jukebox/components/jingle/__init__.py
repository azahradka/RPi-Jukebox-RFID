# RPi-Jukebox-RFID Version 3
# Copyright (c) See file LICENSE in project root folder
"""
Jingle Playback Factory for extensible run-time support of various file types
"""

import os.path
import signal
import logging
import jukebox.plugs as plugin
import jukebox.cfghandler

logger = logging.getLogger('jb.jingle')
cfg = jukebox.cfghandler.get_handler('jukebox')


class JingleFactory:
    """Jingle Factory"""

    def __init__(self):
        self._builders = {}

    def register(self, key, builder):
        logger.debug(f"Register '{key}' in {self.__class__}.")
        self._builders[key] = builder

    def get(self, key):
        return self._builders.get(key)()

    def list(self):
        """List the available volume services"""
        return self._builders.keys()

    def auto(self, filename):
        # Check the config if the user has a specific config
        # else use auto resolver function
        key = cfg['jingle'].get('service', 'auto')
        if key == 'auto':
            # This is a very simple resolving function based on file extension
            # This does no allow for duplicate entries etc...
            key = os.path.splitext(filename)[1][1:]
        logger.debug(f"Auto: '{key}' from {filename}.")
        return self.get(key)


factory: JingleFactory


def initialize():
    global factory
    factory = JingleFactory()


def play(filename):
    """Play the jingle using the configured jingle service

    Phase 6 / Phase 3b FU#1: the volume get/set RPCs are kept inside
    the plugs lock (they're quick, and serialising them with concurrent
    set_volume calls is the whole point of the lock). The blocking
    WAV playback (10-60 s for some jingles) is wrapped in
    :func:`jukebox.plugs.drop_module_lock_for_blocking_call` so other
    RPC traffic — status publishers, RFID swipe dispatch, Web UI calls —
    is not starved. Previously, this method held the plugs RLock across
    the full playback, which led ``playerpodcast`` to ship a direct-ALSA
    workaround (``_play_wav_direct``). With the lock-release here, that
    workaround is no longer required to avoid RPC starvation, though it
    remains in podcast for separate latency reasons (see its docstring).

    > [!NOTE]
    > This still runs in a separate thread and the volume-restore race
    > the original docstring described is not new — another thread can
    > change volume between our jingle-volume set and our restore. The
    > pre-Phase-6 docstring's mitigations still apply.
    """
    global factory
    jingle_volume = cfg.getn('jingle', 'volume', default=None)
    active_volume = None
    if jingle_volume is not None:
        active_volume = plugin.call_ignore_errors('volume', 'ctrl', 'get_volume')
        plugin.call_ignore_errors('volume', 'ctrl', 'set_volume', args=[jingle_volume])
    # Drop the plugs module lock around the blocking WAV playback.
    # See _DropLockForBlockingCall docstring for rationale.
    with plugin.drop_module_lock_for_blocking_call():
        factory.auto(filename).play(filename)
    if jingle_volume is not None:
        plugin.call_ignore_errors('volume', 'ctrl', 'set_volume', args=[active_volume])


def play_startup():
    """Play the startup sound (using jingle.play)"""
    play(cfg['jingle']['startup_sound'])


def play_shutdown():
    """Play the shutdown sound (using jingle.play)"""
    play(cfg['jingle']['shutdown_sound'])


def finalize():
    if 'startup_sound' in cfg['jingle']:
        plugin.call_ignore_errors('jingle', 'play_startup', as_thread=True, thread_name='StartJingle')
    else:
        logger.debug("No startup sound in config file")


def atexit(signal_id: int, **ignored_kwargs):
    # Only play the shutdown sound when terminated with a proper command. Not on Ctrl-C (faster exit for developers :-)
    if signal_id == signal.SIGTERM:
        if 'shutdown_sound' in cfg['jingle']:
            # Never play the shutdown sound as thread!
            # It causes a race condition with the plugin volume, which shuts down faster
            # But we need to have the plugin volume to reset the volume level after the sound was played
            plugin.call_ignore_errors('jingle', 'play_shutdown', as_thread=False)
        else:
            logger.debug("No shutdown sound in config file")


def init_plugin():
    """Register jingle callables and lifecycle hooks (Item 3)."""
    plugin.initialize(initialize)
    plugin.register(play)
    plugin.register(play_startup)
    plugin.register(play_shutdown)
    plugin.finalize(finalize)
    plugin.atexit(atexit)
