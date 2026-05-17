# -*- coding: utf-8 -*-
"""Shared test configuration for playerpodcast tests.

Two responsibilities, both inherited from prior phases:

1. Pre-mock the jukebox plugin framework BEFORE any podcast module is
   imported, so ``@plugs.register`` / ``@plugs.initialize`` decorators
   in ``components.playerpodcast.__init__`` are no-ops. This is the
   pattern Phase 0b established; tests that import ``PlayerPodcast``
   continue to rely on it.

2. Provide ``playback_state_module`` and ``feed_manager_module``
   fixtures that load the sub-modules in isolation, via the Phase 3a
   importlib-stub pattern. Tests for the pure-seam state machine
   should use these so they exercise the real module without booting
   the full ``__init__`` decorator chain.

Both patterns coexist: pattern 1 is sys.modules-shadow; pattern 2
loads specific files into a fresh ``components.playerpodcast`` stub
when the tests opt in. The two do not interfere because pattern 2
re-uses sys.modules entries pattern 1 has already installed.
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
# Pattern 2: per-submodule importlib loaders (Phase 3a style)
# ---------------------------------------------------------------------------
_PODCAST_DIR = _JUKEBOX_SRC / 'components' / 'playerpodcast'


def _load_submodule(qualname: str, file_path: Path):
    """Load a submodule file as ``qualname`` without executing the parent
    package's ``__init__.py``.

    Installs a minimal stub ``components.playerpodcast`` parent in
    ``sys.modules`` so relative imports resolve, but does not run the
    real ``__init__`` (which would trigger plugin registration).
    """
    pkg_name = qualname.rsplit('.', 1)[0]
    if pkg_name not in sys.modules or not hasattr(sys.modules[pkg_name], '__path__'):
        parent_qual = pkg_name.rsplit('.', 1)[0]
        if parent_qual and parent_qual not in sys.modules:
            sys.modules[parent_qual] = types.ModuleType(parent_qual)
        stub = types.ModuleType(pkg_name)
        stub.__path__ = [str(file_path.parent)]
        sys.modules[pkg_name] = stub

    if qualname in sys.modules:
        return sys.modules[qualname]

    spec = importlib.util.spec_from_file_location(qualname, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[qualname] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def playback_state_module():
    """Provide the ``components.playerpodcast.playback_state`` module.

    Loads the pure-seam state machine extracted in Phase 3b without
    triggering ``components.playerpodcast.__init__``'s decorator
    chain. Use this fixture for tests of ``decide_second_swipe`` /
    ``build_queue_plan`` directly.
    """
    return _load_submodule(
        'components.playerpodcast.playback_state',
        _PODCAST_DIR / 'playback_state.py',
    )


@pytest.fixture
def feed_manager_module():
    """Provide the ``components.playerpodcast.feed_manager`` module."""
    return _load_submodule(
        'components.playerpodcast.feed_manager',
        _PODCAST_DIR / 'feed_manager.py',
    )
