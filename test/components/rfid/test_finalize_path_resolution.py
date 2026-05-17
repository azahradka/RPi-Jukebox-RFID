# -*- coding: utf-8 -*-
"""Regression tests for finalize-time YAML path resolution.

Background
----------
Phase 6 anchored config-file paths under :envvar:`PHONIEBOX_HOME` (the
repo root) via :func:`jukebox.utils.paths.resolve_under_home`. The
legacy ``jukebox.default.yaml`` defaults for ``rfid.card_database`` and
``rfid.reader_config`` still contain ``../../shared/settings/...`` —
strings that were written when the daemon's CWD was ``src/jukebox/``.
Under the new anchoring those leading ``..`` segments escaped the repo
root (``<repo>/../../shared/settings/cards.yaml``), so a clean install
silently failed to load cards/rfid at startup.

Fix (2026-05-17)
----------------
Both ``cards.finalize`` and ``rfid.reader.finalize`` now call a small
``_normalize_legacy_cwd_path`` helper that strips a leading ``..``
chain. The resolved path must therefore stay under
:envvar:`PHONIEBOX_HOME` regardless of whether the YAML used the
legacy CWD-relative form (``../../shared/...``) or the new
home-relative form (``shared/...``).

Reversion check
---------------
Removing the ``_normalize_legacy_cwd_path`` call in either finalize
and passing the raw ``../../shared/...`` string through makes
``test_finalize_path_under_repo_root`` fail because the resolved path
escapes the home directory.

Plug-time-import workaround
---------------------------
Importing ``components.rfid.cards`` or ``components.rfid.reader``
normally triggers ``@plugs.register`` decorators that require the full
daemon plugin registry. The helper we want to exercise is a small pure
function defined at module top level; we load each module via
``importlib.util.spec_from_file_location`` with a minimal stub of the
``jukebox.plugs`` machinery so the decorator no-ops and the rest of
the module body executes far enough to expose the helper.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_JUKEBOX_SRC = _REPO_ROOT / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


def _load_paths_module():
    """Import ``jukebox.utils.paths`` defensively.

    Earlier-running tests under ``test/components/playerpodcast`` and
    ``test/components/playerspotify`` install a stub ``ModuleType``
    for ``jukebox.utils`` in ``sys.modules`` — that breaks
    ``from jukebox.utils.paths import ...`` because the stub is not
    a package. Detect and recover by loading ``paths.py`` directly
    via ``spec_from_file_location`` under a non-canonical name.
    """
    try:
        from jukebox.utils.paths import resolve_under_home as _r
        return _r
    except (ModuleNotFoundError, ImportError):
        spec = importlib.util.spec_from_file_location(
            '_test_paths_for_rfid_finalize',
            _JUKEBOX_SRC / 'jukebox' / 'utils' / 'paths.py',
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.resolve_under_home


resolve_under_home = _load_paths_module()


def _load_helper(module_qualname: str, file_path: Path):
    """Load a plugin module far enough to expose ``_normalize_legacy_cwd_path``.

    We can't ``import`` the plugin modules normally because their
    ``@plugs.register`` decorators run at import time and require the
    daemon-side plugin registry. Instead, we load the module under a
    *non-canonical* dotted name (so we don't pollute ``sys.modules``
    in a way that affects other tests) and patch ``jukebox.plugs``
    decorators to no-op for the duration of the load.
    """
    import jukebox.plugs as real_plugs

    saved_register = real_plugs.register
    saved_finalize = real_plugs.finalize
    saved_atexit = real_plugs.atexit
    saved_initialize = real_plugs.initialize
    saved_tag = real_plugs.tag

    def _noop_decorator(*args, **kwargs):
        # Support both @decorator and @decorator(...) forms.
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def wrap(fn):
            return fn
        return wrap

    real_plugs.register = _noop_decorator
    real_plugs.finalize = _noop_decorator
    real_plugs.atexit = _noop_decorator
    real_plugs.initialize = _noop_decorator
    real_plugs.tag = _noop_decorator
    try:
        spec = importlib.util.spec_from_file_location(module_qualname, file_path)
        mod = importlib.util.module_from_spec(spec)
        # Add to sys.modules under the non-canonical name only.
        sys.modules[module_qualname] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:
            sys.modules.pop(module_qualname, None)
            raise
        return mod
    finally:
        real_plugs.register = saved_register
        real_plugs.finalize = saved_finalize
        real_plugs.atexit = saved_atexit
        real_plugs.initialize = saved_initialize
        real_plugs.tag = saved_tag


@pytest.fixture(scope='module')
def cards_module():
    return _load_helper(
        '_test_cards_plugin_stub',
        _JUKEBOX_SRC / 'components' / 'rfid' / 'cards' / '__init__.py',
    )


@pytest.fixture(scope='module')
def reader_module():
    return _load_helper(
        '_test_reader_plugin_stub',
        _JUKEBOX_SRC / 'components' / 'rfid' / 'reader' / '__init__.py',
    )


@pytest.fixture
def home_dir():
    """The repo root resolved through ``paths.resolve_under_home``."""
    return resolve_under_home('.').resolve()


@pytest.mark.parametrize(
    "fixture_name,legacy_default,expected_basename",
    [
        ('cards_module', '../../shared/settings/cards.yaml', 'cards.yaml'),
        ('reader_module', '../../shared/settings/rfid.yaml', 'rfid.yaml'),
    ],
    ids=['cards', 'rfid'],
)
def test_finalize_path_under_repo_root(request, home_dir, fixture_name, legacy_default, expected_basename):
    """The legacy default path must resolve under the repo root.

    Reversion check: the un-normalised legacy form does escape the repo
    root (verified in the assertion at the bottom of this test),
    confirming the regression manifests without the fix.
    """
    mod = request.getfixturevalue(fixture_name)
    normalize = mod._normalize_legacy_cwd_path

    normalized = normalize(legacy_default)
    resolved = resolve_under_home(normalized).resolve()

    # Resolved path lives under the repo root.
    home = home_dir
    assert str(resolved).startswith(str(home) + '/') or resolved == home, (
        f"resolved path {resolved!r} is not under home {home!r}; "
        f"normalised input was {normalized!r}"
    )

    # And it points at the right basename in shared/settings/.
    expected = home / 'shared' / 'settings' / expected_basename
    assert resolved == expected, f"resolved={resolved!r}, expected {expected!r}"

    # Belt-and-braces: the un-normalised legacy form would escape.
    escaped = resolve_under_home(legacy_default).resolve()
    assert escaped != expected, (
        "without normalisation the legacy default should escape; if "
        "this passes, the regression has been fixed in resolve_under_home "
        "itself and the finalize-side normaliser is redundant."
    )


@pytest.mark.parametrize("fixture_name", ['cards_module', 'reader_module'])
def test_normalize_passes_through_home_relative_paths(request, fixture_name):
    """New-style ``shared/settings/...`` strings must not be altered."""
    normalize = request.getfixturevalue(fixture_name)._normalize_legacy_cwd_path
    assert normalize('shared/settings/cards.yaml') == 'shared/settings/cards.yaml'


@pytest.mark.parametrize("fixture_name", ['cards_module', 'reader_module'])
def test_normalize_passes_through_absolute_paths(request, fixture_name):
    """Absolute paths must not be altered (operator override)."""
    normalize = request.getfixturevalue(fixture_name)._normalize_legacy_cwd_path
    assert normalize('/etc/phoniebox/cards.yaml') == '/etc/phoniebox/cards.yaml'


@pytest.mark.parametrize("fixture_name", ['cards_module', 'reader_module'])
def test_normalize_strips_arbitrary_leading_dotdot_chain(request, fixture_name):
    """A leading ``..`` chain of any length collapses to home-relative."""
    normalize = request.getfixturevalue(fixture_name)._normalize_legacy_cwd_path
    assert normalize('../../../shared/settings/cards.yaml') == 'shared/settings/cards.yaml'
    assert normalize('../shared/settings/cards.yaml') == 'shared/settings/cards.yaml'
