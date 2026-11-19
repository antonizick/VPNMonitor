"""Human-readable log plus JSONL event log, with rotation and no window titles (R11).

Stub: implemented in Phase 03.
"""

from __future__ import annotations


def log_event(kind: str, **fields: str | int | float | bool) -> None:
    """Record one event with its inputs and reason in both logs."""
    raise NotImplementedError("eventlog.log_event: Phase 03")
