"""Shared types: the contract between every module (spec R2).

Everything here is a frozen dataclass or an enum, so values can be passed between the focus
watcher, the VPN detector, the engine and the overlay without copying or mutation.

Privacy (spec S1, ADR-0010): there is deliberately **no window title** field anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------------------------
# Focus
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """One output (monitor) known to the compositor."""

    name: str
    """Connector name as Hyprland reports it, for example ``DP-1``."""
    width: int
    """Logical width in pixels (after scaling)."""
    height: int
    """Logical height in pixels (after scaling)."""
    scale: float = 1.0
    """Output scale factor, for example ``1.6``."""
    focused: bool = False
    """True if this is the monitor with keyboard focus."""


@dataclass(frozen=True, slots=True)
class FocusEvent:
    """The focused window changed. Carries **no title** (spec S1)."""

    window_class: str
    """Window class / app id, for example ``brave-browser``. Empty if no window has focus."""
    address: str
    """Hyprland window address, for example ``0x5581a0c3f2d0``. Empty if no window has focus."""
    monitor: str
    """Name of the monitor the window is on. Empty if unknown."""
    fullscreen: bool = False
    """True if the window is fullscreen."""


# ---------------------------------------------------------------------------------------------
# VPN reading
# ---------------------------------------------------------------------------------------------


class VpnState(Enum):
    """Overall verdict of one VPN reading."""

    VPN = "vpn"
    """Every probed address family leaves through a VPN interface."""
    NO_VPN = "no_vpn"
    """At least one family leaves outside a VPN (a leak counts)."""
    UNKNOWN = "unknown"
    """The reading failed or is stale. Always rendered red (spec R4/S6)."""


class RouteKind(Enum):
    """What the kernel said about one probed destination."""

    ROUTED = "routed"
    BLOCKED = "blocked"
    """Routing explicitly blocks it (``blackhole`` / ``prohibit``): not a leak."""
    UNREACHABLE = "unreachable"
    """No route: not a leak, but not protected either."""
    ERROR = "error"
    """The probe itself failed; the family counts as unknown."""


@dataclass(frozen=True, slots=True)
class FamilyRoute:
    """The route a probe destination takes for one address family."""

    family: Literal[4, 6]
    """Address family: 4 or 6."""
    destination: str
    """Documentation-range probe destination used for the lookup. Nothing is ever sent to it."""
    egress_interface: str | None
    """Interface the kernel would use, or ``None`` if there is no route."""
    kind: RouteKind
    """Outcome of the route lookup."""
    is_vpn: bool
    """True if ``egress_interface`` is classified as a VPN (not merely a mesh like Tailscale)."""


@dataclass(frozen=True, slots=True)
class VpnReading:
    """One result from the VPN detector."""

    state: VpnState
    """Overall verdict."""
    routes: tuple[FamilyRoute, ...]
    """Per-family probe results; empty for an ``UNKNOWN`` reading with no data."""
    reason: str
    """Human-readable why, for the log (spec R11). Never contains window titles."""
    timestamp: float
    """When the reading was taken: injected ``boot_clock`` seconds (counts suspend; ADR-0019)."""


def reading_to_dict(reading: VpnReading) -> dict[str, Any]:
    """JSON-friendly form of a reading."""
    return {
        "state": reading.state.value,
        "reason": reading.reason,
        "routes": [
            {
                "family": r.family,
                "destination": r.destination,
                "interface": r.egress_interface,
                "kind": r.kind.value,
                "vpn": r.is_vpn,
            }
            for r in reading.routes
        ],
    }


# ---------------------------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------------------------


class Indicator(Enum):
    """What the overlay shows on a monitor."""

    HIDDEN = "hidden"
    RED = "red"
    BLUE = "blue"


@dataclass(frozen=True, slots=True)
class Decision:
    """The engine's verdict, consumed by the overlay and the log."""

    indicator: Indicator
    """What to show."""
    monitor: str
    """Monitor to show it on; empty when ``indicator`` is ``HIDDEN``."""
    reason: str
    """Why this indicator was chosen (spec R11)."""
    inputs: dict[str, str] = field(default_factory=dict, hash=False, compare=True)
    """Flat record of the inputs that led here (focus class, match result, reading state...)."""


# ---------------------------------------------------------------------------------------------
# Source and sink Protocols (ADR-0011: callback style)
# ---------------------------------------------------------------------------------------------

FocusCallback = Callable[[FocusEvent], None]
VpnCallback = Callable[[VpnReading], None]


@runtime_checkable
class FocusSource(Protocol):
    """Produces :class:`FocusEvent` values. Callbacks run on the GLib main loop thread."""

    def start(self, callback: FocusCallback) -> None:
        """Begin delivering focus events to ``callback``; also deliver the initial state."""
        ...

    def stop(self) -> None:
        """Stop delivering events and release resources. Safe to call twice."""
        ...


@runtime_checkable
class VpnSource(Protocol):
    """Produces :class:`VpnReading` values. Callbacks run on the GLib main loop thread."""

    def start(self, callback: VpnCallback) -> None:
        """Begin delivering readings to ``callback`` (event-driven plus periodic re-check)."""
        ...

    def stop(self) -> None:
        """Stop delivering readings and release resources. Safe to call twice."""
        ...

    def set_active(self, active: bool) -> None:
        """Enable or disable the periodic re-check (on only while a browser is focused)."""
        ...


@runtime_checkable
class IndicatorSink(Protocol):
    """Renders a :class:`Decision`. The overlay implements this."""

    def apply(self, decision: Decision) -> None:
        """Show, change or hide the indicator as ``decision`` says."""
        ...

    def close(self) -> None:
        """Remove all indicators and release resources. Safe to call twice."""
        ...
