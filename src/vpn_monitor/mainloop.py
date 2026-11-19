"""Thin scheduler abstraction over the GLib main loop (ADR-0012).

I/O modules (the VPN watcher now, the focus watcher and the control socket later) schedule timers
and watch file descriptors through :class:`Scheduler`, so they can be driven by a fake loop in tests
and by GLib in the daemon. ``gi`` is imported lazily inside :class:`GLibScheduler` only, so the rest
of the package (and CI without PyGObject) never needs it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

Handle = int
"""Opaque id of a scheduled timer or fd watch."""


def boot_clock() -> float:
    """Seconds since boot, **including** time spent suspended (Linux ``CLOCK_BOOTTIME``).

    The engine's staleness rule and every ``VpnReading.timestamp`` use this clock (ADR-0019).
    ``time.monotonic`` stops while the machine sleeps, so a VPN reading taken just before a
    suspend would still look seconds old after hours asleep and could keep a bar blue on resume.
    """
    return time.clock_gettime(time.CLOCK_BOOTTIME)


class Scheduler(Protocol):
    """Timers and fd watches, all delivered on one thread (the main loop)."""

    def call_later(self, delay_s: float, callback: Callable[[], None]) -> Handle:
        """Run ``callback`` once after ``delay_s`` seconds."""
        ...

    def watch_fd(self, fd: int, callback: Callable[[], bool]) -> Handle:
        """Call ``callback`` whenever ``fd`` is readable or hung up; it returns False to stop."""
        ...

    def cancel(self, handle: Handle) -> None:
        """Cancel a timer or watch. Unknown or already-fired handles are ignored."""
        ...


class GLibScheduler:
    """:class:`Scheduler` on the default GLib main context."""

    def __init__(self) -> None:
        from gi.repository import GLib

        self._glib: Any = GLib
        try:  # PyGObject >= 3.52 moved the Unix fd source to GLibUnix
            from gi.repository import GLibUnix

            self._fd_add: Any = GLibUnix.fd_add_full
        except ImportError:  # pragma: no cover - older PyGObject
            self._fd_add = GLib.unix_fd_add_full
        self._live: set[Handle] = set()

    def call_later(self, delay_s: float, callback: Callable[[], None]) -> Handle:
        handle: Handle = 0

        def fire() -> bool:
            self._live.discard(handle)
            callback()
            return False  # one-shot

        handle = int(self._glib.timeout_add(max(0, round(delay_s * 1000)), fire))
        self._live.add(handle)
        return handle

    def watch_fd(self, fd: int, callback: Callable[[], bool]) -> Handle:
        glib = self._glib
        handle: Handle = 0
        conditions = glib.IOCondition.IN | glib.IOCondition.HUP | glib.IOCondition.ERR

        def ready(_fd: int, _condition: Any) -> bool:
            keep = callback()
            if not keep:
                self._live.discard(handle)
            return keep

        handle = int(self._fd_add(glib.PRIORITY_DEFAULT, fd, conditions, ready))
        self._live.add(handle)
        return handle

    def cancel(self, handle: Handle) -> None:
        if handle in self._live:
            self._live.discard(handle)
            self._glib.source_remove(handle)
