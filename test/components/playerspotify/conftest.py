# -*- coding: utf-8 -*-
"""
Shared test configuration for Spotify player tests.

Mocks the jukebox plugin framework before any module imports to allow
testing individual components in isolation without the full plugin system.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add jukebox source to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'jukebox'))

# Mock jukebox framework modules BEFORE any playerspotify imports.
# This prevents the @plugs.initialize, @plugs.register, @plugs.atexit decorators
# from trying to register with a plugin system that isn't running.
_mock_plugs = MagicMock()
_mock_plugs.initialize = lambda f: f
_mock_plugs.register = lambda f=None, **kwargs: (lambda fn: fn) if f is None else f
_mock_plugs.atexit = lambda f: f
_mock_plugs.tag = lambda f: f

_mock_cfghandler = MagicMock()
_mock_publishing = MagicMock()

# Real ``jukebox.utils.atomic_io`` — Phase 1 fix #2. Spotify _save_status
# now delegates to it; the tests want the genuine atomic writer.
_PKG_ROOT = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import importlib.util as _ilutil  # noqa: E402
_atomic_spec = _ilutil.spec_from_file_location(
    'jukebox.utils.atomic_io',
    _PKG_ROOT / 'jukebox' / 'utils' / 'atomic_io.py',
)
_atomic_mod = _ilutil.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic_mod)

_mock_utils = MagicMock()
_mock_utils.atomic_io = _atomic_mod

# Mock the parent 'jukebox' package too so attribute access works correctly
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
