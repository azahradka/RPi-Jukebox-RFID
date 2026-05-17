# -*- coding: utf-8 -*-
"""Tests for ``components.jingle.play`` lock-release discipline.

Phase 6 / Phase 3b FU#1: previously ``jingle.play`` held
``jukebox.plugs._lock_module`` across the blocking WAV playback,
starving every other RPC for the playback duration (10-60 s for
podcast waiting-jingle). The fix wraps the blocking call in
``plugs.drop_module_lock_for_blocking_call()``.

This test exercises the real ``jingle.play`` function with a fake
factory whose ``play()`` checks the lock state mid-blocking.
Reversion check: remove the ``with drop_module_lock_for_blocking_call()``
wrapper in ``components.jingle.play`` and this test fails.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[3] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


def _reinstall_jingle_test_modules():
    """Re-install the decorator-neutralising plugs mock + real-cfghandler
    layer that ``conftest.py`` does at import time.

    Earlier tests (e.g. playerpodcast) replace ``sys.modules['jukebox']``
    with their own MagicMock; this fixture must rebuild the layer
    every time so subsequent ``import components.jingle`` runs against
    OUR mock (which keeps the real lock object).
    """
    plugs_path = _JUKEBOX_SRC / 'jukebox' / 'plugs.py'
    spec = importlib.util.spec_from_file_location(
        '_jukebox_plugs_real', plugs_path)
    real_plugs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(real_plugs)

    plugs_mock = MagicMock()
    plugs_mock.register = lambda f=None, **kw: (lambda fn: fn) if f is None else f
    plugs_mock.initialize = lambda f: f
    plugs_mock.finalize = lambda f: f
    plugs_mock.atexit = lambda f: f
    plugs_mock.tag = lambda f: f
    plugs_mock._lock_module = real_plugs._lock_module
    plugs_mock.drop_module_lock_for_blocking_call = (
        real_plugs.drop_module_lock_for_blocking_call
    )
    plugs_mock.call_ignore_errors = real_plugs.call_ignore_errors

    cfg_path = _JUKEBOX_SRC / 'jukebox' / 'cfghandler.py'
    spec = importlib.util.spec_from_file_location(
        'jukebox.cfghandler', cfg_path)
    cfg_mod = importlib.util.module_from_spec(spec)
    sys.modules['jukebox.cfghandler'] = cfg_mod
    spec.loader.exec_module(cfg_mod)

    jukebox_pkg = types.ModuleType('jukebox')
    jukebox_pkg.__path__ = [str(_JUKEBOX_SRC / 'jukebox')]
    jukebox_pkg.plugs = plugs_mock
    jukebox_pkg.cfghandler = cfg_mod
    sys.modules['jukebox'] = jukebox_pkg
    sys.modules['jukebox.plugs'] = plugs_mock
    sys.modules.pop('components.jingle', None)
    return plugs_mock


@pytest.fixture
def jingle_module():
    """Load ``components.jingle`` against the decorator-neutralising
    plugs mock installed by ``conftest.py``.

    The mock exposes the real ``_lock_module`` and
    ``drop_module_lock_for_blocking_call``, so the behavioural tests
    still exercise the real lock object — not a parallel
    implementation.
    """
    # Re-install in case a prior test module shadowed sys.modules.
    _reinstall_jingle_test_modules()

    import jukebox.cfghandler as cfghandler
    cfg = cfghandler.get_handler('jukebox')
    cfg.config_dict({'jingle': {}})

    # Force re-import so decorators run against the mocked plugs.
    sys.modules.pop('components.jingle', None)
    import components.jingle as jingle_mod
    yield jingle_mod


def test_jingle_play_releases_plugs_lock_during_blocking_call(jingle_module):
    """Another thread can acquire ``plugs._lock_module`` while the
    blocking WAV play is in progress.

    Setup mirrors how ``plugs.call`` invokes ``jingle.play``: the
    caller holds the plugs module lock; ``play()`` must drop it
    around the blocking section.

    Reversion check: remove ``with plugin.drop_module_lock_for_blocking_call():``
    from ``components.jingle.play`` and this test will hang (the other
    thread never gets the lock within timeout).
    """
    import jukebox.plugs as plugs

    other_thread_acquired = threading.Event()
    blocking_started = threading.Event()
    can_finish = threading.Event()

    class FakeService:
        def play(self, filename):
            # Signal we're inside the "blocking" section and wait
            # for the other thread to confirm it could acquire.
            blocking_started.set()
            # Wait up to 2s; if the test passed, we'll be released
            # immediately.
            can_finish.wait(timeout=2.0)

    class FakeFactory:
        def auto(self, filename):
            return FakeService()

    jingle_module.factory = FakeFactory()

    def other_thread():
        # Wait for play() to enter the blocking section
        blocking_started.wait(timeout=2.0)
        if plugs._lock_module.acquire(timeout=1.5):
            other_thread_acquired.set()
            plugs._lock_module.release()
        # Let the blocking section finish
        can_finish.set()

    t = threading.Thread(target=other_thread, daemon=True)

    # Simulate plugs.call: hold the module lock around the invocation.
    plugs._lock_module.acquire()
    try:
        t.start()
        # Patch volume calls to no-ops so we don't need volume plugin
        with patch('components.jingle.plugin.call_ignore_errors',
                   return_value=None):
            jingle_module.play('fake.wav')
        t.join(timeout=3.0)
    finally:
        plugs._lock_module.release()

    assert other_thread_acquired.is_set(), (
        "Other thread could not acquire plugs._lock_module while "
        "jingle.play was in its blocking section. The lock-release "
        "around the blocking call was reverted."
    )


def test_jingle_play_still_holds_lock_for_volume_calls(jingle_module):
    """The volume get/set calls in ``jingle.play`` must run while the
    plugs lock is held (so concurrent set_volume requests serialise).

    We assert this indirectly: ``plugin.call_ignore_errors`` is invoked
    *outside* the drop block (before and after the play). We patch it
    and verify the calls happened.
    """
    import jukebox.plugs as plugs

    class FakeService:
        def play(self, filename):
            pass

    class FakeFactory:
        def auto(self, filename):
            return FakeService()

    jingle_module.factory = FakeFactory()

    # Configure jingle volume so the volume-changing branch runs.
    import jukebox.cfghandler as cfghandler
    cfg = cfghandler.get_handler('jukebox')
    cfg.config_dict({'jingle': {'volume': 50}})

    plugs._lock_module.acquire()
    try:
        with patch('components.jingle.plugin.call_ignore_errors',
                   return_value=42) as mock_call:
            jingle_module.play('fake.wav')
            # Expect: get_volume + set_volume(50) + set_volume(42)
            assert mock_call.call_count >= 3
            calls = [c.args[:3] for c in mock_call.call_args_list]
            assert ('volume', 'ctrl', 'get_volume') in calls
            assert ('volume', 'ctrl', 'set_volume') in calls
    finally:
        plugs._lock_module.release()

    # Reset cfg for downstream tests
    cfg.config_dict({'jingle': {}})
