# -*- coding: utf-8 -*-
"""Tests for the ``--args`` / ``--kwargs`` plumbing in
``src/jukebox/run_rpc_tool.py`` one-shot mode (followups item 10).

The CLI script is imported as a module so we can drive its real
argparse + dispatch path. The RPC client is replaced with a
:class:`_FakeRpcClient` that captures the ``enque(...)`` call -- this
is the boundary we want to assert against, not a re-implementation of
the dispatch logic.

Reversion-check: the
``test_one_shot_dispatch_passes_args_and_kwargs_through`` case fails
when the ``--args`` / ``--kwargs`` plumbing in ``runcmd`` is reverted.
"""

from __future__ import annotations

import importlib
import runpy
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_JUKEBOX_SRC = _REPO_ROOT / 'src' / 'jukebox'
_SCRIPT_PATH = _JUKEBOX_SRC / 'run_rpc_tool.py'


@pytest.fixture(autouse=True)
def _ensure_jukebox_on_path():
    """Make ``src/jukebox`` importable for the duration of this module's
    tests. The top-level conftest does this for tests under ``test/``,
    but we re-assert it explicitly for clarity."""
    added = False
    if str(_JUKEBOX_SRC) not in sys.path:
        sys.path.insert(0, str(_JUKEBOX_SRC))
        added = True
    yield
    if added:
        sys.path.remove(str(_JUKEBOX_SRC))


@pytest.fixture
def rpc_tool_module():
    """Import the script as a module (without triggering ``__main__``)."""
    if 'run_rpc_tool' in sys.modules:
        del sys.modules['run_rpc_tool']
    module = importlib.import_module('run_rpc_tool')
    yield module
    if 'run_rpc_tool' in sys.modules:
        del sys.modules['run_rpc_tool']


# ---------------------------------------------------------------------------
# parse_json_args -- pure-ish seam, no RPC dependency
# ---------------------------------------------------------------------------


def test_args_flag_accepts_json_list(rpc_tool_module):
    parsed_args, parsed_kwargs = rpc_tool_module.parse_json_args('["foo"]', None)
    assert parsed_args == ["foo"]
    assert parsed_kwargs == {}


def test_kwargs_flag_accepts_json_dict(rpc_tool_module):
    parsed_args, parsed_kwargs = rpc_tool_module.parse_json_args(
        None, '{"recursive": true}')
    assert parsed_args == []
    assert parsed_kwargs == {"recursive": True}


def test_both_flags_parse_together(rpc_tool_module):
    parsed_args, parsed_kwargs = rpc_tool_module.parse_json_args(
        '["X", 1]', '{"a": "b"}')
    assert parsed_args == ["X", 1]
    assert parsed_kwargs == {"a": "b"}


def test_args_default_is_empty_list(rpc_tool_module):
    parsed_args, parsed_kwargs = rpc_tool_module.parse_json_args(None, None)
    assert parsed_args == []
    assert parsed_kwargs == {}


def test_args_flag_rejects_malformed_json(rpc_tool_module):
    with pytest.raises(ValueError) as excinfo:
        rpc_tool_module.parse_json_args('not json', None)
    assert '--args' in str(excinfo.value)


def test_kwargs_flag_rejects_malformed_json(rpc_tool_module):
    with pytest.raises(ValueError) as excinfo:
        rpc_tool_module.parse_json_args(None, '{not: valid}')
    assert '--kwargs' in str(excinfo.value)


def test_args_flag_rejects_non_list(rpc_tool_module):
    """``--args '{"k": "v"}'`` is valid JSON but the wrong shape."""
    with pytest.raises(ValueError) as excinfo:
        rpc_tool_module.parse_json_args('{"k": "v"}', None)
    msg = str(excinfo.value)
    assert '--args' in msg
    assert 'list' in msg


def test_kwargs_flag_rejects_non_dict(rpc_tool_module):
    """``--kwargs '[]'`` is valid JSON but the wrong shape."""
    with pytest.raises(ValueError) as excinfo:
        rpc_tool_module.parse_json_args(None, '[]')
    msg = str(excinfo.value)
    assert '--kwargs' in msg
    assert 'object' in msg


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------


def test_argparser_exposes_args_and_kwargs(rpc_tool_module):
    parser = rpc_tool_module.build_argparser()
    ns = parser.parse_args(['-c', 'player.ctrl.play_folder',
                            '--args', '["X"]',
                            '--kwargs', '{"recursive": true}'])
    assert ns.command == 'player.ctrl.play_folder'
    assert ns.args == '["X"]'
    assert ns.kwargs == '{"recursive": true}'


def test_argparser_args_and_kwargs_default_to_none(rpc_tool_module):
    parser = rpc_tool_module.build_argparser()
    ns = parser.parse_args(['-c', 'playerstatus'])
    assert ns.command == 'playerstatus'
    assert ns.args is None
    assert ns.kwargs is None


# ---------------------------------------------------------------------------
# runcmd -- end-to-end up to the RPC client boundary
# ---------------------------------------------------------------------------


class _FakeRpcClient:
    """Captures the ``enque(...)`` call args. No socket; no real ZMQ."""

    def __init__(self, address='tcp://fake', context=None, **kwargs):
        self._address = address
        self.calls = []  # list[dict] of captured enque calls

    @property
    def address(self):
        return self._address

    def enque(self, package, plugin, method=None, args=None, kwargs=None,
              ignore_response=None, ignore_errors=None):
        self.calls.append({
            'package': package,
            'plugin': plugin,
            'method': method,
            'args': args,
            'kwargs': kwargs,
        })
        return {'ok': True}


