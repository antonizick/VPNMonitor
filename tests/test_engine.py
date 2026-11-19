"""Engine truth table, staleness, hysteresis, monitors and the S6 invariant (never a false blue)."""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass

import pytest

from vpn_monitor.browsers import BrowserMatcher
from vpn_monitor.config import Config, parse_config
from vpn_monitor.engine import Engine, describe_routes, reading_problem
from vpn_monitor.model import (
    Decision,
    FamilyRoute,
    FocusEvent,
    Indicator,
    MonitorInfo,
    RouteKind,
    VpnReading,
    VpnState,
)

MAX_AGE = 10.0


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def v4(
    kind: RouteKind = RouteKind.ROUTED, dev: str | None = "proton0", vpn: bool = True
) -> FamilyRoute:
    return FamilyRoute(4, "1.1.1.1", dev, kind, vpn)


def v6(
    kind: RouteKind = RouteKind.BLOCKED, dev: str | None = "ipv6leakintrf0", vpn: bool = False
) -> FamilyRoute:
    return FamilyRoute(6, "2606:4700:4700::1111", dev, kind, vpn)


def vpn_reading(ts: float, routes: tuple[FamilyRoute, ...] | None = None) -> VpnReading:
    return VpnReading(VpnState.VPN, (v4(), v6()) if routes is None else routes, "all via VPN", ts)


def no_vpn_reading(ts: float) -> VpnReading:
    return VpnReading(VpnState.NO_VPN, (v4(dev="wlo1", vpn=False),), "v4 via wlo1", ts)


def unknown_reading(ts: float) -> VpnReading:
    return VpnReading(VpnState.UNKNOWN, (), "probe timed out", ts)


BRAVE = FocusEvent("brave-browser", "0x1", "eDP-1")
WEBAPP = FocusEvent("brave-basecamp.com__-Default", "0x2", "eDP-1")
TERMINAL = FocusEvent("foot", "0x3", "eDP-1")
NOTHING = FocusEvent("", "", "")


def make(clock: FakeClock | None = None, **kwargs: object) -> tuple[Engine, FakeClock]:
    clock = clock or FakeClock()
    return Engine(BrowserMatcher(), clock, max_reading_age_s=MAX_AGE, **kwargs), clock  # type: ignore[arg-type]


# --- basic truth table -----------------------------------------------------------------------


def test_initial_decision_is_hidden() -> None:
    engine, _ = make()
    assert engine.decision.indicator is Indicator.HIDDEN
    assert engine.decision.reason == "starting"
    assert not engine.active
    assert engine.next_deadline() is None


def test_browser_without_reading_is_red() -> None:
    engine, _ = make()
    d = engine.on_focus(BRAVE)
    assert d is not None
    assert (d.indicator, d.monitor) == (Indicator.RED, "eDP-1")
    assert d.reason == "browser focused, no VPN reading yet"
    assert engine.active


def test_browser_with_fresh_vpn_is_blue() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    d = engine.on_vpn(vpn_reading(clock.now))
    assert d is not None
    assert (d.indicator, d.monitor) == (Indicator.BLUE, "eDP-1")


def test_webapp_counts_as_browser() -> None:
    engine, clock = make()
    engine.on_vpn(vpn_reading(clock.now))
    d = engine.on_focus(WEBAPP)
    assert d is not None
    assert d.indicator is Indicator.BLUE
    assert d.inputs["match"].startswith("regex:")


@pytest.mark.parametrize(
    ("reading_factory", "reason"),
    [
        (no_vpn_reading, "browser focused, traffic is not routed through a VPN"),
        (unknown_reading, "browser focused, VPN state unknown"),
    ],
)
def test_negative_readings_are_red(reading_factory: object, reason: str) -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(reading_factory(clock.now))  # type: ignore[operator]
    assert engine.decision.indicator is Indicator.RED
    assert engine.decision.reason == reason


