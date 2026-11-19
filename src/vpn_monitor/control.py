"""Unix control socket: daemon side and client (pause, resume, status).

Stub: implemented in Phase 07.
"""

from __future__ import annotations


def send_command(command: str) -> str:
    """Send ``command`` to the running daemon and return its reply."""
    raise NotImplementedError("control.send_command: Phase 07")
