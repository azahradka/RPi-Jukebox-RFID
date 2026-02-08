# -*- coding: utf-8 -*-
"""
Shared test configuration for podcast player tests.

Mocks the jukebox plugin framework before any module imports to allow
testing individual components in isolation without the full plugin system.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add jukebox source to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src' / 'jukebox'))

# Mock jukebox framework modules BEFORE any playerpodcast imports.
# This prevents the @plugs.initialize, @plugs.register, @plugs.atexit decorators
# from trying to register with a plugin system that isn't running.
_mock_plugs = MagicMock()
_mock_plugs.initialize = lambda f: f
_mock_plugs.register = lambda f=None, **kwargs: (lambda fn: fn) if f is None else f
_mock_plugs.atexit = lambda f: f
_mock_plugs.tag = lambda f: f

_mock_cfghandler = MagicMock()
_mock_publishing = MagicMock()

# Mock the parent 'jukebox' package too so attribute access works correctly
# when __init__.py does: import jukebox.cfghandler; cfg = jukebox.cfghandler.get_handler(...)
_mock_jukebox = MagicMock()
_mock_jukebox.plugs = _mock_plugs
_mock_jukebox.cfghandler = _mock_cfghandler
_mock_jukebox.publishing = _mock_publishing

sys.modules['jukebox'] = _mock_jukebox
sys.modules['jukebox.plugs'] = _mock_plugs
sys.modules['jukebox.cfghandler'] = _mock_cfghandler
sys.modules['jukebox.publishing'] = _mock_publishing
