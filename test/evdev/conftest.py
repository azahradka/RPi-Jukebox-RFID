# -*- coding: utf-8 -*-
"""
Local conftest for evdev tests.

Earlier subdirectory conftests (``test/components/playerpodcast`` and
``test/components/playerspotify``) install ``MagicMock`` objects into
``sys.modules['jukebox']`` to short-circuit the plugin framework for the
duration of their tests. Once those modules are collected, the pollution
persists for the rest of the pytest session, which breaks any subsequent
test that needs the *real* ``jukebox`` package (e.g. ``import jukebox.utils``
fails with "``jukebox`` is not a package").

Pytest collects directories alphabetically, so ``test/components/`` runs
before ``test/evdev/``. This conftest restores the real package by purging
any stale ``jukebox*`` entries from ``sys.modules`` and re-importing the
genuine package from ``src/jukebox``.
"""

import importlib
import sys
from pathlib import Path

_JUKEBOX_SRC = Path(__file__).parent.parent.parent / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))

# Drop any cached (potentially mocked) jukebox entries so the real package
# is re-imported below.
for _name in [m for m in list(sys.modules) if m == 'jukebox' or m.startswith('jukebox.')]:
    del sys.modules[_name]

# Re-import the real package eagerly so subsequent ``import jukebox.<sub>``
# statements resolve against the on-disk package, not a stale mock.
importlib.import_module('jukebox')
importlib.import_module('jukebox.plugs')
