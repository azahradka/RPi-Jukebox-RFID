# -*- coding: utf-8 -*-
"""Test setup for ``components.jingle``.

Pre-stage a minimal ``jukebox.plugs`` stub so the ``@plugin.register``
/ ``@plugin.initialize`` / ``@plugin.finalize`` / ``@plugin.atexit``
decorators in ``components.jingle.__init__`` are no-ops at import
time, while still exposing the real ``_lock_module`` and
``drop_module_lock_for_blocking_call`` to the tests (no parallel
implementation).

The conftest is defensive against prior session state: earlier
playerpodcast tests fully replace ``sys.modules['jukebox']`` with a
mock, so we must reload the real ``jukebox.plugs`` from its source
file rather than relying on ``import jukebox.plugs``.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


def _load_real_plugs():
    """Load the real ``jukebox/plugs.py`` regardless of session state.

    Previous tests may have replaced ``sys.modules['jukebox']`` with a
    MagicMock; ``import jukebox.plugs`` would then return mock objects.
    We load directly from the file via ``importlib.util`` to guarantee
    we get the production ``_lock_module`` and
    ``drop_module_lock_for_blocking_call``.
    """
    plugs_path = _JUKEBOX_SRC / 'jukebox' / 'plugs.py'
    spec = importlib.util.spec_from_file_location(
        '_jukebox_plugs_real', plugs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_real_plugs = _load_real_plugs()

# Build a decorator-neutralising mock that re-exports the real lock
# helpers, so the behavioural tests touch production code.
_plugs_mock = MagicMock()
_plugs_mock.register = lambda f=None, **kw: (lambda fn: fn) if f is None else f
_plugs_mock.initialize = lambda f: f
_plugs_mock.finalize = lambda f: f
_plugs_mock.atexit = lambda f: f
_plugs_mock.tag = lambda f: f
_plugs_mock._lock_module = _real_plugs._lock_module
_plugs_mock.drop_module_lock_for_blocking_call = (
    _real_plugs.drop_module_lock_for_blocking_call
)
_plugs_mock.call_ignore_errors = _real_plugs.call_ignore_errors


# Build (or repair) a minimal ``jukebox`` package mock that exposes
# our plugs mock + a real-ish cfghandler. We must always re-install
# these to overwrite any leftover state from prior conftests.
def _install_test_modules():
    # Real cfghandler so cfg.getn / cfg.config_dict work.
    cfg_path = _JUKEBOX_SRC / 'jukebox' / 'cfghandler.py'
    spec = importlib.util.spec_from_file_location(
        'jukebox.cfghandler', cfg_path)
    cfg_mod = importlib.util.module_from_spec(spec)
    sys.modules['jukebox.cfghandler'] = cfg_mod
    spec.loader.exec_module(cfg_mod)

    # Use a real ``types.ModuleType`` with a proper ``__path__`` so
    # subsequent ``import jukebox.<sub>`` calls (e.g. by other tests
    # running after this one) can still resolve real submodules.
    jukebox_pkg = types.ModuleType('jukebox')
    jukebox_pkg.__path__ = [str(_JUKEBOX_SRC / 'jukebox')]
    jukebox_pkg.plugs = _plugs_mock
    jukebox_pkg.cfghandler = cfg_mod
    sys.modules['jukebox'] = jukebox_pkg
    sys.modules['jukebox.plugs'] = _plugs_mock

    # Force re-import of components.jingle so decorators run against
    # the mock we just installed.
    sys.modules.pop('components.jingle', None)


_install_test_modules()