@pytest.mark.parametrize("focus", [TERMINAL, NOTHING])
def test_non_browser_is_hidden(focus: FocusEvent) -> None:
    engine, clock = make()
    engine.on_vpn(vpn_reading(clock.now))
    engine.on_focus(focus)
    assert engine.decision.indicator is Indicator.HIDDEN
    assert engine.decision.monitor == ""
    assert not engine.active


def test_pause_hides_and_resume_restores() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    d = engine.on_pause(True)
    assert d is not None
    assert (d.indicator, d.reason) == (Indicator.HIDDEN, "paused")
    assert engine.paused
    assert not engine.active
    d = engine.on_pause(False)
    assert d is not None
    assert d.indicator is Indicator.BLUE


@pytest.mark.parametrize(("show", "expected"), [(True, Indicator.RED), (False, Indicator.HIDDEN)])
def test_fullscreen(show: bool, expected: Indicator) -> None:
    engine, _ = make(show_on_fullscreen=show)
    engine.on_focus(FocusEvent("brave-browser", "0x1", "eDP-1", fullscreen=True))
    assert engine.decision.indicator is expected


# --- staleness and timestamps ----------------------------------------------------------------


def test_reading_goes_stale_and_turns_red() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(MAX_AGE)
    assert engine.tick() is None  # exactly max age is still fresh
    clock.advance(0.001)
    d = engine.tick()
    assert d is not None
    assert (d.indicator, d.reason) == (Indicator.RED, "browser focused, VPN reading is stale")


def test_tick_with_explicit_now() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    d = engine.tick(clock.now + MAX_AGE + 1)
    assert d is not None
    assert d.indicator is Indicator.RED


def test_already_stale_reading_is_red() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now - MAX_AGE - 0.5))
    assert engine.decision.reason == "browser focused, VPN reading is stale"


@pytest.mark.parametrize("ts", [math.nan, 1000.0 + 1.5, math.inf])
def test_future_or_nan_timestamp_is_red(ts: float) -> None:
    engine, _ = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(ts))
    assert engine.decision.indicator is Indicator.RED
    assert engine.decision.reason == "browser focused, VPN reading has an invalid timestamp"


def test_small_future_skew_is_tolerated() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now + 0.5))
    assert engine.decision.indicator is Indicator.BLUE


def test_minus_infinity_timestamp_is_stale() -> None:
    engine, _ = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(-math.inf))
    assert engine.decision.reason == "browser focused, VPN reading is stale"


# --- reading consistency (defence in depth) ----------------------------------------------------


@pytest.mark.parametrize(
    "routes",
    [
        (),  # no routes at all
        (v4(), v6(RouteKind.ROUTED, "wlo1", False)),  # IPv6 leak (spec R3)
        (v4(RouteKind.ROUTED, "wlo1", False), v6()),  # IPv4 leak
        (v4(RouteKind.BLOCKED, None, False), v6()),  # nothing routed: no internet = red (R4)
        (v4(RouteKind.UNREACHABLE, None, False), v6(RouteKind.UNREACHABLE, None, False)),
        (v4(), v6(RouteKind.ERROR, None, False)),  # a failed probe
        (v4(RouteKind.ERROR, "proton0", True),),
    ],
)
def test_vpn_state_contradicting_routes_is_red(routes: tuple[FamilyRoute, ...]) -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now, routes))
    assert engine.decision.indicator is Indicator.RED
    assert engine.decision.reason == "browser focused, VPN reading contradicts its routes"


@pytest.mark.parametrize(
    "routes",
    [
        (v4(),),
        (v4(), v6()),
        (v4(), v6(RouteKind.UNREACHABLE, None, False)),
        (v4(), v6(RouteKind.ROUTED, "proton0", True)),
    ],
)
def test_consistent_vpn_routes_are_blue(routes: tuple[FamilyRoute, ...]) -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now, routes))
    assert engine.decision.indicator is Indicator.BLUE


