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


@pytest.fixture(autouse=True)
def _clear_home_cache():
    """Each test should compute home fresh; tests mutate the env var."""
    paths_mod.reset_phoniebox_home_cache()
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
