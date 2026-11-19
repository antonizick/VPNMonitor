"""Hyprland socket2 focus watcher and initial-state query (titles are dropped).

Stub: implemented in Phase 05.
"""

from __future__ import annotations

from vpn_monitor.model import FocusEvent


def parse_event_line(line: str) -> FocusEvent | None:
    """Parse one socket2 line into a FocusEvent, dropping any window title."""
    raise NotImplementedError("focus.parse_event_line: Phase 05")
