# -*- coding: utf-8 -*-
"""Atomic file I/O helpers.

JSON state files (player state, podcast state, Spotify state) used a naive
write pattern: ``open(path, 'w')`` followed by ``json.dump``. If the process
crashed (SIGKILL, power loss, OOM) mid-write, the file on disk was left
truncated or partially written, and the next start-up's ``_load_state``
would fail to parse it and silently fall back to an empty dict — losing
last-played state, resume positions, and device IDs.

The helpers here implement the classic write-temp + fsync + rename pattern:

  1. Write payload to ``<path>.tmp`` in the same directory (so the rename
     is on the same filesystem, which makes it atomic on POSIX).
  2. ``flush`` + ``os.fsync`` the temp file to push it to durable storage.
  3. ``os.replace`` the temp over the target — atomic on POSIX, and on
     Windows (Python 3.3+).

If anything fails before the replace, the temp file is removed and the
original target is untouched.
"""

import json
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger('jb.utils.atomic_io')


def atomic_write_json(path, data: Any, *, indent: int = 2) -> None:
    """Serialize ``data`` to ``path`` atomically.

    Writes to a temp file in the same directory, fsyncs it, then
    atomically renames it over the target. The parent directory is
    created if it does not already exist.

    :param path: Destination path (str or :class:`os.PathLike`).
    :param data: Any JSON-serializable object.
    :param indent: ``json.dump`` indent (default 2 to match prior format).
    :raises: Whatever ``json.dump`` / file I/O raise; the partial temp
        file (if any) is removed before re-raising.
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)

    # ``delete=False`` because we need to close the file before the rename
    # on Windows, and we want explicit control over cleanup on error.
    tmp = tempfile.NamedTemporaryFile(
        mode='w',
        encoding='utf-8',
        dir=directory,
        prefix=os.path.basename(path) + '.',
        suffix='.tmp',
        delete=False,
    )
    tmp_path = tmp.name
    try:
        try:
            json.dump(data, tmp, indent=indent)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp_path, path)
    except Exception:
        # Leave the original file alone; remove the temp.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json_safe(path, data: Any, *, indent: int = 2) -> bool:
    """Like :func:`atomic_write_json` but swallows and logs errors.

    Returns ``True`` on success, ``False`` if anything went wrong (an error
    is logged). Intended for state-persistence call sites that should not
    propagate I/O failures.
    """
    try:
        atomic_write_json(path, data, indent=indent)
        return True
    except Exception as e:
        logger.error(f"Atomic write to {path} failed: {e}")
        return False
