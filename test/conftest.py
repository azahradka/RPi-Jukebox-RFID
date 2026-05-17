# -*- coding: utf-8 -*-
"""
Top-level pytest configuration.

Shared fixtures for jukebox tests:
- ``fake_mpd_client``: in-memory stand-in for ``python-mpd2``'s ``MPDClient``.
- ``fake_plugs``: lightweight stand-in for ``jukebox.plugs`` that captures
  registered functions and routes ``call()`` lookups.
- ``tmp_state_dir``: ``tmp_path``-derived directory for JSON state file tests.

Subdirectory conftests (e.g. ``test/components/playerpodcast/conftest.py``)
that pre-mock ``jukebox.plugs`` via ``sys.modules`` continue to work and take
precedence within their subtree.
"""

import json
import sys
from pathlib import Path

import pytest


# Make the jukebox source importable for tests that don't rely on the
# sys.modules pre-mock pattern used by player-specific conftests.
_JUKEBOX_SRC = Path(__file__).parent.parent / 'src' / 'jukebox'
if str(_JUKEBOX_SRC) not in sys.path:
    sys.path.insert(0, str(_JUKEBOX_SRC))


# ---------------------------------------------------------------------------
# FakeMPDClient
# ---------------------------------------------------------------------------


class FakeMPDClient:
    """In-memory stand-in for ``python-mpd2``'s ``MPDClient``.

    Implements the subset of the MPDClient API used by ``playermpd``:
    connection lifecycle, transport (play/stop/pause/next/previous/seek),
    playlist mutation (clear/add/addid), status/currentsong queries, and
    library queries (listall/list/find/findadd).

    All state is in-memory; no socket is opened. Volume, random, repeat
    and single are tracked but do not affect playback behavior.
    """

    def __init__(self):
        self.timeout = None
        self.idletimeout = None
        self.mpd_version = '0.23.5'
        self._connected = False
        self._playlist = []      # list[dict]: {'file', 'id', 'pos'}
        self._next_id = 1
        self._state = 'stop'     # 'play' | 'pause' | 'stop'
        self._pos = None         # int | None
        self._elapsed = 0.0
        self._volume = 100
        self._random = 0
        self._repeat = 0
        self._single = 0
        self._library = []       # list[str] of file paths
        self._db_updates = 0
        self.call_log = []       # list[(method, args, kwargs)]

    # connection
    def connect(self, host, port):
        self._connected = True
        self.call_log.append(('connect', (host, port), {}))

    def disconnect(self):
        self._connected = False
        self.call_log.append(('disconnect', (), {}))

    def ping(self):
        return 'OK' if self._connected else None

    # status
    def status(self):
        s = {
            'state': self._state,
            'volume': str(self._volume),
            'random': str(self._random),
            'repeat': str(self._repeat),
            'single': str(self._single),
            'playlistlength': str(len(self._playlist)),
            'elapsed': f'{self._elapsed:.3f}',
        }
        if self._pos is not None:
            s['pos'] = str(self._pos)
            s['song'] = str(self._pos)
        return s

    def currentsong(self):
        if self._pos is None or self._pos >= len(self._playlist):
            return {}
        return dict(self._playlist[self._pos])

    # playlist
    def clear(self):
        self._playlist = []
        self._pos = None
        self._state = 'stop'
        self._elapsed = 0.0
        self.call_log.append(('clear', (), {}))

    def add(self, uri):
        entry = {'file': uri, 'id': str(self._next_id), 'pos': str(len(self._playlist))}
        self._next_id += 1
        self._playlist.append(entry)
        self.call_log.append(('add', (uri,), {}))

    def addid(self, uri, pos=None):
        sid = str(self._next_id)
        self._next_id += 1
        entry = {'file': uri, 'id': sid, 'pos': str(len(self._playlist))}
        self._playlist.append(entry)
        self.call_log.append(('addid', (uri, pos), {}))
        return sid

    # transport
    def play(self, pos=None):
        if pos is not None:
            self._pos = int(pos)
        elif self._pos is None and self._playlist:
            self._pos = 0
        if self._pos is not None:
            self._state = 'play'
        self.call_log.append(('play', (pos,), {}))

    def stop(self):
        self._state = 'stop'
        self._elapsed = 0.0
        self.call_log.append(('stop', (), {}))

    def pause(self, state=None):
        if state is None:
            self._state = 'pause' if self._state == 'play' else 'play'
        else:
            self._state = 'pause' if int(state) else 'play'
        self.call_log.append(('pause', (state,), {}))

    def next(self):
        if self._pos is not None and self._pos + 1 < len(self._playlist):
            self._pos += 1
            self._elapsed = 0.0
        self.call_log.append(('next', (), {}))

    def previous(self):
        if self._pos is not None and self._pos > 0:
            self._pos -= 1
            self._elapsed = 0.0
        self.call_log.append(('previous', (), {}))

    def seek(self, songpos, time):
        self._pos = int(songpos)
        self._elapsed = float(time)
        self.call_log.append(('seek', (songpos, time), {}))

    def seekcur(self, time):
        self._elapsed = float(time)
        self.call_log.append(('seekcur', (time,), {}))

    # mixer / modes
    def setvol(self, vol):
        self._volume = int(vol)

    def random(self, val):
        self._random = int(val)

    def repeat(self, val):
        self._repeat = int(val)

    def single(self, val):
        self._single = int(val)

    # database
    def update(self, uri=None):
        self._db_updates += 1
        return str(self._db_updates)

    def playlistinfo(self):
        return [dict(p) for p in self._playlist]

    def listall(self, uri=None):
        prefix = uri or ''
        return [{'file': f} for f in self._library if f.startswith(prefix)]

    def list(self, *args):
        return []

    def find(self, *args):
        return []

    def findadd(self, *args):
        # Treat as add-of-everything for testing; pull from library.
        for f in self._library:
            self.add(f)
        return None

    # idle (used by some helpers; no-op in tests)
    def idle(self, *args):
        return []

    def noidle(self):
        return None

    # test helpers (not part of MPDClient API)
    def _seed_library(self, files):
        """Populate the library so list/find/listall/findadd return results."""
        self._library = list(files)

    def _seed_playlist(self, files):
        """Populate the current playlist directly without going through add()."""
        self.clear()
        for f in files:
            self.add(f)