# --- hysteresis (ADR-0013) ---------------------------------------------------------------------


def test_blue_confirm_delays_blue_only() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    assert engine.decision.reason == "browser focused, VPN confirmation pending"
    assert engine.next_deadline() == pytest.approx(clock.now + 0.5)
    clock.advance(0.499)
    assert engine.tick() is None
    clock.advance(0.001)
    d = engine.tick()
    assert d is not None
    assert d.indicator is Indicator.BLUE


def test_red_is_immediate_even_with_blue_confirm() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(1)
    engine.tick()
    assert engine.decision.indicator is Indicator.BLUE
    d = engine.on_vpn(no_vpn_reading(clock.now))
    assert d is not None
    assert d.indicator is Indicator.RED


def test_flapping_vpn_stays_red() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(BRAVE)
    for _ in range(20):
        engine.on_vpn(vpn_reading(clock.now))
        clock.advance(0.3)
        engine.tick()
        assert engine.decision.indicator is Indicator.RED
        engine.on_vpn(no_vpn_reading(clock.now))
        clock.advance(0.3)
        engine.tick()
        assert engine.decision.indicator is Indicator.RED


def test_consecutive_vpn_readings_keep_confirmation_running() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(0.3)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(0.3)
    engine.tick()
    assert engine.decision.indicator is Indicator.BLUE


def test_gap_where_reading_went_stale_restarts_confirmation() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(MAX_AGE + 5)  # no tick in between: the reading silently went stale
    engine.on_vpn(vpn_reading(clock.now))
    assert engine.decision.reason == "browser focused, VPN confirmation pending"


def test_confirmation_runs_while_hidden() -> None:
    engine, clock = make(blue_confirm_ms=500)
    engine.on_focus(TERMINAL)
    engine.on_vpn(vpn_reading(clock.now))
    clock.advance(1)
    engine.on_vpn(vpn_reading(clock.now))
    d = engine.on_focus(BRAVE)
    assert d is not None
    assert d.indicator is Indicator.BLUE


def test_rejects_bad_constructor_arguments() -> None:
    with pytest.raises(ValueError, match="max_reading_age_s"):
        Engine(BrowserMatcher(), FakeClock(), max_reading_age_s=0)
    with pytest.raises(ValueError, match="blue_confirm_ms"):
        Engine(BrowserMatcher(), FakeClock(), blue_confirm_ms=-1)


# --- deadlines -----------------------------------------------------------------------------------


def test_deadline_is_staleness_while_blue() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now - 2))
    assert engine.next_deadline() == pytest.approx(clock.now - 2 + MAX_AGE)


def test_no_deadline_while_hidden_or_red_without_fresh_vpn() -> None:
    engine, clock = make()
    engine.on_focus(TERMINAL)
    engine.on_vpn(vpn_reading(clock.now))
    assert engine.next_deadline() is None  # idle: nothing to schedule (R13)
    engine.on_focus(BRAVE)
    engine.on_vpn(no_vpn_reading(clock.now))
    assert engine.next_deadline() is None
    engine2, _ = make()
    engine2.on_focus(BRAVE)
    assert engine2.next_deadline() is None  # red with no reading


def test_deadline_is_earlier_of_confirm_and_stale() -> None:
    engine, clock = make(blue_confirm_ms=5000)
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now - 8))  # stale in 2 s, confirm in 5 s
    assert engine.next_deadline() == pytest.approx(clock.now + 2)


# --- monitors ----------------------------------------------------------------------------------


MONITORS = [
    MonitorInfo("eDP-1", 2400, 1350, 1.6, focused=False),
    MonitorInfo("DP-1", 1920, 1080, 1.0, focused=True),
]


def test_bar_follows_focused_window_monitor() -> None:
    engine, _ = make()
    engine.on_monitors(MONITORS)
    engine.on_focus(FocusEvent("brave-browser", "0x1", "eDP-1"))
    assert engine.decision.monitor == "eDP-1"
    d = engine.on_focus(FocusEvent("brave-browser", "0x1", "DP-1"))
    assert d is not None
    assert d.monitor == "DP-1"


