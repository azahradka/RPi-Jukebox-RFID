# -*- coding: utf-8 -*-
"""Tests for the unified RPC contract source-of-truth (Phase 5a).

``src/jukebox/components/rpc_command_alias.py`` defines:

* ``cmd_alias_definitions`` — short aliases used in cards.yaml + GPIO
  triggers (this dict pre-existed; we just verify nothing regressed).
* ``web_command_definitions`` — comprehensive Web UI RPC catalog. The
  generator in ``src/webapp/scripts/generate-commands.js`` consumes
  this dict to regenerate ``src/webapp/src/commands/index.js``.
* ``KNOWN_PLUGIN_METHOD_ALLOWLIST`` — validator escape hatch for
  triples that cannot be discovered by AST scanning.
* ``KNOWN_INTERNAL_PLUGIN_METHODS`` — triples the generator must NEVER
  emit to the JS file (backend-only RPCs, e.g. ``play_single_passive``).

These tests pin the shape and a few load-bearing invariants:

1. Both dicts import without raising.
2. Every entry has the required keys.
3. The two dicts are consistent where they overlap (e.g. ``play_card``
   in card aliases targets the same triple as ``play_card`` would in
   the Web UI catalog, if both define it).
4. ``KNOWN_INTERNAL_PLUGIN_METHODS`` does NOT overlap with anything
   in ``web_command_definitions`` (the validator enforces this at
   build time; this is a belt-and-braces unit check).
"""

import sys
from pathlib import Path

import pytest

_PKG_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from components.rpc_command_alias import (  # noqa: E402
    cmd_alias_definitions,
    web_command_definitions,
    KNOWN_PLUGIN_METHOD_ALLOWLIST,
    KNOWN_INTERNAL_PLUGIN_METHODS,
)


def test_cmd_alias_definitions_is_non_empty():
    assert isinstance(cmd_alias_definitions, dict)
    assert len(cmd_alias_definitions) > 0


def test_web_command_definitions_is_non_empty():
    assert isinstance(web_command_definitions, dict)
    assert len(web_command_definitions) > 0


@pytest.mark.parametrize("name,spec", list(web_command_definitions.items()))
def test_web_command_required_keys(name, spec):
    """Every web command must declare package + plugin (method optional)."""
    assert isinstance(spec, dict), f"{name!r} spec is not a dict"
    assert 'package' in spec, f"{name!r} missing 'package'"
    assert 'plugin' in spec, f"{name!r} missing 'plugin'"
    assert isinstance(spec['package'], str)
    assert isinstance(spec['plugin'], str)
    if 'method' in spec and spec['method'] is not None:
        assert isinstance(spec['method'], str)
    if 'argKeys' in spec:
        assert isinstance(spec['argKeys'], list)
        for key in spec['argKeys']:
            assert isinstance(key, str)


def test_known_internal_methods_excluded_from_web_commands():
    """The generator's validator enforces this; we double-check at the
    Python level so a wrong edit fails immediately, not only at the
    webapp build step. ``play_single_passive`` is the canonical case
    (project_phase_3b_followups.md #2)."""
    for triple in KNOWN_INTERNAL_PLUGIN_METHODS:
        package, plugin, method = triple
        for name, spec in web_command_definitions.items():
            spec_pkg = spec['package']
            spec_plug = spec['plugin']
            spec_method = spec.get('method')
            if spec_pkg == package and spec_plug == plugin and spec_method == method:
                pytest.fail(
                    f"web_command_definitions[{name!r}] exposes the internal-only "
                    f"RPC {package}.{plugin}.{method}; remove it or update "
                    f"KNOWN_INTERNAL_PLUGIN_METHODS."
                )


def test_play_single_passive_is_marked_internal():
    """Phase 3b FU#2: ``playermpd.ctrl.play_single_passive`` must be
    in KNOWN_INTERNAL_PLUGIN_METHODS so the Web UI generator refuses
    to emit it."""
    assert ('player', 'ctrl', 'play_single_passive') in KNOWN_INTERNAL_PLUGIN_METHODS


def test_card_aliases_use_canonical_packages():
    """Card aliases that reference player backends must use the alias
    names exposed in the Web UI catalog (consistency check)."""
    web_pkgs = {spec['package'] for spec in web_command_definitions.values()}
    for name, spec in cmd_alias_definitions.items():
        if 'package' not in spec:
            continue  # 2-part call with package inferred via spec body
        pkg = spec['package']
        # Player packages must match what the Web UI catalog declares.
        if pkg in ('player', 'player_spotify', 'player_podcast'):
            assert pkg in web_pkgs, (
                f"card alias {name!r} uses package {pkg!r} which is missing "
                f"from web_command_definitions."
            )


def test_allowlist_entries_are_three_tuples():
    """KNOWN_PLUGIN_METHOD_ALLOWLIST entries must be (pkg, plugin, method)
    tuples. Method may be None for 2-part calls."""
    for entry in KNOWN_PLUGIN_METHOD_ALLOWLIST:
        assert isinstance(entry, tuple), f"allowlist entry not a tuple: {entry!r}"
        assert len(entry) == 3, f"allowlist entry wrong length: {entry!r}"
        pkg, plug, method = entry
        assert isinstance(pkg, str)
        assert isinstance(plug, str)
        assert method is None or isinstance(method, str)
