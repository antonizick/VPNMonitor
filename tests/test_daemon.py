"""Full daemon pipeline with fakes: focus switches, VPN drop, pause/resume, crashes -> red."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor.config import Config, ConfigError, parse_config
from vpn_monitor.daemon import Daemon
from vpn_monitor.eventlog import EventLog
from vpn_monitor.fakes import FakeFocusSource, FakeScheduler, FakeVpnSource, RecordingSink
from vpn_monitor.model import (
    FamilyRoute,
    FocusEvent,
    Indicator,
    RouteKind,
    VpnReading,
    VpnState,
)

BRAVE = FocusEvent("brave-browser", "0x1", "HDMI-A-1")
FOOT = FocusEvent("foot", "0x2", "HDMI-A-1")
NOTHING = FocusEvent("", "", "")


def vpn_reading(ts: float) -> VpnReading:
    routes = (FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True),)
    return VpnReading(VpnState.VPN, routes, "v4 via proton0", ts)


def leak_reading(ts: float) -> VpnReading:
    routes = (FamilyRoute(4, "192.0.2.1", "wlo1", RouteKind.ROUTED, False),)
    return VpnReading(VpnState.NO_VPN, routes, "v4 via wlo1", ts)


class Rig:
    def __init__(self, tmp: Path, config: Config | None = None, **extra: Any) -> None:
        self.config = config or Config()
        self.scheduler = FakeScheduler()
        self.focus = FakeFocusSource()
        self.vpn = FakeVpnSource()
        self.sink = RecordingSink()
        self.log = EventLog(tmp)
        self.stopped: list[bool] = []
        self.daemon = Daemon(
            self.config,
            focus=self.focus,
            vpn=self.vpn,
            sink=self.sink,
            scheduler=self.scheduler,
            log=self.log,
            clock=self.scheduler.clock,
            on_stop=lambda: self.stopped.append(True),
            **extra,
        )

    @property
    def now(self) -> float:
        return self.scheduler.now

    def events(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.log.events_path.read_text().splitlines()]

    @property
    def shown(self) -> Indicator | None:
        return self.sink.last.indicator if self.sink.last else None


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    r = Rig(tmp_path)
    yield r
    r.log.close()


def test_focus_switches_show_red_blue_and_hide(rig: Rig) -> None:
    rig.daemon.start()
    rig.focus.emit(NOTHING)
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE
    assert rig.sink.last is not None
    assert rig.sink.last.monitor == "HDMI-A-1"
    rig.focus.emit(FOOT)
    assert rig.shown is Indicator.HIDDEN
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE


def test_vpn_drop_turns_red_at_once_and_reconnect_blue(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE
    rig.scheduler.advance(1)
    rig.vpn.emit(leak_reading(rig.now))
    assert rig.shown is Indicator.RED
    rig.vpn.emit(vpn_reading(rig.now))
    assert rig.shown is Indicator.BLUE


def test_vpn_source_is_active_only_while_a_bar_is_shown(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    assert rig.vpn.active is False
    rig.focus.emit(BRAVE)
    assert rig.vpn.active is True
    rig.focus.emit(FOOT)
    assert rig.vpn.active is False
    assert rig.vpn.active_history == [True, False]


def test_stuck_vpn_watcher_turns_blue_into_red_by_timer(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE
    rig.scheduler.advance(rig.config.vpn.max_reading_age_s - 1)
    assert rig.shown is Indicator.BLUE
    rig.scheduler.advance(2)  # no new reading: stale
    assert rig.shown is Indicator.RED
    assert "stale" in (rig.sink.last.reason if rig.sink.last else "")


def test_new_reading_postpones_the_stale_timer(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    for _ in range(5):
        rig.scheduler.advance(rig.config.vpn.max_reading_age_s - 2)
        rig.vpn.emit(vpn_reading(rig.now))
    assert rig.shown is Indicator.BLUE
    assert len(rig.scheduler.timers) == 1  # exactly one deadline timer, never a pile-up


def test_no_timer_while_hidden(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(FOOT)
    assert rig.scheduler.timers == {}


def test_pause_hides_and_resume_restores(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.daemon.handle_command("pause") == {"paused": True}
    assert rig.shown is Indicator.HIDDEN
    assert rig.vpn.active is False
    rig.focus.emit(FOOT)
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.HIDDEN  # still paused
    assert rig.daemon.handle_command("resume") == {"paused": False}
    assert rig.shown is Indicator.BLUE
    assert rig.daemon.handle_command("toggle") == {"paused": True}
    assert rig.daemon.handle_command("toggle") == {"paused": False}


def test_pause_without_auto_resume_lasts(rig: Rig) -> None:
    rig.daemon.start()
    rig.daemon.set_paused(True)
    rig.scheduler.advance(24 * 3600)
    assert rig.daemon.status()["paused"] is True
    assert rig.daemon.status()["pause_resumes_in_s"] is None


def test_pause_auto_resumes_when_configured(tmp_path: Path) -> None:
    rig = Rig(tmp_path, parse_config({"pause": {"auto_resume_minutes": 5}}))
    try:
        rig.daemon.start()
        rig.vpn.emit(vpn_reading(rig.now))
        rig.focus.emit(BRAVE)
        rig.daemon.set_paused(True)
        assert rig.daemon.status()["pause_resumes_in_s"] == 300.0
        rig.scheduler.advance(299)
        assert rig.shown is Indicator.HIDDEN
        rig.scheduler.advance(2)
        assert rig.daemon.status()["paused"] is False
        assert rig.shown is Indicator.RED  # the reading went stale while paused: red, not blue
        assert any(e["event"] == "resume" and "expired" in e["reason"] for e in rig.events())
    finally:
        rig.log.close()


def test_manual_resume_cancels_the_auto_resume_timer(tmp_path: Path) -> None:
    rig = Rig(tmp_path, parse_config({"pause": {"auto_resume_minutes": 5}}))
    try:
        rig.daemon.start()
        rig.daemon.set_paused(True)
        rig.daemon.set_paused(False)
        assert rig.scheduler.timers == {}
    finally:
        rig.log.close()


class ExplodingFocus(FakeFocusSource):
    def start(self, callback: Any) -> None:
        raise OSError("socket gone")


class ExplodingVpn(FakeVpnSource):
    def start(self, callback: Any) -> None:
        raise RuntimeError("ip missing")


def test_vpn_source_start_failure_is_logged_and_red(tmp_path: Path) -> None:
    r = Rig(tmp_path)
    r.vpn = ExplodingVpn()
    r.daemon = Daemon(
        r.config,
        focus=r.focus,
        vpn=r.vpn,
        sink=r.sink,
        scheduler=r.scheduler,
        log=r.log,
        clock=r.scheduler.clock,
    )
    try:
        r.daemon.start()
        r.focus.emit(BRAVE)
        assert r.shown is Indicator.RED
        assert any(e["event"] == "vpn_source_failed" for e in r.events())
    finally:
        r.log.close()


def test_focus_source_start_failure_is_logged(tmp_path: Path) -> None:
    r = Rig(tmp_path)
    r.daemon = Daemon(
        r.config,
        focus=ExplodingFocus(),
        vpn=r.vpn,
        sink=r.sink,
        scheduler=r.scheduler,
        log=r.log,
        clock=r.scheduler.clock,
    )
    try:
        r.daemon.start()
        assert any(e["event"] == "focus_source_failed" for e in r.events())
    finally:
        r.log.close()


def test_callback_exception_in_the_vpn_path_is_red_not_blue(rig: Rig, monkeypatch: Any) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE
    original = rig.daemon._engine.on_vpn
    calls = {"n": 0}

    def flaky(reading: VpnReading) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("boom")
        return original(reading)

    monkeypatch.setattr(rig.daemon._engine, "on_vpn", flaky)
    rig.vpn.emit(vpn_reading(rig.now))
    assert rig.shown is Indicator.RED
    assert any(e["event"] == "vpn_failed" for e in rig.events())


def test_broken_engine_forces_a_blue_bar_red(rig: Rig, monkeypatch: Any) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.BLUE

    def broken(*_: Any) -> Any:
        raise RuntimeError("engine bug")

    monkeypatch.setattr(rig.daemon._engine, "on_vpn", broken)
    monkeypatch.setattr(rig.daemon._engine, "on_focus", broken)
    rig.focus.emit(BRAVE)
    assert rig.shown is Indicator.RED
    assert any(e["event"] == "engine_failed" for e in rig.events())


def test_sink_failure_is_logged_and_does_not_stop_the_daemon(rig: Rig, monkeypatch: Any) -> None:
    rig.daemon.start()

    def broken(_: Any) -> None:
        raise RuntimeError("toolkit")

    monkeypatch.setattr(rig.sink, "apply", broken)
    rig.focus.emit(BRAVE)
    assert any(e["event"] == "overlay_failed" for e in rig.events())
    rig.focus.emit(FOOT)  # still alive


def test_vpn_set_active_failure_is_logged(rig: Rig, monkeypatch: Any) -> None:
    def broken(_: bool) -> None:
        raise RuntimeError("ip died")

    monkeypatch.setattr(rig.vpn, "set_active", broken)
    rig.daemon.start()
    rig.focus.emit(BRAVE)
    assert any(e["event"] == "vpn_source_failed" for e in rig.events())


def test_stop_removes_the_bar_and_is_idempotent(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    rig.daemon.stop("test")
    rig.daemon.stop("again")
    assert rig.sink.closed
    assert rig.focus.stopped
    assert rig.vpn.stopped
    assert rig.scheduler.timers == {}
    rig.focus.emit(BRAVE)  # ignored after stop (sources are stopped anyway)
    rig.daemon._on_focus(BRAVE)
    assert [e["event"] for e in rig.events()].count("daemon_stopped") == 1


def test_request_stop_quits_the_loop(rig: Rig) -> None:
    rig.daemon.start()
    rig.daemon.request_stop("SIGTERM received")
    assert rig.stopped == [True]
    assert rig.sink.closed


def test_stop_tolerates_failing_parts(rig: Rig, monkeypatch: Any) -> None:
    def broken(*_: Any) -> None:
        raise RuntimeError("x")

    monkeypatch.setattr(rig.vpn, "stop", broken)
    monkeypatch.setattr(rig.focus, "stop", broken)
    monkeypatch.setattr(rig.sink, "close", broken)
    rig.daemon.stop()
    events = {e["event"] for e in rig.events()}
    assert {
        "vpn_source_failed",
        "focus_source_failed",
        "overlay_failed",
        "daemon_stopped",
    } <= events


def test_every_decision_is_logged_with_inputs(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    decisions = [e for e in rig.events() if e["event"] == "decision"]
    assert decisions[-1]["decision"] == "blue"
    assert decisions[-1]["inputs"]["class"] == "brave-browser"
    assert "title" not in json.dumps(rig.events()).lower()


def test_status_reports_focus_reading_and_watchers(rig: Rig) -> None:
    rig.daemon.start()
    rig.vpn.emit(vpn_reading(rig.now))
    rig.focus.emit(BRAVE)
    rig.scheduler.advance(3)
    status = rig.daemon.handle_command("status")
    assert status["indicator"] == "blue"
    assert status["focus"]["class"] == "brave-browser"
    assert status["focus"]["match"] != "none"
    assert status["reading"]["state"] == "vpn"
    assert status["reading"]["age_s"] == 3.0
    assert status["reading"]["routes"][0]["interface"] == "proton0"
    assert status["uptime_s"] == 3.0
    json.dumps(status)  # JSON-safe


def test_status_before_any_input(rig: Rig) -> None:
    status = rig.daemon.status()
    assert status["reading"] is None
    assert status["indicator"] == "hidden"


def test_config_warnings_are_logged(tmp_path: Path) -> None:
    config = parse_config({"nonsense": {"x": 1}})
    r = Rig(tmp_path, config)
    try:
        r.daemon.start()
        assert any(e["event"] == "config_warning" for e in r.events())
    finally:
        r.log.close()


# -- reload ---------------------------------------------------------------------------------


def make_reload_rig(tmp_path: Path, loader: Callable[[], Config]) -> tuple[Rig, list[Any]]:
    rebuilt: list[Any] = []

    def factory(appearance: Any) -> RecordingSink:
        rebuilt.append(appearance)
        return RecordingSink()

    return Rig(tmp_path, sink_factory=factory, config_loader=loader), rebuilt


def test_reload_applies_new_browser_list_and_replays_state(tmp_path: Path) -> None:
    new = parse_config({"browsers": {"classes": ["foot"], "patterns": []}})
    rig, _ = make_reload_rig(tmp_path, lambda: new)
    try:
        rig.daemon.start()
        rig.vpn.emit(vpn_reading(rig.now))
        rig.focus.emit(FOOT)
        assert rig.shown is Indicator.HIDDEN
        rig.daemon.reload()
        assert rig.shown is Indicator.BLUE  # foot is a "browser" now; focus and reading replayed
        assert rig.sink.last is not None
        assert rig.sink.last.inputs["vpn_state"] == "vpn"  # the logged inputs are the replayed ones
    finally:
        rig.log.close()


def test_reload_keeps_pause(tmp_path: Path) -> None:
    rig, _ = make_reload_rig(tmp_path, Config)
    try:
        rig.daemon.start()
        rig.focus.emit(BRAVE)
        rig.daemon.set_paused(True)
        rig.daemon.reload()
        assert rig.daemon.status()["paused"] is True
        assert rig.shown is Indicator.HIDDEN
    finally:
        rig.log.close()


def test_reload_rebuilds_the_overlay_when_the_look_changes(tmp_path: Path) -> None:
    new = parse_config({"appearance": {"thickness": 3}})
    rig, rebuilt = make_reload_rig(tmp_path, lambda: new)
    try:
        rig.daemon.start()
        rig.focus.emit(BRAVE)
        old_sink = rig.sink
        rig.daemon.reload()
        assert old_sink.closed
        assert len(rebuilt) == 1
        assert rebuilt[0].thickness == 3
    finally:
        rig.log.close()


def test_reload_with_a_broken_config_keeps_the_old_one(tmp_path: Path) -> None:
    def broken() -> Config:
        raise ConfigError("appearance.thickness: must be an integer")

    rig, rebuilt = make_reload_rig(tmp_path, broken)
    try:
        rig.daemon.start()
        rig.vpn.emit(vpn_reading(rig.now))
        rig.focus.emit(BRAVE)
        rig.daemon.reload()
        assert rig.shown is Indicator.BLUE
        assert not rebuilt
        assert any(e["event"] == "config_reload_failed" for e in rig.events())
    finally:
        rig.log.close()


def test_reload_warns_that_vpn_changes_need_a_restart(tmp_path: Path) -> None:
    new = parse_config({"vpn": {"max_reading_age_s": 30}})
    rig, _ = make_reload_rig(tmp_path, lambda: new)
    try:
        rig.daemon.start()
        rig.daemon.reload()
        assert any("restart" in e["reason"] for e in rig.events())
    finally:
        rig.log.close()


def test_reload_without_a_loader_does_nothing(rig: Rig) -> None:
    rig.daemon.reload()
    assert rig.sink.decisions == []


def test_reload_survives_a_sink_rebuild_failure(tmp_path: Path) -> None:
    def factory(_: Any) -> RecordingSink:
        raise RuntimeError("no layer shell")

    new = parse_config({"appearance": {"thickness": 4}})
    rig = Rig(tmp_path, sink_factory=factory, config_loader=lambda: new)
    try:
        rig.daemon.start()
        rig.daemon.reload()
        assert any(e["event"] == "overlay_failed" for e in rig.events())
    finally:
        rig.log.close()


def test_reload_replay_failure_is_red_not_blue(tmp_path: Path, monkeypatch: Any) -> None:
    from vpn_monitor import daemon as daemon_module

    real_engine = daemon_module.Engine
    rig, _ = make_reload_rig(tmp_path, Config)
    try:
        rig.daemon.start()
        rig.vpn.emit(vpn_reading(rig.now))
        rig.focus.emit(BRAVE)
        assert rig.shown is Indicator.BLUE

        class Broken:
            @classmethod
            def from_config(cls, *_: Any) -> Any:
                engine = real_engine.from_config(Config(), rig.scheduler.clock)

                def boom(*_a: Any) -> Any:
                    raise RuntimeError("bug")

                engine.on_focus = boom  # type: ignore[method-assign]
                return engine

        monkeypatch.setattr(daemon_module, "Engine", Broken)
        rig.daemon.reload()
        assert any(e["event"] == "config_reload_failed" for e in rig.events())
        assert rig.shown in (Indicator.RED, Indicator.HIDDEN)  # never blue
    finally:
        rig.log.close()
