# -*- coding: utf-8 -*-
"""
Local conftest for gpioz tests.

See ``test/evdev/conftest.py`` for the full rationale. Briefly: earlier
component-test conftests install MagicMock stand-ins for the ``jukebox``
package in ``sys.modules``; that pollution persists across the rest of the
session and breaks any test that imports the real package. This conftest
restores the genuine package before gpioz tests are collected.
"""

import importlib
import sys
from pathlib import Path

_JUKEBOX_SRC = Path(__file__).parent.parent.parent / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))

for _name in [m for m in list(sys.modules) if m == 'jukebox' or m.startswith('jukebox.')]:
    del sys.modules[_name]

importlib.import_module('jukebox')
importlib.import_module('jukebox.plugs')