def test_unknown_monitor_falls_back_to_focused_monitor() -> None:
    engine, _ = make()
    engine.on_monitors(MONITORS)
    engine.on_focus(FocusEvent("brave-browser", "0x1", ""))
    assert engine.decision.monitor == "DP-1"
    engine.on_focus(FocusEvent("brave-browser", "0x1", "HDMI-A-9"))  # removed monitor
    assert engine.decision.monitor == "DP-1"


def test_unknown_monitor_falls_back_to_first_monitor() -> None:
    engine, _ = make()
    engine.on_monitors([MonitorInfo("eDP-1", 2400, 1350, 1.6)])
    engine.on_focus(FocusEvent("brave-browser", "0x1", ""))
    assert engine.decision.monitor == "eDP-1"


def test_monitor_without_list_is_trusted() -> None:
    engine, _ = make()
    engine.on_focus(FocusEvent("brave-browser", "0x1", "DP-3"))
    assert engine.decision.monitor == "DP-3"


def test_no_monitor_at_all_is_hidden() -> None:
    engine, _ = make()
    engine.on_focus(FocusEvent("brave-browser", "0x1", ""))
    assert engine.decision.indicator is Indicator.HIDDEN
    assert engine.decision.reason == "monitor of the focused browser is unknown"


def test_monitor_removed_moves_bar() -> None:
    engine, _ = make()
    engine.on_monitors(MONITORS)
    engine.on_focus(FocusEvent("brave-browser", "0x1", "eDP-1"))
    d = engine.on_monitors([MONITORS[1]])
    assert d is not None
    assert d.monitor == "DP-1"


# --- change detection and inputs ------------------------------------------------------------------


def test_returns_none_when_unchanged() -> None:
    engine, clock = make()
    assert engine.on_focus(BRAVE) is not None
    assert engine.on_focus(FocusEvent("brave-browser", "0x9", "eDP-1")) is None  # same result
    assert engine.on_vpn(vpn_reading(clock.now)) is not None
    clock.advance(1)
    assert engine.on_vpn(vpn_reading(clock.now)) is None  # still blue
    assert engine.on_pause(False) is None
    assert engine.tick() is None


def test_reason_change_is_reported_even_if_colour_stays() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    d = engine.on_vpn(no_vpn_reading(clock.now))
    assert d is not None
    assert d.indicator is Indicator.RED
    d = engine.on_vpn(unknown_reading(clock.now))
    assert d is not None
    assert d.reason == "browser focused, VPN state unknown"


def test_inputs_record() -> None:
    engine, clock = make()
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now - 1.25))
    assert engine.decision.inputs == {
        "class": "brave-browser",
        "match": "exact:brave-browser",
        "monitor": "eDP-1",
        "fullscreen": "false",
        "paused": "false",
        "vpn_state": "vpn",
        "reading_age_s": "1.250",
        "routes": "v4 proton0 routed vpn; v6 ipv6leakintrf0 blocked",
        "reading_reason": "all via VPN",
    }
    assert all(isinstance(v, str) for v in engine.decision.inputs.values())


def test_inputs_before_any_input() -> None:
    engine, _ = make()
    engine.on_pause(True)
    assert engine.decision.inputs["class"] == ""
    assert engine.decision.inputs["vpn_state"] == "none"
    assert engine.decision.inputs["routes"] == "none"


def test_describe_routes() -> None:
    assert describe_routes(None) == "none"
    assert describe_routes(unknown_reading(0)) == "none"
    assert describe_routes(no_vpn_reading(0)) == "v4 wlo1 routed"
    assert describe_routes(vpn_reading(0, (v4(RouteKind.UNREACHABLE, None, False),))) == (
        "v4 - unreachable"
    )


