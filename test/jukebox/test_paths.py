# -*- coding: utf-8 -*-
"""Tests for ``jukebox.utils.paths``.

Phase 6: replaces cwd-relative ``'../../shared/...'`` paths with
PHONIEBOX_HOME-anchored resolution. These tests pin the resolution
order and the absolute-path passthrough.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add jukebox source to path
_JUKEBOX_SRC = Path(__file__).resolve().parents[2] / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))

from jukebox.utils import paths as paths_mod  # noqa: E402


# Item 6 (project_post_refactor_followups.md): on macOS this test file
# has intermittently failed when run after certain other tests
# (reproduces on main since Phase 6, doesn't manifest in Linux CI).
# Suspected cause is the ``lru_cache`` on
# ``paths._phoniebox_home_cached`` interacting with a stale
# ``PHONIEBOX_HOME`` env var inherited from an outer test that
# monkeypatched it but didn't clean up via its own fixture teardown.
# The autouse fixture below clears both the cache AND any leaked env
# var before each test runs. Less invasive than skipping the file
# wholesale; if the issue resurfaces despite this, switch to
# ``pytest.mark.skipif(platform.system() == 'Darwin', ...)`` per the
# follow-up brief.


@pytest.fixture(autouse=True)
def _clear_home_cache(monkeypatch):
    """Each test should compute home fresh; tests mutate the env var.

    Also clears any leaked ``PHONIEBOX_HOME`` env var that a prior
    test in the same session may have set but not cleaned up — see
    the Item 6 follow-up note above for the macOS isolation context.
    """
    paths_mod.reset_phoniebox_home_cache()
    # Defensive: clear leaked env var. monkeypatch auto-restores after
    # the test, so this doesn't affect siblings.
    monkeypatch.delenv(paths_mod.PHONIEBOX_HOME_ENV, raising=False)
    yield
    paths_mod.reset_phoniebox_home_cache()


def test_get_phoniebox_home_honours_env_var(tmp_path, monkeypatch):
    """``PHONIEBOX_HOME`` env var wins over the walk-up fallback."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    assert paths_mod.get_phoniebox_home() == tmp_path.resolve()


def test_get_phoniebox_home_walk_up_finds_repo_root(monkeypatch):
    """No env var → walk up from the module file to the repo root.

    Reversion check: rename ``src/jukebox`` to anything else and this
    test fails — the walk-up marker is gone.
    """
    monkeypatch.delenv(paths_mod.PHONIEBOX_HOME_ENV, raising=False)
    home = paths_mod.get_phoniebox_home()
    # The repo root must contain src/jukebox and shared (or at least
    # the marker we're keying off).
    assert (home / 'src' / 'jukebox').is_dir()


def test_get_phoniebox_home_empty_env_var_falls_back_to_walk_up(monkeypatch):
    """An empty ``PHONIEBOX_HOME`` is treated as unset."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, '   ')
    home = paths_mod.get_phoniebox_home()
    assert (home / 'src' / 'jukebox').is_dir()


def test_resolve_under_home_relative_anchors_at_home(monkeypatch, tmp_path):
    """Relative paths resolve under home."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    result = paths_mod.resolve_under_home('shared/settings/jukebox.yaml')
    assert result == tmp_path / 'shared' / 'settings' / 'jukebox.yaml'


def test_resolve_under_home_absolute_passes_through(monkeypatch, tmp_path):
    """Absolute paths bypass the resolver entirely."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    abs_path = '/etc/phoniebox/whatever.yaml'
    result = paths_mod.resolve_under_home(abs_path)
    assert result == Path(abs_path)


def test_resolve_under_home_tilde_expanded(monkeypatch, tmp_path):
    """``~/foo`` paths are expanded via ``expanduser``."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    home = os.path.expanduser('~')
    result = paths_mod.resolve_under_home('~/relative_to_user.yaml')
    # Tilde-paths are treated as absolute after expansion.
    assert str(result).startswith(home)


def test_get_phoniebox_home_unfindable_raises(monkeypatch, tmp_path):
    """If neither env nor walk-up succeed, raise RuntimeError.

    We can't actually move the module file. Instead patch the marker
    so the walk-up never finds a match and unset the env.
    """
    monkeypatch.delenv(paths_mod.PHONIEBOX_HOME_ENV, raising=False)
    monkeypatch.setattr(paths_mod, '_HOME_MARKER',
                        ('definitely', 'not_a_real_marker'))
    with pytest.raises(RuntimeError, match='PHONIEBOX_HOME'):
        paths_mod.get_phoniebox_home()


def test_resolve_under_home_returns_pathlib_path(monkeypatch, tmp_path):
    """Always returns a :class:`pathlib.Path`."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    result = paths_mod.resolve_under_home('foo.yaml')
    assert isinstance(result, Path)


def test_resolve_under_home_collapses_dotdot(monkeypatch, tmp_path):
    """Leading ``..`` chains in relative paths collapse against home.

    Item 3 (Item 5b in project_post_refactor_followups.md): the
    legacy ``../../shared/settings/cards.yaml`` default (written when
    the daemon's cwd was ``src/jukebox/``) used to escape PHONIEBOX_HOME
    by two levels. Per-plugin ``_normalize_legacy_cwd_path`` helpers
    stripped the chain; now :func:`resolve_under_home` does it
    centrally via ``.resolve()``.

    Reversion check: remove the ``.resolve()`` from
    ``resolve_under_home`` and this test fails — the joined path
    keeps the ``..`` segments and ends up above ``tmp_path``.
    """
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    result = paths_mod.resolve_under_home('../../shared/settings/cards.yaml')
    # The result must be under home (the resolved tmp_path), not escape it.
    home = tmp_path.resolve()
    assert str(result).startswith(str(home)), (
        f"expected path under {home}, got {result}"
    )
    # And the final tail should be the original logical path.
    assert result.name == 'cards.yaml'


def test_resolve_under_home_collapses_interior_dotdot(monkeypatch, tmp_path):
    """``..`` segments anywhere in the relative path collapse, not
    just leading ones. Mirrors what ``Path.resolve()`` does for an
    absolute path."""
    monkeypatch.setenv(paths_mod.PHONIEBOX_HOME_ENV, str(tmp_path))
    result = paths_mod.resolve_under_home('shared/../shared/settings/cards.yaml')
    expected = tmp_path.resolve() / 'shared' / 'settings' / 'cards.yaml'
    assert result == expected
