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
import enum
import json
import logging
import os
import threading
from typing import Any, Dict, Optional

from jukebox.utils.atomic_io import atomic_write_json_safe


logger = logging.getLogger('jb.PlayerMPD.state_store')


class SwipeDecision(enum.Enum):
    """Result of the play_card swipe-decision seam.

    Returned by :func:`decide_swipe` and consumed by
    :meth:`PlayerMPD.play_card`. Encodes the *intent* of the swipe so the
    caller can dispatch to ``play_folder`` (FIRST) or the configured
    ``second_swipe_action`` (SECOND_TOGGLE) without re-deriving the rule.
    """

    #: Treat as a fresh swipe — call ``play_folder``.
    FIRST = 'first'
    #: Treat as a repeat swipe of the same card — call the configured
    #: ``second_swipe_action`` (pause/toggle/replay/...).
    SECOND_TOGGLE = 'second_toggle'


def decide_swipe(
    state_store: 'MPDStateStore',
    folder: str,
    second_swipe_action: Optional[Any] = None,
) -> SwipeDecision:
    """Decide whether ``folder`` is a first or second swipe.

    This is the *pure decision* extracted from :meth:`PlayerMPD.play_card`
    (Phase 3a). It reads ``last_swiped_folder`` from ``state_store`` and
    compares against the incoming ``folder``. It does **not** mutate the
    store — ``play_card`` updates the swipe marker after consulting this
    function so the decision is observable in isolation.

    Decision rule (regression-locked by ``test_decide_swipe.py``):

    * ``last_swiped_folder`` is empty (fresh boot, or after
      ``clear_last_swiped_folder``) → FIRST.
    * ``last_swiped_folder`` differs from ``folder`` (user swiped a
      different card) → FIRST.
    * ``last_swiped_folder == folder`` AND ``second_swipe_action`` is
      configured → SECOND_TOGGLE.
    * ``last_swiped_folder == folder`` AND ``second_swipe_action`` is
      ``None`` (feature disabled) → FIRST.

    The post-reboot scenario falls out of the first bullet: the store
    clears ``last_swiped_folder`` on init (see
    :meth:`MPDStateStore.clear_last_swiped_folder` and ``PlayerMPD.__init__``)
    so the first swipe after reboot is always FIRST, even if the card
    happens to match ``last_played_folder``.

    :param state_store: Live :class:`MPDStateStore` whose
        ``last_swiped_folder()`` is the discriminator.
    :param folder: The folder being swiped (an RFID payload).
    :param second_swipe_action: Whatever ``PlayerMPD.second_swipe_action``
        is — only its truthiness matters here. ``None`` (feature disabled)
        forces FIRST on every swipe.
    :returns: :class:`SwipeDecision`.
    """
    last_swiped = state_store.last_swiped_folder()
    if not last_swiped or last_swiped != folder:
        return SwipeDecision.FIRST
    if second_swipe_action is None:
        return SwipeDecision.FIRST
    return SwipeDecision.SECOND_TOGGLE


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

    # ------------------------------------------------------------------
    # Poll-thread merge (Phase 3a follow-up — reviewer ask #2)
    # ------------------------------------------------------------------
    def apply_poll(
        self,
        new_status: Dict[str, Any],
        new_song: Dict[str, Any],
        mpd_status_buffer: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Merge a single MPD poll cycle into the store under ``state_lock``.

        Extracted from ``PlayerMPD._mpd_status_poll`` so the dict-merge
        rules (which fields propagate to ``player_status`` vs.
        ``current_folder_status``, when to clear ``volume``, etc.) can be
        regression-tested without booting MPD or the plugin system.

        The buffer (``mpd_status_buffer``) is the running snapshot kept
        on ``PlayerMPD`` as ``self.mpd_status``. It is mutated in place
        rather than re-allocated so the publish-side `dict(self.mpd_status)`
        copy semantic is preserved. The buffer is passed in (rather than
        owned by the store) so callers that don't need the published-
        snapshot side channel — like unit tests — can supply a throwaway
        ``{}`` and still get the store mutations.

        :param new_status: Output of ``MPDClient.status()`` (may be empty).
        :param new_song: Output of ``MPDClient.currentsong()`` (may be
            empty if MPD has no current song).
        :param mpd_status_buffer: The running buffer to merge into.
            Mutated in place. The post-merge contents are returned as a
            copy for publish-side use.
        :returns: A copy of ``mpd_status_buffer`` after merge, suitable
            for handing to the publisher. (Done as a copy under the lock
            so the publisher sees a consistent snapshot.)
        """
        with self.state_lock:
            mpd_status_buffer.update(new_status)
            mpd_status_buffer.update(new_song)

            if mpd_status_buffer.get('elapsed') is not None:
                self.current_folder_status["ELAPSED"] = mpd_status_buffer['elapsed']
                self.music_player_status['player_status']["CURRENTSONGPOS"] = mpd_status_buffer['song']
                self.music_player_status['player_status']["CURRENTFILENAME"] = mpd_status_buffer['file']

            if mpd_status_buffer.get('file') is not None:
                self.current_folder_status["CURRENTFILENAME"] = mpd_status_buffer['file']
                self.current_folder_status["CURRENTSONGPOS"] = mpd_status_buffer['song']
                self.current_folder_status["ELAPSED"] = mpd_status_buffer.get('elapsed', '0.0')
                self.current_folder_status["PLAYSTATUS"] = mpd_status_buffer['state']
                self.current_folder_status["RESUME"] = "OFF"
                self.current_folder_status["SHUFFLE"] = "OFF"
                self.current_folder_status["LOOP"] = "OFF"
                self.current_folder_status["SINGLE"] = "OFF"

            # Volume is published via the 'volume' component — drop it
            # from the buffer so we don't double-publish.
            mpd_status_buffer.pop('volume', None)

            return dict(mpd_status_buffer)
