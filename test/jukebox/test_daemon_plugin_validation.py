# -*- coding: utf-8 -*-
"""Regression tests for :meth:`JukeBox._validate_critical_plugins`.

Phase 1, fix #6: ``daemon.run`` loads plugins with ``ignore_errors=True``
and so could happily boot into a broken state. After loading, the daemon
now validates:

* ``publishing`` is loaded → otherwise SystemExit(2).
* ``player`` and ``rfid`` are loaded → otherwise logs ERROR but continues.
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def daemon_module():
    """Import jukebox.daemon, mocking out heavy import-time deps.

    ``daemon.py`` does ``import jukebox.cfghandler`` then later
    ``cfg = jukebox.cfghandler.get_handler('jukebox')`` — so the mock
    must be attached as an attribute on the real ``jukebox`` package,
    not just installed under ``sys.modules``.
    """
    import jukebox as _jukebox_pkg
    real_cfg = getattr(_jukebox_pkg, 'cfghandler', None)
    mock_cfg = mock.MagicMock()
    mock_cfg.get_handler.return_value = mock.MagicMock()
    _jukebox_pkg.cfghandler = mock_cfg

    with mock.patch.dict('sys.modules', {
        'misc': mock.MagicMock(flatten=lambda x: x),
        'jukebox.plugs': mock.MagicMock(),
        'jukebox.publishing': mock.MagicMock(),
        'jukebox.rpc.server': mock.MagicMock(),
        'jukebox.cfghandler': mock_cfg,
    }):
        sys.modules.pop('jukebox.daemon', None)
        import jukebox.daemon as daemon
        try:
            yield daemon
        finally:
            sys.modules.pop('jukebox.daemon', None)

    if real_cfg is None:
        if hasattr(_jukebox_pkg, 'cfghandler'):
            delattr(_jukebox_pkg, 'cfghandler')
    else:
        _jukebox_pkg.cfghandler = real_cfg


def _make_juke(daemon_module):
    """Build a JukeBox with __init__ bypassed."""
    j = daemon_module.JukeBox.__new__(daemon_module.JukeBox)
    return j


def test_publishing_missing_exits_non_zero(daemon_module, caplog):
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
        'rfid': 'rfid.reader',
    }
    pack_ok = ['player', 'rfid']  # publishing missing
    with pytest.raises(SystemExit) as exc:
        juke._validate_critical_plugins(pack_ok, plugins_named)
    assert exc.value.code == 2


def test_player_missing_logs_error_but_continues(daemon_module, caplog):
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
        'rfid': 'rfid.reader',
    }
    pack_ok = ['publishing', 'rfid']  # player missing
    caplog.set_level('ERROR', logger='jb.daemon')
    juke._validate_critical_plugins(pack_ok, plugins_named)
    assert any("Critical plugin 'player'" in rec.message for rec in caplog.records)


def test_rfid_missing_logs_error_but_continues(daemon_module, caplog):
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
        'rfid': 'rfid.reader',
    }
    pack_ok = ['publishing', 'player']  # rfid missing
    caplog.set_level('ERROR', logger='jb.daemon')
    juke._validate_critical_plugins(pack_ok, plugins_named)
    assert any("Critical plugin 'rfid'" in rec.message for rec in caplog.records)


def test_all_good_no_error_logged(daemon_module, caplog):
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
        'rfid': 'rfid.reader',
    }
    pack_ok = ['publishing', 'player', 'rfid']
    caplog.set_level('ERROR', logger='jb.daemon')
    juke._validate_critical_plugins(pack_ok, plugins_named)
    # No "Critical plugin" ERROR messages.
    assert not any("Critical plugin" in rec.message for rec in caplog.records)


def test_pack_ok_none_treated_as_empty(daemon_module):
    """If get_all_loaded_packages itself returned None (misc plugin
    failed), the validator must still fail safely — publishing is by
    definition missing → exit."""
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
        'rfid': 'rfid.reader',
    }
    with pytest.raises(SystemExit) as exc:
        juke._validate_critical_plugins(None, plugins_named)
    assert exc.value.code == 2


def test_rfid_only_required_when_in_named(daemon_module, caplog):
    """If the config doesn't declare ``rfid`` at all (a Pi running
    without an RFID reader), the validator must not complain about it."""
    juke = _make_juke(daemon_module)
    plugins_named = {
        'publishing': 'publishing',
        'player': 'playermpd',
    }
    pack_ok = ['publishing', 'player']
    caplog.set_level('ERROR', logger='jb.daemon')
    juke._validate_critical_plugins(pack_ok, plugins_named)
    assert not any("Critical plugin 'rfid'" in rec.message for rec in caplog.records)
