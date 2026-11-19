"""VPN route probe, interface classifier and change watcher.

Stub: implemented in Phase 04.
"""

from __future__ import annotations

from vpn_monitor.model import VpnReading


def read_vpn_state() -> VpnReading:
    """Probe the kernel routing table once; any failure must give an UNKNOWN reading."""
    raise NotImplementedError("vpn.read_vpn_state: Phase 04")