def test_from_config() -> None:
    config = parse_config({"indicator": {"blue_confirm_ms": 250, "show_on_fullscreen": False}})
    clock = FakeClock()
    engine = Engine.from_config(config, clock)
    engine.on_focus(FocusEvent("brave-browser", "0x1", "eDP-1", fullscreen=True))
    assert engine.decision.indicator is Indicator.HIDDEN
    engine.on_focus(BRAVE)
    engine.on_vpn(vpn_reading(clock.now))
    assert engine.decision.reason == "browser focused, VPN confirmation pending"
    assert Engine.from_config(Config(), clock).decision.reason == "starting"


# --- S6 invariant: exhaustive combinations ------------------------------------------------------


@dataclass(frozen=True)
class ReadingCase:
    name: str
    reading: VpnReading | None
    """Timestamp is relative to now (0 = now); shifted in the test."""
    positive: bool
    """True only for a fresh, consistent VPN reading."""


def _shift(reading: VpnReading | None, now: float) -> VpnReading | None:
    if reading is None:
        return None
    return VpnReading(reading.state, reading.routes, reading.reason, now + reading.timestamp)


ROUTE_SETS: dict[str, tuple[tuple[FamilyRoute, ...], bool]] = {
    "v4vpn+v6blocked": ((v4(), v6()), True),
    "v4vpn": ((v4(),), True),
    "v4vpn+v6vpn": ((v4(), v6(RouteKind.ROUTED, "wg0", True)), True),
    "v4vpn+v6unreach": ((v4(), v6(RouteKind.UNREACHABLE, None, False)), True),
    "v4vpn+v6leak": ((v4(), v6(RouteKind.ROUTED, "wlo1", False)), False),
    "v4leak+v6blocked": ((v4(RouteKind.ROUTED, "wlo1", False), v6()), False),
    "allblocked": ((v4(RouteKind.BLOCKED, None, False), v6()), False),
    "v4vpn+v6error": ((v4(), v6(RouteKind.ERROR, None, False)), False),
    "empty": ((), False),
}
AGES = {
    "fresh": (0.0, True),
    "edge": (-MAX_AGE, True),
    "stale": (-MAX_AGE - 0.01, False),
    "future": (5.0, False),
    "nan": (math.nan, False),
}


def _reading_cases() -> list[ReadingCase]:
    cases = [ReadingCase("none", None, False)]
    for (rname, (routes, routes_ok)), (aname, (offset, age_ok)), state in itertools.product(
        ROUTE_SETS.items(), AGES.items(), VpnState
    ):
        positive = state is VpnState.VPN and routes_ok and age_ok
        cases.append(
            ReadingCase(
                f"{state.value}/{rname}/{aname}", VpnReading(state, routes, "r", offset), positive
            )
        )
    return cases


READING_CASES = _reading_cases()
FOCUS_CASES = {
    "browser": (BRAVE, True),
    "webapp": (WEBAPP, True),
    "browser-fullscreen": (FocusEvent("brave-browser", "0x1", "eDP-1", fullscreen=True), True),
    "browser-nomonitor": (FocusEvent("chromium", "0x1", ""), True),
    "terminal": (TERMINAL, False),
    "terminal-fullscreen": (FocusEvent("foot", "0x3", "eDP-1", fullscreen=True), False),
    "nothing": (NOTHING, False),
    "none": (None, False),
}


def _assert_invariant(
    engine: Engine, decision: Decision, *, browser: bool, paused: bool, positive: bool
) -> None:
    if decision.indicator is Indicator.BLUE:
        assert browser, "BLUE without a browser focused"
        assert not paused, "BLUE while paused"
        assert positive, "BLUE without a fresh, consistent VPN reading"
        assert decision.monitor, "BLUE without a monitor"
    if decision.indicator is Indicator.HIDDEN:
        assert decision.monitor == ""


