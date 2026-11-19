"""Scripted fakes implementing the source and sink Protocols, for tests (no I/O, no GLib)."""

from __future__ import annotations

from collections.abc import Sequence

from vpn_monitor.model import (
    Decision,
    FocusCallback,
    FocusEvent,
    VpnCallback,
    VpnReading,
)


class FakeFocusSource:
    """Scripted focus events: the first on ``start``, the rest via ``emit_next``."""

    def __init__(self, events: Sequence[FocusEvent] = ()) -> None:
        self._pending = list(events)
        self._callback: FocusCallback | None = None
        self.started = False
        self.stopped = False

    def start(self, callback: FocusCallback) -> None:
        self._callback = callback
        self.started = True
        if self._pending:
            callback(self._pending.pop(0))

    def stop(self) -> None:
        self._callback = None
        self.stopped = True

    def emit(self, event: FocusEvent) -> None:
        """Deliver ``event`` now (no effect if not started)."""
        if self._callback is not None:
            self._callback(event)

    def emit_next(self) -> bool:
        """Deliver the next scripted event; return False when the script is exhausted."""
        if not self._pending:
            return False
        self.emit(self._pending.pop(0))
        return True


class FakeVpnSource:
    """Delivers scripted VPN readings; records ``set_active`` calls."""

    def __init__(self, readings: Sequence[VpnReading] = ()) -> None:
        self._pending = list(readings)
        self._callback: VpnCallback | None = None
        self.active = False
        self.active_history: list[bool] = []
        self.started = False
        self.stopped = False

    def start(self, callback: VpnCallback) -> None:
        self._callback = callback
        self.started = True
        if self._pending:
            callback(self._pending.pop(0))

    def stop(self) -> None:
        self._callback = None
        self.stopped = True

    def set_active(self, active: bool) -> None:
        self.active = active
        self.active_history.append(active)

    def emit(self, reading: VpnReading) -> None:
        """Deliver ``reading`` now (no effect if not started)."""
        if self._callback is not None:
            self._callback(reading)

    def emit_next(self) -> bool:
        """Deliver the next scripted reading; return False when the script is exhausted."""
        if not self._pending:
            return False
        self.emit(self._pending.pop(0))
        return True


class RecordingSink:
    """Records every applied Decision."""

    def __init__(self) -> None:
        self.decisions: list[Decision] = []
        self.closed = False

    def apply(self, decision: Decision) -> None:
        self.decisions.append(decision)

    def close(self) -> None:
        self.closed = True

    @property
    def last(self) -> Decision | None:
        """The most recent Decision, or None."""
        return self.decisions[-1] if self.decisions else None
