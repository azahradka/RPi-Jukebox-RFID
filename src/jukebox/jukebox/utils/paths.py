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
    Otherwise anchor it under :func:`get_phoniebox_home`.

    Examples::

        resolve_under_home('shared/settings/jukebox.yaml')
        # /home/boxadmin/RPi-Jukebox-RFID/shared/settings/jukebox.yaml

        resolve_under_home('/etc/phoniebox/config.yaml')
        # /etc/phoniebox/config.yaml   (unchanged)
    """
    p = Path(relative).expanduser()
    if p.is_absolute():
        return p
    return get_phoniebox_home() / p
