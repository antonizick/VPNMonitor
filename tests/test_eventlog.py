"""Event log: schema, both files, rotation, permissions and the S1 title guard."""

from __future__ import annotations

import json
import stat
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vpn_monitor.browsers import BrowserMatcher
from vpn_monitor.engine import Engine
from vpn_monitor.eventlog import (
    EVENT_LOG,
    HUMAN_LOG,
    EventLog,
    TitleGuard,
    TitleLeakError,
    default_state_dir,
)
from vpn_monitor.model import (
    Decision,
    FamilyRoute,
    FocusEvent,
    Indicator,
    RouteKind,
    VpnReading,
    VpnState,
)

CST = timezone(timedelta(hours=-6))
FIXED = datetime(2026, 11, 18, 22, 31, 5, 123000, tzinfo=CST)


def fixed_clock() -> datetime:
    return FIXED


def read_events(log: EventLog) -> list[dict[str, object]]:
    return [json.loads(line) for line in log.events_path.read_text().splitlines()]


@pytest.fixture
def log(tmp_path: Path) -> Iterator[EventLog]:
    event_log = EventLog(tmp_path / "state", wall_clock=fixed_clock)
    yield event_log
    event_log.close()


def test_creates_private_directory_and_both_files(log: EventLog) -> None:
    log.record("startup", reason="daemon started")
    assert stat.S_IMODE(log.state_dir.stat().st_mode) == 0o700
    assert log.human_path.name == HUMAN_LOG
    assert log.events_path.name == EVENT_LOG
    assert log.human_path.exists()
    assert log.events_path.exists()


def test_tightens_existing_directory_mode(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    event_log = EventLog(state)
    try:
        assert stat.S_IMODE(state.stat().st_mode) == 0o700
    finally:
        event_log.close()


def test_decision_schema(log: EventLog) -> None:
    decision = Decision(
        Indicator.RED,
        "eDP-1",
        "browser focused, VPN reading is stale",
        {"class": "brave-browser", "match": "exact:brave-browser", "paused": "false"},
    )
    entry = log.decision(decision)
    assert entry == {
        "ts": "2026-11-18T22:31:05.123-06:00",
        "event": "decision",
        "level": "info",
        "decision": "red",
        "monitor": "eDP-1",
        "reason": "browser focused, VPN reading is stale",
        "inputs": {"class": "brave-browser", "match": "exact:brave-browser", "paused": "false"},
    }
    assert read_events(log) == [entry]
    assert set(entry) == {"ts", "event", "level", "decision", "monitor", "reason", "inputs"}


def test_human_line(log: EventLog) -> None:
    decision = Decision(
        Indicator.BLUE,
        "eDP-1",
        "browser focused, routed through a VPN",
        {"class": "brave-browser", "routes": "v4 proton0 routed vpn"},
    )
    log.decision(decision)
    line = log.human_path.read_text().strip()
    assert line == (
        "2026-11-18T22:31:05.123-06:00 INFO    decision blue on eDP-1: "
        "browser focused, routed through a VPN "
        "[class=brave-browser routes='v4 proton0 routed vpn']"
    )


def test_event_without_decision(log: EventLog) -> None:
    entry = log.record("config", reason="unknown key vpn.bogus ignored", inputs={"path": "/x"})
    assert entry["decision"] is None
    assert entry["monitor"] is None
    assert (
        log.human_path.read_text()
        .strip()
        .endswith("config: unknown key vpn.bogus ignored [path=/x]")
    )


def test_hidden_decision_has_no_monitor_in_human_line(log: EventLog) -> None:
    log.decision(Decision(Indicator.HIDDEN, "", "paused"))
    assert log.human_path.read_text().strip().endswith("decision hidden: paused")


def test_error_level(log: EventLog) -> None:
    log.error("probe", "ip route get timed out", {"family": "4"})
    (entry,) = read_events(log)
    assert entry["level"] == "error"
    assert " ERROR " in log.human_path.read_text()


def test_extra_inputs_merge_over_decision_inputs(log: EventLog) -> None:
    decision = Decision(Indicator.RED, "eDP-1", "r", {"a": "1", "b": "2"})
    entry = log.record("decision", reason="r", decision=decision, inputs={"b": "3"})
    assert entry["inputs"] == {"a": "1", "b": "3"}


def test_unicode_is_kept(log: EventLog) -> None:
    log.record("note", reason="café ✓")
    assert read_events(log)[0]["reason"] == "café ✓"


def test_default_wall_clock_has_offset(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path)
    try:
        ts = event_log.record("x", reason="y")["ts"]
    finally:
        event_log.close()
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert abs(parsed - datetime.now(UTC)) < timedelta(minutes=1)


def test_rotation(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path, max_bytes=2_000, backup_count=2, wall_clock=fixed_clock)
    try:
        for i in range(200):
            event_log.record("tick", reason=f"entry {i:04d} " + "x" * 40)
    finally:
        event_log.close()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        EVENT_LOG,
        f"{EVENT_LOG}.1",
        f"{EVENT_LOG}.2",
        HUMAN_LOG,
        f"{HUMAN_LOG}.1",
        f"{HUMAN_LOG}.2",
    ]
    for path in tmp_path.iterdir():
        assert path.stat().st_size <= 2_000
    last = json.loads((tmp_path / EVENT_LOG).read_text().splitlines()[-1])
    assert last["reason"].startswith("entry 0199")


