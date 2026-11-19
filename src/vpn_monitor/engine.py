"""Pure state engine: focus + VPN reading -> Decision. No I/O, no clock (spec R2).

Stub: implemented in Phase 03. The shape follows the Phase 03 prompt: inputs arrive through the
``on_*`` methods, time is passed in to ``tick``, and a new :class:`Decision` is returned only
when it changed.
"""

from __future__ import annotations

from vpn_monitor.model import Decision, FocusEvent, MonitorInfo, VpnReading


class Engine:
    """Decides ``HIDDEN | RED | BLUE`` per monitor; unknown or stale input must give red."""

    def on_focus(self, event: FocusEvent) -> Decision | None:
        """Feed a focus change; return the new Decision if it changed."""
        raise NotImplementedError("Engine.on_focus: Phase 03")

    def on_vpn(self, reading: VpnReading) -> Decision | None:
        """Feed a VPN reading; return the new Decision if it changed."""
        raise NotImplementedError("Engine.on_vpn: Phase 03")

    def on_pause(self, paused: bool) -> Decision | None:
        """Pause or resume; return the new Decision if it changed."""
        raise NotImplementedError("Engine.on_pause: Phase 03")

    def on_monitors(self, monitors: list[MonitorInfo]) -> Decision | None:
        """Feed the monitor list; return the new Decision if it changed."""
        raise NotImplementedError("Engine.on_monitors: Phase 03")

    def tick(self, now: float) -> Decision | None:
        """Advance time (staleness checks); return the new Decision if it changed."""
        raise NotImplementedError("Engine.tick: Phase 03")
