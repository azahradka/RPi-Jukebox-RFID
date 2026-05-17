# -*- coding: utf-8 -*-
"""Test setup for ``components.jingle``.

Pre-stage a minimal ``jukebox.plugs`` stub so the ``@plugin.register``
/ ``@plugin.initialize`` / ``@plugin.finalize`` / ``@plugin.atexit``
decorators in ``components.jingle.__init__`` are no-ops at import
time, while still exposing the real ``_lock_module`` and
``drop_module_lock_for_blocking_call`` to the tests (no parallel
implementation).

Defensive against prior session state and careful to restore the
real ``jukebox.plugs`` after this module's tests so subsequent
test files (e.g. ``test/jukebox/test_atomic_io.py``) still see the
real ``jukebox`` package with its real ``utils``, ``cfghandler``,
etc.
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


def _load_real_plugs():
    plugs_path = _JUKEBOX_SRC / 'jukebox' / 'plugs.py'
    spec = importlib.util.spec_from_file_location(
        '_jukebox_plugs_real_jingle', plugs_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_plugs_mock():
    real_plugs = _load_real_plugs()
    plugs_mock = MagicMock()
    plugs_mock.register = lambda f=None, **kw: (
        (lambda fn: fn) if f is None else f)
    plugs_mock.initialize = lambda f: f
    plugs_mock.finalize = lambda f: f
    plugs_mock.atexit = lambda f: f
    plugs_mock.tag = lambda f: f
    plugs_mock._lock_module = real_plugs._lock_module
    plugs_mock.drop_module_lock_for_blocking_call = (
        real_plugs.drop_module_lock_for_blocking_call)
    plugs_mock.call_ignore_errors = real_plugs.call_ignore_errors
    return plugs_mock


@pytest.fixture(autouse=True)
def _install_jingle_plugs_mock():
    """Install the decorator-neutralising plugs mock for each jingle
    test, then restore the real ``sys.modules['jukebox']`` and the
    real ``jukebox.plugs`` attribute on teardown.
    """
    # Snapshot
    saved_modules = {
        k: sys.modules.get(k) for k in (
            'jukebox', 'jukebox.plugs', 'jukebox.cfghandler',
            'components.jingle')
    }
    real_jukebox = sys.modules.get('jukebox')
    real_jukebox_plugs_attr = getattr(real_jukebox, 'plugs', None) \
        if real_jukebox is not None else None

    plugs_mock = _build_plugs_mock()

    # Build a jukebox package stub that has __path__ so submodule
    # imports still resolve, plus our mocked plugs attribute.
    jukebox_stub = types.ModuleType('jukebox')
    jukebox_stub.__path__ = [str(_JUKEBOX_SRC / 'jukebox')]
    jukebox_stub.plugs = plugs_mock

    # Load a real cfghandler under the stub (its module functions
    # work standalone).
    cfg_path = _JUKEBOX_SRC / 'jukebox' / 'cfghandler.py'
    spec = importlib.util.spec_from_file_location('jukebox.cfghandler', cfg_path)
    cfg_mod = importlib.util.module_from_spec(spec)
    sys.modules['jukebox'] = jukebox_stub
    sys.modules['jukebox.plugs'] = plugs_mock
    sys.modules['jukebox.cfghandler'] = cfg_mod
    spec.loader.exec_module(cfg_mod)
    jukebox_stub.cfghandler = cfg_mod

    # Force re-import of components.jingle so decorators run against
    # the mock we just installed.
    sys.modules.pop('components.jingle', None)

    yield

    # Restore
    for k, v in saved_modules.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v
    if real_jukebox is not None and real_jukebox_plugs_attr is not None:
        setattr(real_jukebox, 'plugs', real_jukebox_plugs_attr)
