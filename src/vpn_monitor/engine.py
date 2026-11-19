"""Pure state engine: focus + VPN reading + pause + clock -> one Decision (spec R2, R4, S6).

No I/O and no direct clock access. Time is injected: the constructor takes a ``clock`` callable
(``time.monotonic`` in the daemon, a fake in tests), and ``tick(now)`` lets the caller advance time
explicitly. ``VpnReading.timestamp`` must come from the same monotonic clock.

There is one current :class:`Decision`. It names the monitor that shows the bar (the focused
window's monitor, spec R6), and every other monitor shows nothing. Every ``on_*`` method and
:meth:`Engine.tick` return the new Decision **only when it changed** (indicator, monitor or
reason), else ``None``; the daemon applies it to the overlay and logs it.

Rules, in order (the first that applies wins; ``docs/VPM_ARCHITECTURE.md`` has the table):

1. paused → HIDDEN
2. no window focused, or the focused window is not a browser → HIDDEN
3. fullscreen browser and ``show_on_fullscreen`` is off → HIDDEN
4. the browser's monitor cannot be resolved → HIDDEN
5. no reading, UNKNOWN, NO_VPN, stale, future-dated or self-contradicting reading → RED
6. a positive reading that has not yet held for ``blue_confirm_ms`` → RED
7. otherwise (fresh, consistent VPN reading) → BLUE

Invariant (S6, tested exhaustively): BLUE ⇒ browser focused ∧ not paused ∧ a fresh, consistent
``VpnState.VPN`` reading. Red is never delayed (ADR-0013).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from vpn_monitor.browsers import NO_MATCH, BrowserMatcher, MatchResult
from vpn_monitor.model import (
    Decision,
    FocusEvent,
    Indicator,
    MonitorInfo,
    RouteKind,
    VpnReading,
    VpnState,
)

if TYPE_CHECKING:
    from vpn_monitor.config import Config

FUTURE_TOLERANCE_S = 1.0
"""A reading dated more than this far in the future is treated as invalid (red)."""

Clock = Callable[[], float]

_INITIAL = Decision(indicator=Indicator.HIDDEN, monitor="", reason="starting")


def reading_problem(reading: VpnReading | None, now: float, max_age_s: float) -> str | None:
    """Return why ``reading`` cannot justify blue at ``now``, or ``None`` if it can.

    This is the single gate for blue. Defence in depth: besides ``state`` and age, the per-family
    routes must agree with a ``VPN`` verdict (spec R3): at least one family routed via a VPN, no
    family routed outside one, and no failed probe.
    """
    if reading is None:
        return "no VPN reading yet"
    if reading.state is VpnState.UNKNOWN:
        return "VPN state unknown"
    if reading.state is VpnState.NO_VPN:
        return "traffic is not routed through a VPN"
    age = now - reading.timestamp
    if math.isnan(age) or age < -FUTURE_TOLERANCE_S:
        return "VPN reading has an invalid timestamp"
    if age > max_age_s:
        return "VPN reading is stale"
    routes = reading.routes
    via_vpn = any(r.kind is RouteKind.ROUTED and r.is_vpn for r in routes)
    leaks = any(r.kind is RouteKind.ROUTED and not r.is_vpn for r in routes)
    failed = any(r.kind is RouteKind.ERROR for r in routes)
    if not via_vpn or leaks or failed:
        return "VPN reading contradicts its routes"
    return None


def describe_routes(reading: VpnReading | None) -> str:
    """Compact per-family summary for the log, e.g. ``v4 proton0 routed vpn; v6 - blocked``."""
    if reading is None or not reading.routes:
        return "none"
    parts = []
    for r in reading.routes:
        tag = " vpn" if r.is_vpn else ""
        parts.append(f"v{r.family} {r.egress_interface or '-'} {r.kind.value}{tag}")
    return "; ".join(parts)


class Engine:
    """Decides ``HIDDEN | RED | BLUE`` for the focused browser's monitor."""

    def __init__(
        self,
        matcher: BrowserMatcher,
        clock: Clock,
        *,
        max_reading_age_s: float = 10.0,
        blue_confirm_ms: int = 0,
        show_on_fullscreen: bool = True,
    ) -> None:
        if not max_reading_age_s > 0:
            raise ValueError("max_reading_age_s must be positive")
        if blue_confirm_ms < 0:
            raise ValueError("blue_confirm_ms must not be negative")
        self._matcher = matcher
        self._clock = clock
        self._max_age = float(max_reading_age_s)
        self._blue_confirm_s = blue_confirm_ms / 1000.0
        self._show_on_fullscreen = show_on_fullscreen

        self._focus: FocusEvent | None = None
        self._match: MatchResult = NO_MATCH
        self._reading: VpnReading | None = None
        self._paused = False
        self._monitors: tuple[MonitorInfo, ...] = ()
        self._vpn_ok_since: float | None = None
        self._decision = _INITIAL

    @classmethod
    def from_config(cls, config: Config, clock: Clock) -> Engine:
        """Build an engine (and its matcher) from a validated :class:`Config`."""
        matcher = BrowserMatcher(config.browsers.classes, config.browsers.patterns)
        return cls(
            matcher,
            clock,
            max_reading_age_s=config.vpn.max_reading_age_s,
            blue_confirm_ms=config.indicator.blue_confirm_ms,
            show_on_fullscreen=config.indicator.show_on_fullscreen,
        )

    # -- read-only state ------------------------------------------------------------------

    @property
    def decision(self) -> Decision:
        """The current Decision (``HIDDEN``/"starting" before the first input)."""
        return self._decision

    @property
    def active(self) -> bool:
        """True while a bar is shown, i.e. VPN re-checks are wanted (ADR-0007, spec R5)."""
        return self._decision.indicator is not Indicator.HIDDEN

    @property
    def paused(self) -> bool:
        return self._paused

    def next_deadline(self) -> float | None:
        """Monotonic time at which :meth:`tick` may change the Decision, or ``None``.

        The daemon schedules one timer for it: when a pending blue confirmation completes, or
        when a fresh reading goes stale. ``None`` while no bar is shown, so nothing is scheduled
        while idle (spec R13).
        """
        if not self.active or self._reading is None:
            return None
        if reading_problem(self._reading, self._clock(), self._max_age) is not None:
            return None
        deadlines = [self._reading.timestamp + self._max_age]
        if self._vpn_ok_since is not None and self._decision.indicator is not Indicator.BLUE:
            deadlines.append(self._vpn_ok_since + self._blue_confirm_s)
        return min(deadlines)

    # -- inputs -----------------------------------------------------------------------------

    def on_focus(self, event: FocusEvent) -> Decision | None:
        """Feed a focus change (an empty ``window_class`` means nothing is focused)."""
        self._focus = event
        self._match = self._matcher.match(event.window_class)
        return self._update(self._clock())

    def on_vpn(self, reading: VpnReading) -> Decision | None:
        """Feed a VPN reading (it replaces the previous one)."""
        now = self._clock()
        self._track_confirmation(now)  # a gap where the old reading went stale resets the timer
        self._reading = reading
        return self._update(now)

    def on_pause(self, paused: bool) -> Decision | None:
        """Pause (bar hidden) or resume."""
        self._paused = paused
        return self._update(self._clock())

    def on_monitors(self, monitors: Sequence[MonitorInfo]) -> Decision | None:
        """Feed the current monitor list (replaces the previous one)."""
        self._monitors = tuple(monitors)
        return self._update(self._clock())

    def tick(self, now: float | None = None) -> Decision | None:
        """Advance time to ``now`` (default: the injected clock) for staleness and confirmation."""
        return self._update(self._clock() if now is None else now)

    # -- evaluation -------------------------------------------------------------------------

    def _track_confirmation(self, now: float) -> None:
        if reading_problem(self._reading, now, self._max_age) is None:
            if self._vpn_ok_since is None:
                self._vpn_ok_since = now
        else:
            self._vpn_ok_since = None

    def _update(self, now: float) -> Decision | None:
        self._track_confirmation(now)
        new = self._evaluate(now)
        old = self._decision
        self._decision = new
        if (new.indicator, new.monitor, new.reason) == (old.indicator, old.monitor, old.reason):
            return None
        return new

    def _resolve_monitor(self) -> str:
        names = [m.name for m in self._monitors]
        wanted = self._focus.monitor if self._focus is not None else ""
        if wanted and (not names or wanted in names):
            return wanted
        for monitor in self._monitors:
            if monitor.focused:
                return monitor.name
        return names[0] if names else ""

    def _inputs(self, now: float, monitor: str) -> dict[str, str]:
        focus = self._focus
        reading = self._reading
        age = "none" if reading is None else f"{now - reading.timestamp:.3f}"
        return {
            "class": focus.window_class if focus is not None else "",
            "match": self._match.rule or "none",
            "monitor": monitor,
            "fullscreen": str(focus.fullscreen if focus is not None else False).lower(),
            "paused": str(self._paused).lower(),
            "vpn_state": "none" if reading is None else reading.state.value,
            "reading_age_s": age,
            "routes": describe_routes(reading),
            "reading_reason": "" if reading is None else reading.reason,
        }

    def _evaluate(self, now: float) -> Decision:
        monitor = self._resolve_monitor()
        inputs = self._inputs(now, monitor)

        def hidden(reason: str) -> Decision:
            return Decision(Indicator.HIDDEN, "", reason, inputs)

        if self._paused:
            return hidden("paused")
        focus = self._focus
        if focus is None or not focus.window_class:
            return hidden("no window focused")
        if not self._match.matched:
            return hidden("focused window is not a browser")
        if focus.fullscreen and not self._show_on_fullscreen:
            return hidden("fullscreen browser and show_on_fullscreen is off")
        if not monitor:
            return hidden("monitor of the focused browser is unknown")

        problem = reading_problem(self._reading, now, self._max_age)
        if problem is not None:
            return Decision(Indicator.RED, monitor, f"browser focused, {problem}", inputs)
        since = self._vpn_ok_since
        if since is None or now - since < self._blue_confirm_s:
            return Decision(
                Indicator.RED, monitor, "browser focused, VPN confirmation pending", inputs
            )
        return Decision(Indicator.BLUE, monitor, "browser focused, routed through a VPN", inputs)
