# -*- coding: utf-8 -*-
"""Shared test configuration for playerpodcast tests.

After Item 3 (plug-time-coupling refactor) only Pattern 1 remains:
the conftest pre-mocks ``jukebox.cfghandler`` / ``jukebox.publishing``
so tests that *instantiate* ``PlayerPodcast`` don't need a running
config handler. Tests that only need leaf modules
(``playback_state``, ``feed_manager``) can ``import`` them directly
via the fixtures below — no importlib-stub gymnastics needed because
``components.playerpodcast.__init__`` is now import-safe.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


# ---------------------------------------------------------------------------
# Pattern 1: pre-mock the jukebox plugin framework
# ---------------------------------------------------------------------------
# This prevents the @plugs.initialize, @plugs.register, @plugs.atexit decorators
# from trying to register with a plugin system that isn't running.
_mock_plugs = MagicMock()
_mock_plugs.initialize = lambda f: f
_mock_plugs.register = lambda f=None, **kwargs: (lambda fn: fn) if f is None else f
_mock_plugs.atexit = lambda f: f
_mock_plugs.tag = lambda f: f

_mock_cfghandler = MagicMock()
_mock_publishing = MagicMock()

# Real ``jukebox.utils.atomic_io`` so podcast state-manager writes use the
# genuine helper under test. Imported via importlib so it's installed under
# sys.modules['jukebox.utils.atomic_io'] before we shadow 'jukebox'.
_atomic_spec = importlib.util.spec_from_file_location(
    'jukebox.utils.atomic_io',
    _JUKEBOX_SRC / 'jukebox' / 'utils' / 'atomic_io.py',
)
_atomic_mod = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic_mod)

_mock_utils = MagicMock()
_mock_utils.atomic_io = _atomic_mod

# Mock the parent 'jukebox' package so attribute access works correctly
# when __init__.py does: import jukebox.cfghandler; cfg = jukebox.cfghandler.get_handler(...)
_mock_jukebox = MagicMock()
_mock_jukebox.plugs = _mock_plugs
_mock_jukebox.cfghandler = _mock_cfghandler
_mock_jukebox.publishing = _mock_publishing
_mock_jukebox.utils = _mock_utils

sys.modules['jukebox'] = _mock_jukebox
sys.modules['jukebox.plugs'] = _mock_plugs
sys.modules['jukebox.cfghandler'] = _mock_cfghandler
sys.modules['jukebox.publishing'] = _mock_publishing
sys.modules['jukebox.utils'] = _mock_utils
sys.modules['jukebox.utils.atomic_io'] = _atomic_mod


# ---------------------------------------------------------------------------
# Stub ``components.player`` parent package (Phase 3b).
# ---------------------------------------------------------------------------
# ``components.playerpodcast.__init__`` does
#     from components.player.coordinator import get_coordinator
# Importing the real ``components.player.__init__.py`` triggers
# ``MusicLibPath`` which reads mpd.conf at module-import time - fails
# under tests. We install a minimal package stub for
# ``components.player`` with a proper ``__path__`` so the real
# ``components.player.coordinator`` can be imported normally.
_PLAYER_PKG_NAME = 'components.player'
if _PLAYER_PKG_NAME not in sys.modules or not hasattr(
    sys.modules[_PLAYER_PKG_NAME], '__path__',
):
    _player_pkg = types.ModuleType(_PLAYER_PKG_NAME)
    _player_pkg.__path__ = [str(_JUKEBOX_SRC / 'components' / 'player')]
    _player_pkg.get_music_library_path = lambda: None
    sys.modules[_PLAYER_PKG_NAME] = _player_pkg


# ---------------------------------------------------------------------------
# Pattern 2: per-submodule fixtures
# ---------------------------------------------------------------------------
# Pre-Item 3 these used ``importlib.util.spec_from_file_location`` plus a
# stub parent package because ``components.playerpodcast.__init__`` would
# otherwise run ``@plugs.initialize`` / ``@plugs.atexit`` decorators at
# import time. After Item 3 the parent package is import-safe (its plugs
# registrations live inside ``init_plugin()``), so a plain
# ``import components.playerpodcast.playback_state`` is enough.


@pytest.fixture
def playback_state_module():
    """Provide the ``components.playerpodcast.playback_state`` module.

    Pure-seam state machine extracted in Phase 3b. Use this fixture
    for tests of ``decide_second_swipe`` / ``build_queue_plan`` so
    the test exercises real production code without parallel
    implementation.
    """
    import components.playerpodcast.playback_state as pb
    return pb


@pytest.fixture
def feed_manager_module():
    """Provide the ``components.playerpodcast.feed_manager`` module."""
    import components.playerpodcast.feed_manager as fm
    return fm
