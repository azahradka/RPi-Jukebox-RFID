# -*- coding: utf-8 -*-
"""Tests for ``JukeBox._summary_*`` startup-banner helpers.

Background
----------
Phase 7 introduced a startup summary block in ``daemon.py`` that logs
four facts at INFO so journalctl users can tell at a glance which
player, plugins, RFID readers and audio sink the box came up with.
Each fact is computed by a small ``_summary_*`` helper that wraps its
lookup in ``try/except Exception`` and falls back to
``"<unavailable> ({exc})"`` so a partially-failed startup still
prints something useful.

Two regressions / follow-ups are exercised here:

1. **Regression B (RPi-surfaced 2026-05-17)**: ``_summary_audio_sink``
   calls ``volume.ctrl.get_active`` but no such method existed —
   ``call_ignore_errors`` returned ``None`` and the summary fell
   through to ``"<unknown>"``. We now add the method and the helper
   must surface its return value. Reversion check: rename / remove
   ``get_active`` and the assertion that the helper returns the fake
   sink alias fails.

2. **Item 7 — WARN logging on helper failure (project_post_refactor_followups.md
   #7)**: when the underlying call raises, the helper should emit a
   ``logger.warning`` *in addition to* returning the fallback string,
   so a silently-degraded startup leaves a breadcrumb in
   ``errors.log``. Reversion check: drop the warning and the warning
   assertion fails.

Both helpers are exercised against the real ``JukeBox`` class instance
(constructed without running ``__init__`` so we don't have to fake
the entire config-load + signal-handler dance).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_JUKEBOX_SRC = _REPO_ROOT / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


def _stub_zmq_if_missing():
    """Stub ``zmq`` + the publishing IOLoop import path so we can import
    ``jukebox.daemon`` on CI runners that don't compile PyZMQ.

    The CI workflow comments out ``pyzmq`` in ``requirements.txt`` —
    the production install script compiles it from source on the RPi
    for websocket support, but CI doesn't have it available. The
    startup-summary helpers don't actually USE zmq at runtime (they
    go through the ``plugin.call_ignore_errors`` indirection), so
    stubbing the module is safe for this test file.
    """
    import importlib as _importlib
    import types as _types
    try:
        _importlib.import_module('zmq')
        return
    except ImportError:
        pass
    fake_zmq = _types.ModuleType('zmq')
    fake_zmq.__version__ = '0.0.0-stub'
    # Anything referenced from ``jukebox.publishing.server`` at import
    # time. The publisher class itself isn't instantiated in these
    # tests so we don't have to fake behaviour.
    for attr in ('PUB', 'REP', 'REQ', 'PUSH', 'PULL', 'LINGER',
                 'SNDHWM', 'RCVHWM', 'SUBSCRIBE', 'SUB'):
        setattr(fake_zmq, attr, 0)
    fake_zmq.Context = lambda *a, **kw: None  # type: ignore[assignment]
    fake_zmq.Socket = type('Socket', (), {})

    fake_zmq_error = _types.ModuleType('zmq.error')
    fake_zmq_error.ZMQError = type('ZMQError', (Exception,), {})
    fake_zmq.error = fake_zmq_error

    fake_evloop = _types.ModuleType('zmq.eventloop')
    fake_evloop.__path__ = []  # mark as package
    fake_ioloop = _types.ModuleType('zmq.eventloop.ioloop')
    fake_ioloop.IOLoop = type('IOLoop', (), {})
    fake_zmqstream = _types.ModuleType('zmq.eventloop.zmqstream')
    fake_zmqstream.ZMQStream = type('ZMQStream', (), {})

    # Constants referenced beyond the basic socket types — fill in
    # with sentinel zeros so ``import jukebox.publishing.server``
    # succeeds at module load time. We never actually call into
    # zmq in this test file.
    for attr in ('XPUB', 'XPUB_VERBOSE', 'DRAFT_API'):
        setattr(fake_zmq, attr, 0)
    fake_zmq.pyzmq_version = lambda: '0.0.0-stub'
    fake_zmq.zmq_version = lambda: '0.0.0-stub'

    sys.modules['zmq'] = fake_zmq
    sys.modules['zmq.error'] = fake_zmq_error
    sys.modules['zmq.eventloop'] = fake_evloop
    sys.modules['zmq.eventloop.ioloop'] = fake_ioloop
    sys.modules['zmq.eventloop.zmqstream'] = fake_zmqstream


_stub_zmq_if_missing()

# Import daemon module directly. Its top-level imports pull in plugs,
# publishing, etc. — those are all importable without booting plugins
# once zmq is stubbed (if needed) above.
import jukebox.daemon as daemon_mod  # noqa: E402


def _bare_jukebox():
    """Return a ``JukeBox`` instance with no ``__init__`` side effects.

    ``JukeBox.__init__`` registers signal handlers, opens YAML files
    and writes log lines. We don't need any of that for testing the
    pure-ish ``_summary_*`` helpers; ``__new__`` gives us a bound-method
    self.
    """
    return daemon_mod.JukeBox.__new__(daemon_mod.JukeBox)


# ----------------------------------------------------------------------
# Regression B: _summary_audio_sink resolves volume.ctrl.get_active
# ----------------------------------------------------------------------


def test_summary_audio_sink_uses_volume_ctrl_get_active(monkeypatch):
    """The helper must surface the value returned by ``volume.ctrl.get_active``.

    Reversion check: rename the method back to anything else, the fake
    will not be invoked, the helper falls back to ``<unknown>`` and
    this assert fails.
    """
    calls = []

    def fake_call_ignore_errors(package, plugin, method=None, *args, **kwargs):
        calls.append((package, plugin, method))
        if (package, plugin, method) == ('volume', 'ctrl', 'get_active'):
            return 'speaker'
        return None

    monkeypatch.setattr(daemon_mod.plugin, 'call_ignore_errors', fake_call_ignore_errors)

    jb = _bare_jukebox()
    result = jb._summary_audio_sink()

    assert result == 'speaker', (
        f"expected the helper to surface the fake sink alias 'speaker', got "
        f"{result!r}. Did volume.ctrl.get_active disappear from the helper?"
    )
    assert ('volume', 'ctrl', 'get_active') in calls, (
        "helper did not invoke volume.ctrl.get_active — regression B "
        "would have re-surfaced. Calls observed: " + repr(calls)
    )


def test_summary_audio_sink_falls_back_when_method_returns_none(monkeypatch):
    """If the method is registered but returns ``None``/empty, the
    helper still emits a useful string."""

    monkeypatch.setattr(
        daemon_mod.plugin, 'call_ignore_errors',
        lambda *a, **kw: None,
    )

    jb = _bare_jukebox()
    assert jb._summary_audio_sink() == '<unknown>'


# ----------------------------------------------------------------------
# Item 7: WARN logging on summary-helper exceptions
# ----------------------------------------------------------------------


def _boom(*args, **kwargs):
    raise RuntimeError('boom')


@pytest.mark.parametrize(
    "helper_name,patch_target",
    [
        ('_summary_audio_sink', 'call_ignore_errors'),
        ('_summary_loaded_plugins', 'call_ignore_errors'),
        # _summary_rfid_readers reaches into cfghandler.get_handler; we
        # patch get_handler to raise so the except branch fires.
        ('_summary_rfid_readers', None),
    ],
)
def test_summary_helper_logs_warning_on_exception(monkeypatch, caplog, helper_name, patch_target):
    """When a summary helper hits an exception, it must:

    1. Return a ``<unavailable> (...)`` fallback string (existing
       Phase 7 behaviour).
    2. Log a warning with the exception detail so the failure is
       visible in ``errors.log`` (Item 7 follow-up).

    Reversion check: removing the ``logger.warning`` line from the
    helper makes ``warning_logged`` False and the assert fails.
    """
    jb = _bare_jukebox()

    if helper_name == '_summary_rfid_readers':
        # Patch the cfghandler used inside the helper to raise.
        import jukebox.cfghandler as cfghandler_mod
        monkeypatch.setattr(cfghandler_mod, 'get_handler', _boom)
    else:
        monkeypatch.setattr(daemon_mod.plugin, patch_target, _boom)

    caplog.set_level(logging.WARNING, logger=daemon_mod.logger.name)
    result = getattr(jb, helper_name)()

    assert result.startswith('<unavailable>'), (
        f"{helper_name} should return a <unavailable> fallback on "
        f"exception; got {result!r}"
    )
    warning_logged = any(
        rec.levelno == logging.WARNING and 'boom' in rec.message
        for rec in caplog.records
    )
    assert warning_logged, (
        f"{helper_name} did not emit a WARN-level log on exception. "
        f"Records: {[r.getMessage() for r in caplog.records]}"
    )


def test_summary_active_player_logs_warning_on_exception(monkeypatch, caplog):
    """``_summary_active_player`` imports ``get_coordinator`` lazily;
    patch ``components.player.coordinator.get_coordinator`` to raise."""
    # Lazy import inside helper — patch the symbol the helper looks up.
    fake_mod = type(sys)('fake_coord_mod')
    fake_mod.get_coordinator = _boom
    monkeypatch.setitem(sys.modules, 'components.player.coordinator', fake_mod)

    caplog.set_level(logging.WARNING, logger=daemon_mod.logger.name)
    jb = _bare_jukebox()
    result = jb._summary_active_player()

    assert result.startswith('<unavailable>')
    assert any(
        rec.levelno == logging.WARNING and 'boom' in rec.message
        for rec in caplog.records
    ), 'no WARN emitted on get_coordinator exception'
