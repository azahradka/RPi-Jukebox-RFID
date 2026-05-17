# -*- coding: utf-8 -*-
"""Persistent state store for :mod:`components.playermpd` (Phase 3a).

``PlayerMPD`` used to interleave three concerns in its 900-line
``__init__.py``: (1) holding the ``music_player_status`` dict with its
two sub-dicts (``player_status`` and ``audio_folder_status``), (2)
loading/saving that dict from a JSON file, and (3) guarding both
against concurrent mutation by the poll thread and RPC threads. This
module factors all three out into a single, testable class.

The store wraps a single ``state_lock`` (``threading.Lock``) — the same
lock previously owned by ``PlayerMPD`` — and exposes:

* ``music_player_status`` / ``current_folder_status`` for read access
  by the poll thread (locking is the caller's responsibility for the
  bulk-update path, mirroring how ``_mpd_status_poll`` worked before).
* Field-level helpers (``last_played_folder``, ``last_swiped_folder``,
  ``set_last_played_folder``, ``set_last_swiped_folder``,
  ``ensure_folder_entry``) that take the lock internally for the
  single-field read/write paths used by the play/swipe handlers.
* ``save()`` — snapshots under the lock and writes via
  :func:`jukebox.utils.atomic_io.atomic_write_json_safe`, so a crashed
  write never leaves a torn JSON file (Phase 1 fix #2 already used
  this helper inline; we keep using it via the same import).

The ``last_swiped_folder`` field (new in Phase 3a) is separate from
``last_played_folder`` and is what the second-swipe detection consults.
On startup we clear only ``last_swiped_folder`` — ``last_played_folder``
is preserved so a first swipe of the last-played card after reboot
still triggers playback instead of being misread as a second swipe.
See ``play_card`` for the user-visible behaviour.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from jukebox.utils.atomic_io import atomic_write_json_safe


logger = logging.getLogger('jb.PlayerMPD.state_store')


class MPDStateStore:
    """In-memory + on-disk state for the MPD player backend.

    The on-disk format mirrors what ``PlayerMPD`` used to write directly
    so existing ``shared/settings/`` JSON files keep loading::

        {
          "player_status": {
            "last_played_folder": "...",
            "last_swiped_folder": "...",  # NEW in Phase 3a
            "CURRENTSONGPOS": "0",
            "CURRENTFILENAME": "..."
          },
          "audio_folder_status": {
            "<folder>": {
              "ELAPSED": "...", "CURRENTFILENAME": "...",
              "CURRENTSONGPOS": "...", "PLAYSTATUS": "...",
              "RESUME": "OFF", "SHUFFLE": "OFF",
              "LOOP": "OFF", "SINGLE": "OFF"
            }, ...
          }
        }

    Older state files (without ``last_swiped_folder``) load cleanly:
    the field is treated as absent and second-swipe detection falls back
    to the empty string, which never matches a real folder path.
    """

    def __init__(self, status_file: str) -> None:
        self.status_file = status_file
        #: Single lock guarding all mutations of ``music_player_status``
        #: and the ``current_folder_status`` reference. Acquired by the
        #: poll thread for bulk updates; field helpers take it internally.
        self.state_lock = threading.Lock()
        self.music_player_status: Dict[str, Any] = self._load_from_disk()

        # Seed missing sub-dicts so callers can index without churn.
        if not self.music_player_status:
            self.music_player_status['player_status'] = {}
            self.music_player_status['audio_folder_status'] = {}
            self.save()
        else:
            # Defensive: tolerate partial files (manual edits, older
            # schema, etc.) without raising.
            self.music_player_status.setdefault('player_status', {})
            self.music_player_status.setdefault('audio_folder_status', {})

        #: The audio_folder_status entry for the currently-loaded folder.
        #: Held as a separate reference (not a property) so the poll
        #: thread can mutate it in-place; that's how the original code
        #: worked and we preserve the shape for callers that capture it.
        self.current_folder_status: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_from_disk(self) -> Dict[str, Any]:
        """Load state from ``status_file`` or return an empty dict.

        Mirrors the prior inline ``_load_state`` exactly: a missing or
        unreadable file becomes ``{}`` and is logged at ERROR level so
        the upstream caller can decide whether to re-seed.
        """
        if not os.path.exists(self.status_file):
            return {}
        try:
            with open(self.status_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load player status: {e}")
            return {}

    def save(self) -> bool:
        """Snapshot under lock and write atomically to ``status_file``.

        Returns ``True`` on success, ``False`` on I/O failure (logged
        by :func:`atomic_write_json_safe`). Snapshotting under the lock
        is what gives the on-disk payload its consistency — even if the
        poll thread is mid-update we serialise a clean view.
        """
        with self.state_lock:
            snapshot = copy.deepcopy(self.music_player_status)
        return atomic_write_json_safe(self.status_file, snapshot)

    # ------------------------------------------------------------------
    # Field-level accessors (lock internally)
    # ------------------------------------------------------------------
    @property
    def player_status(self) -> Dict[str, Any]:
        """Direct reference to the ``player_status`` sub-dict.

        Callers that mutate it must hold ``state_lock`` themselves; the
        property exists for the poll-thread path where the lock is
        already held around a multi-field merge.
        """
        return self.music_player_status['player_status']

    @property
    def audio_folder_status(self) -> Dict[str, Dict[str, Any]]:
        """Direct reference to the ``audio_folder_status`` sub-dict."""
        return self.music_player_status['audio_folder_status']

    def last_played_folder(self) -> str:
        """Return ``last_played_folder`` (the resume target).

        Empty string if never set. Used by ``replay`` /
        ``replay_if_stopped`` to know what to re-play. **Not** consulted
        for second-swipe detection (that's ``last_swiped_folder``).
        """
        with self.state_lock:
            return self.music_player_status['player_status'].get('last_played_folder', '') or ''

    def set_last_played_folder(self, folder: str) -> None:
        """Set the resume target. Does not persist — caller calls ``save()``."""
        with self.state_lock:
            self.music_player_status['player_status']['last_played_folder'] = folder

    def last_swiped_folder(self) -> str:
        """Return ``last_swiped_folder`` — the folder *swiped* this session.

        Empty string if no swipe has happened since startup. This is what
        ``play_card`` consults to decide first vs. second swipe. The store
        clears it at startup (see ``clear_last_swiped_folder``) precisely
        so the first swipe after reboot never looks like a second swipe.
        """
        with self.state_lock:
            return self.music_player_status['player_status'].get('last_swiped_folder', '') or ''

    def set_last_swiped_folder(self, folder: str) -> None:
        """Record the most recently swiped folder."""
        with self.state_lock:
            self.music_player_status['player_status']['last_swiped_folder'] = folder

    def clear_last_swiped_folder(self) -> None:
        """Reset the swipe marker. Called at startup to prevent the
        post-reboot first swipe of the last-played card from being
        misclassified as a second swipe."""
        with self.state_lock:
            self.music_player_status['player_status']['last_swiped_folder'] = ''

    def ensure_folder_entry(self, folder: str) -> Dict[str, Any]:
        """Get (or create) the ``audio_folder_status`` entry for ``folder``.

        Returns the entry dict; callers may mutate it to record playback
        progress. Lock is held only across the get-or-create — subsequent
        mutations by the caller follow the normal poll-thread discipline
        (hold ``state_lock`` while mutating from outside the poll thread).
        """
        with self.state_lock:
            entry = self.music_player_status['audio_folder_status'].get(folder)
            if entry is None:
                entry = {}
                self.music_player_status['audio_folder_status'][folder] = entry
        return entry

    def get_folder_status(self, folder: str) -> Optional[Dict[str, Any]]:
        """Return the audio_folder_status entry for ``folder`` (or ``None``)."""
        with self.state_lock:
            return self.music_player_status['audio_folder_status'].get(folder)

    def set_current_folder_status(self, folder: str) -> Dict[str, Any]:
        """Point ``current_folder_status`` at ``folder``'s entry (creating it
        if missing) and return the entry. The caller takes ownership of
        further in-place mutations.
        """
        entry = self.ensure_folder_entry(folder)
        self.current_folder_status = entry
        return entry
