"""GTK4 layer-shell glow bar, one per monitor (click-through).

Stub: implemented in Phase 06.
"""

from __future__ import annotations

from vpn_monitor.model import Decision


class GlowOverlay:
    """Renders Decisions as a glow bar. Implements the IndicatorSink Protocol."""

    def apply(self, decision: Decision) -> None:
        """Show, change or hide the bar."""
        raise NotImplementedError("GlowOverlay.apply: Phase 06")

    def close(self) -> None:
        """Remove all bars."""
        raise NotImplementedError("GlowOverlay.close: Phase 06")