@pytest.fixture
def fake_mpd_client():
    """Provide a fresh ``FakeMPDClient`` per test."""
    return FakeMPDClient()


# ---------------------------------------------------------------------------
# FakePlugs
# ---------------------------------------------------------------------------


class FakePlugs:
    """Lightweight stand-in for ``jukebox.plugs``.

    Captures registered functions in a ``registry`` keyed by
    ``package.plugin.method`` and routes ``.call()`` lookups against it.
    Decorators (``register``, ``initialize``, ``atexit``, ``tag``) are no-op
    pass-throughs so importing modules under test does not raise.

    Useful when a test needs to *assert* what the plugin code registered,
    rather than only that it could be imported.
    """

    def __init__(self):
        self.registry = {}
        self.call_log = []

    def register(self, f=None, *, name=None, package=None, **kwargs):
        def _wrap(fn):
            key_name = name or getattr(fn, '__name__', 'anonymous')
            pkg = package or fn.__module__.split('.')[-1]
            self.registry[f'{pkg}.{key_name}'] = fn
            return fn
        if f is None or not callable(f):
            return _wrap
        return _wrap(f)

    def initialize(self, f):
        return f

    def atexit(self, f):
        return f

    def tag(self, f):
        return f

    def call(self, package, plugin=None, method=None, *, args=(), kwargs=None):
        key = '.'.join(p for p in (package, plugin, method) if p)
        self.call_log.append((key, tuple(args), dict(kwargs or {})))
        fn = self.registry.get(key)
        if fn is None:
            return None
        return fn(*args, **(kwargs or {}))

    def call_ignore_errors(self, package, plugin=None, method=None, *, args=(), kwargs=None):
        try:
            return self.call(package, plugin, method, args=args, kwargs=kwargs)
        except Exception:
            return None

    def reset(self):
        self.registry.clear()
        self.call_log.clear()


@pytest.fixture
def fake_plugs():
    """Provide a fresh ``FakePlugs`` per test."""
    return FakePlugs()


# ---------------------------------------------------------------------------
# tmp_state_dir
# ---------------------------------------------------------------------------


class _StateDir:
    """``Path``-like wrapper that adds a ``read_json(name)`` helper."""

    def __init__(self, path):
        self.path = Path(path)

    def __truediv__(self, other):
        return self.path / other

    def __fspath__(self):
        return str(self.path)

    def __str__(self):
        return str(self.path)

    def __repr__(self):
        return f'_StateDir({self.path!r})'

    def read_json(self, name):
        with open(self.path / name) as f:
            return json.load(f)


@pytest.fixture
def tmp_state_dir(tmp_path):
    """A per-test directory for JSON state files.

    Returns a ``_StateDir`` rooted at ``tmp_path / 'state'`` (created).
    Supports ``/`` joining like ``Path``, plus a ``read_json(name)``
    helper for assertions.
    """
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    return _StateDir(state_dir)