def test_runcmd_passes_explicit_args_and_kwargs_to_client(
        rpc_tool_module, monkeypatch, capsys):
    """``runcmd('player.ctrl.play_folder', args=['X'], kwargs={'recursive': True})``
    must reach ``client.enque(...)`` with the same args/kwargs.
    """
    fake = _FakeRpcClient()
    monkeypatch.setattr(rpc_tool_module, 'client', fake, raising=False)

    rpc_tool_module.runcmd(
        'player.ctrl.play_folder',
        args=['BeatlesAlbum'],
        kwargs={'recursive': True},
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call['package'] == 'player'
    assert call['plugin'] == 'ctrl'
    assert call['method'] == 'play_folder'
    assert call['args'] == ['BeatlesAlbum']
    assert call['kwargs'] == {'recursive': True}


def test_runcmd_back_compat_whitespace_args_still_work(
        rpc_tool_module, monkeypatch):
    """Without ``args=`` kwarg, the legacy whitespace-split path applies."""
    fake = _FakeRpcClient()
    monkeypatch.setattr(rpc_tool_module, 'client', fake, raising=False)

    rpc_tool_module.runcmd('volume.ctrl.set_volume 50')

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call['package'] == 'volume'
    assert call['plugin'] == 'ctrl'
    assert call['method'] == 'set_volume'
    # tonum() converts the '50' string to int
    assert call['args'] == [50]


def test_runcmd_zero_arg_command_still_works(
        rpc_tool_module, monkeypatch):
    """``-c playerstatus`` with no flags: empty args, no kwargs."""
    fake = _FakeRpcClient()
    monkeypatch.setattr(rpc_tool_module, 'client', fake, raising=False)

    rpc_tool_module.runcmd('player.ctrl.playerstatus')

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call['args'] == []
    # kwargs stays None when not explicitly supplied -- preserves the
    # pre-existing wire format (no 'kwargs' key in the JSON request).
    assert call['kwargs'] is None


# ---------------------------------------------------------------------------
# End-to-end: argparse -> parse_json_args -> runcmd -> client.enque
# Drives the script as ``__main__`` to exercise the real wiring.
# ---------------------------------------------------------------------------


def test_one_shot_dispatch_passes_args_and_kwargs_through(monkeypatch, capsys):
    """The full one-shot path: CLI flags reach ``client.enque(...)``.

    This is the **reversion-check** test: revert the ``args=`` /
    ``kwargs=`` plumbing in ``runcmd`` and this assertion fails.
    """
    import jukebox.rpc.client as rpc_client_mod

    captured = {'calls': []}

    class _CapturingClient(_FakeRpcClient):
        def __init__(self, address, context=None, **kwargs):
            super().__init__(address, context, **kwargs)
            captured['client'] = self

        def enque(self, package, plugin, method=None,
                  args=None, kwargs=None, **kw):
            captured['calls'].append({
                'package': package,
                'plugin': plugin,
                'method': method,
                'args': args,
                'kwargs': kwargs,
            })
            return None

    monkeypatch.setattr(rpc_client_mod, 'RpcClient', _CapturingClient)
    monkeypatch.setattr(sys, 'argv', [
        'run_rpc_tool.py',
        '-c', 'player.ctrl.play_folder',
        '--args', '["BeatlesAlbum"]',
        '--kwargs', '{"recursive": true}',
    ])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(_SCRIPT_PATH), run_name='__main__')
    assert excinfo.value.code == 0

    assert len(captured['calls']) == 1
    call = captured['calls'][0]
    assert call['package'] == 'player'
    assert call['plugin'] == 'ctrl'
    assert call['method'] == 'play_folder'
    assert call['args'] == ['BeatlesAlbum']
    assert call['kwargs'] == {'recursive': True}


def test_one_shot_dispatch_rejects_bad_args_json(monkeypatch, capsys):
    """Malformed ``--args`` JSON exits non-zero with a clear message
    (argparse.error -> SystemExit(2))."""
    import jukebox.rpc.client as rpc_client_mod
    monkeypatch.setattr(rpc_client_mod, 'RpcClient', _FakeRpcClient)
    monkeypatch.setattr(sys, 'argv', [
        'run_rpc_tool.py',
        '-c', 'player.ctrl.play_folder',
        '--args', 'not json',
    ])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(_SCRIPT_PATH), run_name='__main__')
    assert excinfo.value.code != 0
    stderr = capsys.readouterr().err
    assert '--args' in stderr


def test_one_shot_dispatch_rejects_bad_kwargs_shape(monkeypatch, capsys):
    """``--kwargs '[]'`` is valid JSON but wrong shape; reject."""
    import jukebox.rpc.client as rpc_client_mod
    monkeypatch.setattr(rpc_client_mod, 'RpcClient', _FakeRpcClient)
    monkeypatch.setattr(sys, 'argv', [
        'run_rpc_tool.py',
        '-c', 'player.ctrl.play_folder',
        '--kwargs', '[]',
    ])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(_SCRIPT_PATH), run_name='__main__')
    assert excinfo.value.code != 0
    stderr = capsys.readouterr().err
    assert '--kwargs' in stderr
