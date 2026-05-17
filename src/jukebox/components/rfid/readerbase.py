import inspect
import os
import logging
import threading
import time
from abc import ABC, abstractmethod


class ReaderBaseClass(ABC):
    """
    Abstract Base Class for all Reader Classes to ensure common API

    Look at template_new_reader.py for documentation how to integrate a new RFID reader

    Phase 6: ``read_card()`` is allowed to block indefinitely (the
    common case for hardware readers waiting for an IRQ). To give
    operators visibility that the reader thread is alive — rather than
    silently hung — :class:`ReaderBaseClass` runs a heartbeat
    watchdog that periodically logs a debug message while
    ``read_card()`` is blocked beyond ``wait_for_tag_timeout_s``.

    The timeout is configurable via ``rfid.wait_for_tag_timeout_s`` in
    ``jukebox.yaml`` (validated by the rfid plugin schema). The default
    is :attr:`WAIT_TIMEOUT_DEFAULT_S` (30s). The watchdog only logs —
    it never interrupts ``read_card()`` — so existing driver
    implementations are unaffected. To wire the watchdog, drivers
    should bracket their blocking call with
    :meth:`_heartbeat_active` (or use the
    :meth:`read_card_with_heartbeat` helper).
    """

    #: Default heartbeat / "still waiting" log interval (seconds).
    #: Configurable via ``rfid.wait_for_tag_timeout_s`` in jukebox.yaml.
    WAIT_TIMEOUT_DEFAULT_S = 30.0

    def __init__(self, reader_cfg_key: str, description: str, logger: logging.Logger,
                 wait_for_tag_timeout_s: float = WAIT_TIMEOUT_DEFAULT_S):
        super().__init__()
        self.logger = logger
        self.description = description
        self.wait_for_tag_timeout_s = max(1.0, float(wait_for_tag_timeout_s))
        # Get the filename of the module that uses ReaderBaseClass (i.e. derives from it)
        callee_filename = os.path.normpath(inspect.stack()[1].filename)
        logger.info(f"Initializing reader '{self.description}' from '{callee_filename}'")
        logger.debug(f"Reader object is {self} for reader config key '{reader_cfg_key}'")
        logger.info(
            f"Reader '{self.description}' heartbeat interval: "
            f"{self.wait_for_tag_timeout_s:.1f}s"
        )

        # Heartbeat state
        self._heartbeat_lock = threading.Lock()
        self._heartbeat_active_flag = False
        self._heartbeat_started_at = 0.0
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = None

    def __enter__(self):
        # Start the heartbeat thread on enter so drivers that opt in via
        # _heartbeat_active() get the periodic "still waiting" log.
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"{self.description}Heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.logger.debug("Exiting")
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None
        self.cleanup()

    def __iter__(self):
        return self

    def __next__(self):
        with self._heartbeat_active():
            return self.read_card()

    def _heartbeat_active(self):
        """Context manager: mark ``read_card()`` as currently blocking.

        Drivers usually don't need this — :meth:`__next__` wraps each
        ``read_card()`` call already. Drivers that have their own
        loop should use this to bracket the blocking section.
        """
        return _HeartbeatActiveScope(self)

    def _heartbeat_loop(self):
        """Background thread that emits a debug log while read_card
        has been blocked beyond ``wait_for_tag_timeout_s``.

        Logs at most once per interval; uses self.logger.debug so the
        log isn't noisy at INFO level — but operators chasing a hung
        reader can flip the rfid logger to DEBUG to see proof of life.
        """
        while not self._heartbeat_stop.wait(timeout=self.wait_for_tag_timeout_s):
            with self._heartbeat_lock:
                if not self._heartbeat_active_flag:
                    continue
                elapsed = time.monotonic() - self._heartbeat_started_at
            self.logger.debug(
                f"Reader '{self.description}' still waiting for tag "
                f"({elapsed:.1f}s elapsed)"
            )

    @abstractmethod
    def read_card(self):
        pass

    @abstractmethod
    def cleanup(self):
        pass

    @abstractmethod
    def stop(self):
        pass


class _HeartbeatActiveScope:
    """Internal context manager for :meth:`ReaderBaseClass._heartbeat_active`."""

    def __init__(self, reader):
        self._reader = reader

    def __enter__(self):
        with self._reader._heartbeat_lock:
            self._reader._heartbeat_active_flag = True
            self._reader._heartbeat_started_at = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        with self._reader._heartbeat_lock:
            self._reader._heartbeat_active_flag = False
        return False