@pytest.mark.parametrize("reading_case", READING_CASES, ids=lambda c: c.name)
def test_s6_invariant_over_all_combinations(reading_case: ReadingCase) -> None:
    combos = itertools.product(
        FOCUS_CASES.items(), (False, True), (False, True), (None, [], MONITORS)
    )
    for (fname, (focus, is_browser)), paused, show_fs, monitors in combos:
        clock = FakeClock()
        engine = Engine(
            BrowserMatcher(), clock, max_reading_age_s=MAX_AGE, show_on_fullscreen=show_fs
        )
        if monitors is not None:
            engine.on_monitors(monitors)
        if focus is not None:
            engine.on_focus(focus)
        engine.on_pause(paused)
        reading = _shift(reading_case.reading, clock.now)
        if reading is not None:
            engine.on_vpn(reading)
        d = engine.decision
        _assert_invariant(
            engine, d, browser=is_browser, paused=paused, positive=reading_case.positive
        )

        # And the converse: every input that should be blue is blue, the rest decided as expected.
        fullscreen_hidden = focus is not None and focus.fullscreen and not show_fs
        has_monitor = bool(focus is not None and focus.monitor) or bool(monitors)
        visible = is_browser and not paused and not fullscreen_hidden and has_monitor
        expected = (
            Indicator.HIDDEN
            if not visible
            else Indicator.BLUE
            if reading_case.positive
            else Indicator.RED
        )
        assert d.indicator is expected, (fname, paused, show_fs, monitors, d.reason)
        assert engine.active is visible


def test_reading_problem_matches_case_table() -> None:
    for case in READING_CASES:
        reading = _shift(case.reading, 0.0)
        assert (reading_problem(reading, 0.0, MAX_AGE) is None) is case.positive, case.name


# --- S6 invariant: random event sequences (stateful property test) ------------------------------


@pytest.mark.parametrize("seed", range(200))
def test_s6_invariant_random_sequences(seed: int) -> None:
    rng = random.Random(seed)
    clock = FakeClock()
    confirm_ms = rng.choice([0, 0, 200, 1500])
    engine = Engine(
        BrowserMatcher(),
        clock,
        max_reading_age_s=MAX_AGE,
        blue_confirm_ms=confirm_ms,
        show_on_fullscreen=rng.random() < 0.5,
    )
    focus: FocusEvent | None = None
    paused = False
    reading: VpnReading | None = None
    ok_since: float | None = None  # independent model of the confirmation window

    def positive_now() -> bool:
        return reading_problem(reading, clock.now, MAX_AGE) is None

    for _ in range(60):
        step = rng.randrange(6)
        was_ok = positive_now()
        if step == 0:
            choice, _ = rng.choice(list(FOCUS_CASES.values()))
            if choice is not None:
                focus = choice
                engine.on_focus(choice)
        elif step == 1:
            case = rng.choice(READING_CASES)
            reading = _shift(case.reading, clock.now)
            if reading is None:
                continue
            engine.on_vpn(reading)
        elif step == 2:
            paused = rng.random() < 0.3
            engine.on_pause(paused)
        elif step == 3:
            engine.on_monitors(rng.choice([[], MONITORS, MONITORS[:1]]))
        else:
            clock.advance(rng.choice([0.05, 0.3, 1.0, 4.0, 11.0]))
            engine.tick()

        # Model of the confirmation timer: it starts the first time a positive reading is
        # observed and resets whenever a non-positive state is observed.
        if not was_ok:
            ok_since = None
        if not positive_now():
            ok_since = None
        elif ok_since is None:
            ok_since = clock.now

        d = engine.decision
        browser = focus is not None and engine._match.matched
        confirmed = ok_since is not None and clock.now - ok_since >= confirm_ms / 1000
        _assert_invariant(engine, d, browser=browser, paused=paused, positive=positive_now())
        if d.indicator is Indicator.BLUE:
            assert confirmed, f"BLUE before blue_confirm_ms elapsed (seed {seed})"
