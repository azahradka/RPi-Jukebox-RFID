# -*- coding: utf-8 -*-
"""Connection + locking wrapper for :mod:`python-mpd2` (Phase 3a).

Splits two previously interleaved concerns out of
``components.playermpd/__init__.py``:

* **The wire-level mutex** (``mpd_lock``, an ``RLock``): serialises
  access to the MPD socket. python-mpd2 is not thread-safe; the wrapper
  re-acquires the connection lazily inside ``__enter__`` so a transient
  disconnect doesn't break subsequent calls.
* **Retry + error-swallow on connection failure**: the prior helper
  ``mpd_retry_with_mutex`` lived as a method on PlayerMPD; here it
  becomes ``call_with_retry`` on the wrapper.

The wrapper is intentionally *thin* — methods that mutate playback or
read status still go through the underlying ``mpd_client`` directly
(``self.client``), letting the existing playermpd call sites keep
their shape. What's new is that:

  - the lock has a single, named owner;
  - the retry logic is unit-testable in isolation;
  - tests can swap in a ``FakeMPDClient`` without monkey-patching
    PlayerMPD's whole import chain.

Use the wrapper as a context manager to acquire the mutex (and lazily
reconnect)::

    with self.mpd_wrapper:
        self.mpd_wrapper.client.play()

Or use the retry helper::

    self.mpd_wrapper.call_with_retry(self.mpd_wrapper.client.status)
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

try:  # ``mpd`` is a heavy dependency that tests stub out.
    import mpd
    _MPD_CONNECTION_ERROR = mpd.base.ConnectionError
except Exception:  # pragma: no cover - test-only path
    mpd = None  # type: ignore[assignment]
    _MPD_CONNECTION_ERROR = ConnectionError


logger = logging.getLogger('jb.PlayerMPD.mpd_client')


class MPDClientWrapper:
    """Owns the python-mpd2 client + its access mutex.

    Replaces the old ``MpdLock`` context-manager. Differences:

    * Holds the underlying ``mpd.MPDClient`` directly (no longer a
      separate attribute on PlayerMPD), so the connection lifecycle
      and the lock have a single owner.
    * Adds :meth:`call_with_retry` so the prior ``mpd_retry_with_mutex``
      helper on PlayerMPD can be a thin pass-through.

    Semantics preserved from ``MpdLock``:

    * Re-entrancy via ``RLock`` (the prev code took the lock recursively
      inside ``play_folder`` → ``addid``).
    * Lazy reconnect: each ``__enter__`` (and ``acquire()``) calls
      ``_try_connect`` so a transient socket loss self-heals.
    """

    def __init__(self, client: Any, host: str, port: int) -> None:
        self.client = client
        self.host = host
        self.port = port
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------
    def _try_connect(self) -> None:
        """Connect; swallow the "already connected" ConnectionError.

        python-mpd2 raises ``ConnectionError`` if you call ``connect``
        on an already-open socket. The old code suppressed that case
        (only that case), and we preserve the exact behaviour — any
        other error propagates so callers can log/handle.
        """
        try:
            self.client.connect(self.host, self.port)
        except _MPD_CONNECTION_ERROR:
            pass

    def connect(self) -> None:
        """Open the connection unconditionally; used at PlayerMPD __init__."""
        self.client.connect(self.host, self.port)

    def disconnect(self) -> None:
        """Close the connection; used at PlayerMPD exit."""
        self.client.disconnect()

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------
    def __enter__(self) -> 'MPDClientWrapper':
        self._lock.acquire()
        self._try_connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._lock.release()

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        locked = self._lock.acquire(blocking, timeout)
        if locked:
            self._try_connect()
        return locked

    def release(self) -> None:
        self._lock.release()

    def locked(self) -> bool:
        # RLock has no public ``locked()``. Use the same shim as before.
        # ``_count`` is an implementation detail but it's what the prior
        # ``MpdLock.locked()`` returned semantically.
        return getattr(self._lock, '_count', 0) > 0 or self._lock_is_held_fallback()

    def _lock_is_held_fallback(self) -> bool:
        """Best-effort: try non-blocking acquire; if it succeeds, nobody
        held the lock — release immediately and return False."""
        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self._lock.release()
            return False
        return True

    # ------------------------------------------------------------------
    # Retry helper
    # ------------------------------------------------------------------
    def call_with_retry(self, mpd_cmd: Callable[..., Any], *args: Any) -> Any:
        """Acquire the lock, call ``mpd_cmd(*args)``, swallow & log errors.

        Returns the command's result on success, ``None`` on failure.

        Mirrors the prior ``mpd_retry_with_mutex`` method on PlayerMPD
        exactly — the name was misleading (there's no actual retry loop,
        only a log-and-return-None on exception) but we keep the
        behaviour byte-for-byte and rename only the *method*. Callers
        treating ``None`` as "command failed" continue to work.
        """
        with self:
            try:
                return mpd_cmd(*args)
            except Exception as e:
                logger.error(f"{e.__class__.__qualname__}: {e}")
                return None
