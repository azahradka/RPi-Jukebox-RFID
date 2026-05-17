# -*- coding: utf-8 -*-
"""Phoniebox path resolution.

Phase 6: replace cwd-relative paths (``'../../shared/...'``) scattered
through the codebase with an explicit, anchored resolution.

The "Phoniebox home" is the repository checkout root — the directory
that contains ``src/``, ``shared/``, ``resources/``, ``installation/``.
On a default install it's ``/home/boxadmin/RPi-Jukebox-RFID``.

Resolution order, first wins:

1. The ``PHONIEBOX_HOME`` environment variable, if set to a non-empty
   string. Useful for tests, alternative installs, or systemd units
   that want to be explicit.
2. A walk up the filesystem from this file's location until a marker
   directory (``src/jukebox``) is found. This is the standard
   production path: the module lives at
   ``<home>/src/jukebox/jukebox/utils/paths.py``, so home is four
   ``parent`` hops up.

The walk-up keeps the daemon working in a fresh checkout regardless of
the working directory it's launched from — a problem the pre-Phase-6
code "solved" with cwd-relative ``'../../shared/...'`` defaults that
broke when ``run_jukebox.sh`` was invoked from anywhere other than
``src/jukebox``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union


PHONIEBOX_HOME_ENV = 'PHONIEBOX_HOME'

# Marker that identifies the repo root when walking up from a file.
_HOME_MARKER = ('src', 'jukebox')


def _walk_up_to_home(start: Path) -> Optional[Path]:
    """Walk up from ``start`` looking for the repo root marker.

    Returns the directory containing the marker, or ``None`` if not
    found (we've reached the filesystem root).
    """
    cur = start.resolve()
    for parent in (cur, *cur.parents):
        if (parent / _HOME_MARKER[0] / _HOME_MARKER[1]).is_dir():
            return parent
    return None


@lru_cache(maxsize=1)
def get_phoniebox_home() -> Path:
    """Return the Phoniebox repo root as a :class:`pathlib.Path`.

    Resolution order:

    1. ``$PHONIEBOX_HOME`` env var (if set and non-empty).
    2. Walk up from this file looking for ``src/jukebox`` marker.

    Raises :class:`RuntimeError` if neither resolves — a deployment
    so broken we'd rather fail loudly than silently use the cwd.

    Result is memoised; clear with :func:`reset_phoniebox_home_cache`
    if a test needs to override ``PHONIEBOX_HOME`` mid-process.
    """
    env_value = os.environ.get(PHONIEBOX_HOME_ENV, '').strip()
    if env_value:
        return Path(env_value).expanduser().resolve()

    home = _walk_up_to_home(Path(__file__))
    if home is not None:
        return home

    raise RuntimeError(
        f"Could not locate Phoniebox home. Set the {PHONIEBOX_HOME_ENV} "
        f"environment variable to the repo root (the directory "
        f"containing src/, shared/, resources/)."
    )


def reset_phoniebox_home_cache() -> None:
    """Clear the memoised home — for tests that mutate the env var."""
    get_phoniebox_home.cache_clear()


def resolve_under_home(relative: Union[str, Path]) -> Path:
    """Resolve ``relative`` against the Phoniebox home directory.

    If ``relative`` is already absolute, return it unchanged.
    Otherwise:

    1. Strip any leading ``..`` chain from the relative path. The
       legacy ``jukebox.default.yaml`` defaults like
       ``../../shared/settings/cards.yaml`` were written when the
       daemon's cwd was ``src/jukebox/``; under Phase 6's
       PHONIEBOX_HOME anchoring those segments would push the path
       above the repo root, which is never what the user intended.
       Treat any leading ``..`` chain as a legacy CWD-relative
       marker and collapse it.
    2. Anchor the remainder under :func:`get_phoniebox_home`.
    3. Call ``.resolve()`` to fold interior ``..`` segments and
       normalise the absolute path.

    Item 3 (Item 5b in project_post_refactor_followups.md):
    consolidates the per-plugin ``_normalize_legacy_cwd_path``
    helpers that ``cards/__init__.py`` and ``rfid/reader/__init__.py``
    each carried.

    Examples::

        resolve_under_home('shared/settings/jukebox.yaml')
        # /home/boxadmin/RPi-Jukebox-RFID/shared/settings/jukebox.yaml

        resolve_under_home('../../shared/settings/cards.yaml')
        # /home/boxadmin/RPi-Jukebox-RFID/shared/settings/cards.yaml
        # (the leading ``..`` chain is stripped before joining)

        resolve_under_home('/etc/phoniebox/config.yaml')
        # /etc/phoniebox/config.yaml   (unchanged)
    """
    p = Path(relative).expanduser()
    if p.is_absolute():
        return p
    # Strip leading ``..`` chain (legacy CWD-relative marker).
    parts = list(p.parts)
    while parts and parts[0] == '..':
        parts.pop(0)
    stripped = Path(*parts) if parts else Path('.')
    return (get_phoniebox_home() / stripped).resolve()