def test_two_logs_do_not_share_handlers(tmp_path: Path) -> None:
    a = EventLog(tmp_path / "a")
    b = EventLog(tmp_path / "b")
    try:
        a.record("only-a", reason="a")
        assert "only-a" not in (tmp_path / "b" / EVENT_LOG).read_text()
    finally:
        a.close()
        b.close()


def test_close_is_idempotent_and_blocks_writes(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path)
    event_log.close()
    event_log.close()
    with pytest.raises(RuntimeError, match="closed"):
        event_log.record("x", reason="y")


def test_default_state_dir() -> None:
    assert default_state_dir({"XDG_STATE_HOME": "/tmp/xdg-state"}) == Path(
        "/tmp/xdg-state/vpn-monitor"
    )
    expected = Path.home() / ".local" / "state" / "vpn-monitor"
    assert default_state_dir({}) == expected
    assert default_state_dir({"XDG_STATE_HOME": "relative"}) == expected


# --- S1: titles never reach the log ------------------------------------------------------------

SECRET_TITLES = ("Bank of Example: Account 12345 - Brave", "https://example.org/private?id=9")


def test_guard_raises_on_title_anywhere() -> None:
    guard = TitleGuard(SECRET_TITLES)
    guard.add("")  # ignored
    guard.check({"reason": "fine", "inputs": {"class": "brave-browser"}, "n": 3, "x": None})
    with pytest.raises(TitleLeakError):
        guard.check({"reason": f"focused {SECRET_TITLES[0]}"})
    with pytest.raises(TitleLeakError):
        guard.check({"inputs": {SECRET_TITLES[1]: "key leak"}})
    with pytest.raises(TitleLeakError):
        guard.check({"list": ["a", ("b", SECRET_TITLES[1])]})


def test_guard_stops_the_write(tmp_path: Path) -> None:
    event_log = EventLog(tmp_path, guard=TitleGuard(SECRET_TITLES))
    try:
        with pytest.raises(TitleLeakError):
            event_log.record("focus", reason="r", inputs={"title": SECRET_TITLES[0]})
    finally:
        event_log.close()
    assert SECRET_TITLES[0] not in (tmp_path / EVENT_LOG).read_text()
    assert SECRET_TITLES[0] not in (tmp_path / HUMAN_LOG).read_text()


def test_engine_decisions_never_log_titles(tmp_path: Path) -> None:
    """End to end: a scripted session through the engine, every decision logged with a guard."""
    guard = TitleGuard(SECRET_TITLES)
    event_log = EventLog(tmp_path, guard=guard)
    now = [1000.0]
    engine = Engine(BrowserMatcher(), lambda: now[0], max_reading_age_s=10.0)
    reading = VpnReading(
        VpnState.VPN,
        (FamilyRoute(4, "1.1.1.1", "proton0", RouteKind.ROUTED, True),),
        "v4 via proton0",
        1000.0,
    )
    steps = [
        lambda: engine.on_focus(FocusEvent("brave-browser", "0x1", "eDP-1")),
        lambda: engine.on_vpn(reading),
        lambda: engine.on_focus(FocusEvent("brave-bank.example__-Default", "0x2", "eDP-1")),
        lambda: engine.on_pause(True),
        lambda: engine.on_pause(False),
        lambda: engine.tick(1020.0),
        lambda: engine.on_focus(FocusEvent("foot", "0x3", "eDP-1")),
    ]
    logged = 0
    try:
        for step in steps:
            decision = step()
            if decision is not None:
                event_log.decision(decision)
                logged += 1
    finally:
        event_log.close()
    text = (tmp_path / EVENT_LOG).read_text() + (tmp_path / HUMAN_LOG).read_text()
    assert logged >= 5
    for title in SECRET_TITLES:
        assert title not in text
    decisions = [
        e["decision"] for e in map(json.loads, (tmp_path / EVENT_LOG).read_text().splitlines())
    ]
    assert decisions == ["red", "blue", "hidden", "blue", "red", "hidden"]
