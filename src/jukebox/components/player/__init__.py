import os
import re
import logging
import threading
import jukebox.cfghandler
from typing import Optional


logger = logging.getLogger('jb.player')
cfg = jukebox.cfghandler.get_handler('jukebox')


def _get_music_library_path(conf_file):
    """Parse the music directory from the mpd.conf file"""
    pattern = re.compile(r'^\s*music_directory\s*"(.*)"', re.I)
    directory = None
    with open(conf_file, 'r') as f:
        for line in f:
            res = pattern.match(line)
            if res:
                directory = res.group(1)
                break
        else:
            logger.error(f"Could not find music library path in {conf_file}")
    logger.debug(f"MPD music lib path = {directory}; from {conf_file}")
    return directory


class MusicLibPath:
    """Extract the music directory from the mpd.conf file"""
    def __init__(self):
        self._music_library_path = None
        mpd_conf_file = cfg.setndefault('playermpd', 'mpd_conf', value='~/.config/mpd/mpd.conf')
        try:
            self._music_library_path = _get_music_library_path(os.path.expanduser(mpd_conf_file))
        except Exception as e:
            logger.error(f"Could not determine music library directory from '{mpd_conf_file}'")
            logger.error(f"Reason: {e.__class__.__name__}: {e}")

    @property
    def music_library_path(self):
        return self._music_library_path


# ---------------------------------------------------------------------------


_MUSIC_LIBRARY_PATH: Optional[MusicLibPath] = None


def get_music_library_path():
    """Get the music library path"""
    global _MUSIC_LIBRARY_PATH
    if _MUSIC_LIBRARY_PATH is None:
        _MUSIC_LIBRARY_PATH = MusicLibPath()
    return _MUSIC_LIBRARY_PATH.music_library_path


# ---------------------------------------------------------------------------
# Active player tracking
# ---------------------------------------------------------------------------
# Only the active player should publish to the 'playerstatus' topic.
# Valid values: 'mpd', 'spotify', None
#
# Writers are racy (MPD poll thread, Spotify poll thread, RPC threads driving
# play_card). The lock makes reads/writes atomic, and gives callers a
# compare-and-swap option to avoid clobbering a hand-off that already won.
_active_player: Optional[str] = 'mpd'
_active_player_lock = threading.Lock()
_ACTIVE_PLAYER_UNSET = object()  # sentinel for "no expected_current supplied"


def get_active_player() -> Optional[str]:
    with _active_player_lock:
        return _active_player


def set_active_player(player_name: Optional[str], expected_current=_ACTIVE_PLAYER_UNSET) -> bool:
    """Set the active player, optionally as a compare-and-swap.

    If ``expected_current`` is provided, the swap only succeeds when the
    current active player equals that value. Returns ``True`` on success,
    ``False`` if the CAS check failed. With no ``expected_current``, the
    swap is unconditional and always returns ``True``.
    """
    global _active_player
    with _active_player_lock:
        if expected_current is not _ACTIVE_PLAYER_UNSET and _active_player != expected_current:
            logger.debug(
                f"set_active_player CAS rejected: expected={expected_current!r}, "
                f"actual={_active_player!r}, requested={player_name!r}"
            )
            return False
        _active_player = player_name
    logger.info(f"Active player set to: {player_name}")
    return True
