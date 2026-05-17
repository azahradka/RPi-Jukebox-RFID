# -*- coding: utf-8 -*-
"""Player coordination primitive (Phase 2).

Centralises the cross-backend handoff that previously lived in three
copies inside the MPD / Spotify / podcast player ``__init__`` files,
each poking the ``_active_player`` module global directly.

The :class:`PlayerCoordinator` owns:

* **Backend registry** — every player backend (``mpd``, ``spotify``,
  ``podcast``) registers a name plus its ``pause_fn`` / ``stop_fn``
  at plugin init.
* **Active backend bookkeeping** — a single string (or ``None``)
  protected by a lock. Replaces the leaky ``_active_player`` module
  global.
* **Activation handoff** — :meth:`activate` pauses the previous
  backend (so resume position is preserved), then stops it, then
  atomically sets the new active backend. Stop is bounded by a
  5 s timeout: if it blocks (Spotify Web API hiccup, MPD wire
  stall), we log an ERROR and proceed. The show must go on.

Status publishers gate on ``coordinator.current() == self.name``
instead of the prior ``get_active_player() == 'mpd'`` pattern.
The semantics are unchanged; the racy module global is gone.

Activation vs. passive control (Phase 3a decision)
--------------------------------------------------

Backends decide which of their RPCs constitute *activation events*.
The rule pinned by Phase 3a, applied uniformly across backends:

  **Activation events** -- RPCs that start, restart, or resume a
  playback session. Every such RPC MUST call ``coordinator.activate()``
  so handoff (pause-then-stop of the outgoing backend) runs before
  the new playback begins. In ``playermpd``: ``play``, ``play_single``,
  ``resume``, ``play_folder``, ``play_album``, and transitively
  ``play_card`` (via ``play_folder``). ``replay`` /
  ``replay_if_stopped`` also delegate to ``play_folder``, so they
  inherit activation.

  **Passive controls** -- RPCs that *modify* an already-playing
  session without changing which backend owns it. They MUST NOT call
  ``activate()``. In ``playermpd``: ``shuffle``, ``repeat``,
  ``volume`` (set / mute), ``seek`` / ``seekcur``, ``next`` /
  ``prev`` / ``stop`` / ``pause`` / ``toggle``. The rationale is
  asymmetric: if the user has already handed off to a different
  backend, re-claiming on a passive op would *steal* playback
  silently. The only safe re-claim point is one initiated by the
  user (a play/resume RPC, an RFID swipe).

  **Edge case**: ``next`` / ``prev`` look like activation (they start
  audible playback) but they only re-acquire the wire mutex; the
  *active backend* is whatever the coordinator says. If MPD is
  inactive and the user calls ``next``, the call goes to MPD's
  wire but Spotify (or whoever is current) keeps producing audio.
  This is preserved Phase 2 behaviour and matches the long-standing
  UI contract: "next" on MPD's controls advances MPD's queue, even
  if it's not the audible backend.

This rule is also documented at the top of
``components.playermpd/__init__.py``; podcast and Spotify backends
have their own per-backend application of the same principle.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import Callable, Dict, Iterator, NamedTuple, Optional


logger = logging.getLogger('jb.player.coordinator')


#: Default timeout (seconds) for the outgoing backend's ``stop_fn`` during
#: handoff. If the stop call exceeds this we log and proceed — the new
#: backend's activation must not be held hostage by a wedged peer.
STOP_TIMEOUT_SECONDS = 5.0


class _Backend(NamedTuple):
    """A registered player backend.

    Holds the callables used during handoff. Both must be callable with
    no arguments and may raise — the coordinator catches and logs.
    """
    name: str
    stop_fn: Callable[[], None]
    pause_fn: Callable[[], None]


class PlayerCoordinator:
    """Single source of truth for which player backend is active.

    Thread-safe. All mutations of the active-backend name go through
    :meth:`activate` under a single lock; readers use :meth:`current`.

    The coordinator does not own playback. Backends still drive their
    own state machines. The coordinator only enforces the invariant
    that *one and only one* backend is "active" at any moment, and
    that handoff between two backends pauses-then-stops the outgoing
    one before the incoming one starts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backends: Dict[str, _Backend] = {}
        self._current: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        stop_fn: Callable[[], None],
        pause_fn: Callable[[], None],
    ) -> None:
        """Register a backend with its handoff callbacks.

        The first backend to register becomes the initial active player
        (mirroring the prior ``_active_player = 'mpd'`` module-global
        default — daemon.py loads ``playermpd`` first). Re-registering
        the same name replaces its callbacks but leaves ``current()``
        untouched.
        """
        with self._lock:
            self._backends[name] = _Backend(name=name, stop_fn=stop_fn, pause_fn=pause_fn)
            if self._current is None:
                self._current = name
                logger.info(f"Coordinator: initial active backend = {name}")
            else:
                logger.debug(f"Coordinator: registered backend {name}")

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------
    def current(self) -> Optional[str]:
        """Return the name of the active backend, or ``None`` if none.

        Atomic read — safe to call from any thread, including status
        publisher loops that gate on the result.
        """
        with self._lock:
            return self._current

    # ------------------------------------------------------------------
    # Handoff
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def activate(self, name: str) -> Iterator[None]:
        """Hand off to backend ``name``.

        Context manager so callers can group "activation + first
        playback command" if desired::

            with coordinator.activate('spotify'):
                self.sp_client.start_playback(...)

        Semantics on enter:

        1. If ``name`` is already current → no-op (idempotent).
        2. Otherwise: invoke the outgoing backend's ``pause_fn``
           (preserves resume position), then its ``stop_fn`` with a
           ``STOP_TIMEOUT_SECONDS`` bound. Errors and timeouts are
           logged; we always proceed to set the new active backend.
        3. Atomically swap ``_current`` to ``name``.

        Exit is currently a no-op (the context-manager shape is
        forward-compatible with Phase 3 where exit may emit a publish
        message). If the body raises, the active backend stays set —
        cleanup is the body's responsibility.
        """
        self._activate_impl(name)
        try:
            yield
        finally:
            # Forward-compatible: Phase 3 may post-process here.
            pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _activate_impl(self, name: str) -> None:
        # Snapshot the outgoing backend (if any) under the lock so we
        # can run pause/stop *without* holding the lock — those callbacks
        # may take seconds and must not block ``current()`` readers.
        with self._lock:
            if name not in self._backends:
                # Allow activation of an unregistered name; the previous
                # API permitted set_active_player('mpd') before MPD's
                # plugin had registered. Tests rely on this. Log so it's
                # visible, then proceed with the swap.
                logger.debug(f"Coordinator: activating unregistered backend {name!r}")
            if self._current == name:
                # Idempotent — no handoff work.
                return
            outgoing_name = self._current
            outgoing = self._backends.get(outgoing_name) if outgoing_name else None

        # Pause first so the outgoing backend can persist its resume
        # position before being stopped. Both calls run with the
        # coordinator lock released.
        if outgoing is not None:
            self._call_pause(outgoing)
            self._call_stop_with_timeout(outgoing)

        with self._lock:
            self._current = name
        logger.info(f"Coordinator: active backend = {name}")

    @staticmethod
    def _call_pause(backend: _Backend) -> None:
        try:
            backend.pause_fn()
        except Exception as e:
            logger.error(
                f"Coordinator: pause_fn for {backend.name!r} raised "
                f"{e.__class__.__name__}: {e}"
            )

    @staticmethod
    def _call_stop_with_timeout(backend: _Backend) -> None:
        """Run ``backend.stop_fn`` on a worker thread; cap at the timeout.

        On timeout, log an ERROR and proceed — the handoff must not
        hang. The worker thread is daemonised so a wedged stop_fn
        does not prevent process shutdown.
        """
        result: Dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                backend.stop_fn()
            except BaseException as e:  # noqa: BLE001  (broad: log everything)
                result['error'] = e

        worker = threading.Thread(
            target=_runner,
            name=f'coordinator-stop-{backend.name}',
            daemon=True,
        )
        worker.start()
        worker.join(timeout=STOP_TIMEOUT_SECONDS)

        if worker.is_alive():
            logger.error(
                f"Coordinator: stop_fn for {backend.name!r} exceeded "
                f"{STOP_TIMEOUT_SECONDS:.0f}s timeout; proceeding anyway"
            )
            return
        err = result.get('error')
        if err is not None:
            logger.error(
                f"Coordinator: stop_fn for {backend.name!r} raised "
                f"{err.__class__.__name__}: {err}"
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
# Three player backends + status publishers all need to reach the same
# coordinator; a module-level singleton keeps the import surface flat
# (matches the existing ``components.player.get_active_player`` shape).
_coordinator = PlayerCoordinator()


def get_coordinator() -> PlayerCoordinator:
    """Return the process-wide :class:`PlayerCoordinator` singleton."""
    return _coordinator
