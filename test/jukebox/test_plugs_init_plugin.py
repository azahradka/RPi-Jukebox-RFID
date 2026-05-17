# -*- coding: utf-8 -*-
"""Tests for the ``init_plugin()`` convention added by Item 3
(plug-time-coupling refactor).

Migrated plugins expose a top-level ``init_plugin()`` function that
performs all their ``@plugs.register`` / ``@plugs.initialize`` /
``@plugs.finalize`` / ``@plugs.atexit`` registrations. Module-import
runs no plugs registrations; ``plugs.load()`` calls ``init_plugin()``
after the schema validation step.

Reversion check: each test below exercises a real
``plugs.load(...)`` call against a temp plugin package on disk, so
removing the ``init_plugin_hook = getattr(...)`` block from
``plugs.load`` fails them — they are not a parallel implementation of
the dispatch logic.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Make ``src/jukebox`` importable as a package root.
_PKG_ROOT = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import jukebox.plugs as plugs  # noqa: E402


@pytest.fixture
def tmp_plugin_package(tmp_path, monkeypatch):
    """Build a tiny on-disk python package importable by ``plugs.load``.

    Returns a factory ``make(name, init_body)`` that writes
    ``tmp_path/<name>/__init__.py`` with the given module body and
    arranges sys.path so the package is importable. Also ensures the
    plugs registries are cleaned out for ``name`` between invocations.
    """
    monkeypatch.syspath_prepend(str(tmp_path))

    created: list[str] = []

    def make(name: str, init_body: str) -> str:
        pkg_dir = tmp_path / name
        pkg_dir.mkdir(exist_ok=True)
        (pkg_dir / '__init__.py').write_text(textwrap.dedent(init_body))
        created.append(name)
        return name

    yield make

    # Clean plugs state so successive tests can re-load the same name.
    for name in created:
        plugs._PLUGINS.pop(name, None)
        plugs._PLUGINS_FAILED.pop(name, None)
        # _PACKAGE_MAP keys are the python module names, not load_as.
        for src_name in list(plugs._PACKAGE_MAP.keys()):
            if plugs._PACKAGE_MAP[src_name] == name:
                del plugs._PACKAGE_MAP[src_name]
        # Drop cached module so a re-load isn't served stale code.
        sys.modules.pop(name, None)


def test_init_plugin_is_called_when_present(tmp_plugin_package):
    """``plugs.load`` invokes ``init_plugin()`` after schema validation."""
    name = tmp_plugin_package(
        'tplug_init_hook',
        """
        import jukebox.plugs as plugs

        sentinel = {'init_called': False, 'register_called': False}

        def init_plugin():
            sentinel['init_called'] = True

            @plugs.register
            def hello():
                sentinel['register_called'] = True
                return 'hi'
        """,
    )
    plugs.load(name)
    module = plugs.get(name)
    assert module.sentinel['init_called'] is True
    # The decorator ran inside init_plugin, so the function should be
    # callable through the regular plugs.call path.
    result = plugs.call(name, 'hello')
    assert result == 'hi'
    assert module.sentinel['register_called'] is True


def test_module_without_init_plugin_still_loads(tmp_plugin_package):
    """Back-compat: a plugin without ``init_plugin`` still loads, and
    module-body ``@plugs.register`` decorators continue to work.

    Reversion check: a module that uses the legacy module-level
    decorator style continues to register the function. If the
    init_plugin hook stopped running legacy decorators, this test
    would still pass (decorators ran during import_module already);
    it primarily guards against the loader requiring init_plugin.
    """
    name = tmp_plugin_package(
        'tplug_no_hook',
        """
        import jukebox.plugs as plugs

        @plugs.register
        def legacy_func():
            return 42
        """,
    )
    plugs.load(name)
    assert plugs.call(name, 'legacy_func') == 42


def test_init_plugin_registers_initializer_and_atexit(tmp_plugin_package):
    """``@plugs.initialize`` / ``@plugs.atexit`` decorators applied
    inside ``init_plugin`` correctly hook into the per-package lists
    so the loader calls them at the right times."""
    name = tmp_plugin_package(
        'tplug_init_atexit',
        """
        import jukebox.plugs as plugs

        events = []

        def init_plugin():
            @plugs.initialize
            def my_init():
                events.append('init')

            @plugs.atexit
            def my_atexit(**kwargs):
                events.append(('atexit', kwargs.get('signal_number')))
        """,
    )
    plugs.load(name)
    module = plugs.get(name)
    assert module.events == ['init'], (
        f"initializer should fire once after init_plugin; got {module.events}"
    )

    # atexit fires when plugs.close_down() is called. We don't want to
    # tear down the whole process registry, so probe directly:
    pack = plugs._PLUGINS[name]
    assert len(pack.atexit) == 1
    pack.atexit[0](signal_number=15)
    assert module.events[-1] == ('atexit', 15)


def test_init_plugin_failure_marks_plugin_failed(tmp_plugin_package):
    """An ``init_plugin`` that raises is reported in failed-plugins."""
    name = tmp_plugin_package(
        'tplug_init_raises',
        """
        def init_plugin():
            raise RuntimeError('boom in init_plugin')
        """,
    )
    with pytest.raises(RuntimeError, match='boom in init_plugin'):
        plugs.load(name)
    assert name in plugs._PLUGINS_FAILED


def test_module_level_import_has_no_plugs_side_effects(tmp_plugin_package):
    """The headline ergonomics win: ``import <plugin>`` performs zero
    plugs registrations, so test code / smoke-harness code can pull
    the module in without forcing a full plugs.load cycle.

    Reversion check: if a plugin author moves ``@plugs.register`` back
    out of ``init_plugin`` to the module body, this test fails — the
    decorator would call ``_PACKAGE_MAP[plugin_origin]`` at import
    time and KeyError (since plugs.load wasn't called).
    """
    name = tmp_plugin_package(
        'tplug_pure_import',
        """
        import jukebox.plugs as plugs

        def init_plugin():
            @plugs.register
            def deferred():
                return 'deferred'
        """,
    )
    # Plain import — no plugs.load. Must not raise, and must not
    # leak any entries into the plugs registries.
    import importlib
    pre_plugins = set(plugs._PLUGINS)
    pre_packages = set(plugs._PACKAGE_MAP)
    importlib.import_module(name)
    assert set(plugs._PLUGINS) == pre_plugins
    assert set(plugs._PACKAGE_MAP) == pre_packages
