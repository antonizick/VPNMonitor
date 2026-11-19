"""Change watcher: debounce, re-check while active, restart with back-off (spec R5, ADR-0007)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from vpn_monitor import vpn
from vpn_monitor.config import Config, ProbesConfig, VpnConfig
from vpn_monitor.eventlog import EventLog
from vpn_monitor.fakes import FakeScheduler
from vpn_monitor.model import VpnReading, VpnSource, VpnState
from vpn_monitor.vpn import (
    BACKOFF_RESET_S,
    DEBOUNCE_S,
    HEALTHY_AFTER_S,
    RESTART_INITIAL_S,
    RESTART_MAX_S,
    CommandResult,
    IpMonitorStream,
    RouteProbe,
    RouteWatcher,
)

LINKS = json.dumps(
    [{"ifname": "proton0", "linkinfo": {"info_kind": "wireguard"}}, {"ifname": "wlo1"}]
)


class Net:
    """A switchable fake network: ``dev`` is where both families are routed."""

    def __init__(self, dev: str = "proton0") -> None:
        self.dev = dev
        self.probes = 0

    def __call__(self, argv: object, timeout_s: float) -> CommandResult:
        assert isinstance(argv, list)
        if argv[1] == "-d":
            return CommandResult(0, LINKS, "")
        self.probes += 1
        return CommandResult(0, json.dumps([{"dst": argv[-1], "dev": self.dev}]), "")


class FakeStream:
    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.chunks: list[bytes | BaseException | None] = []
        self.closed = 0

    def read_available(self) -> bytes | None:
        item = self.chunks.pop(0) if self.chunks else None
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed += 1


class Spawner:
    def __init__(self) -> None:
        self.streams: list[FakeStream] = []
        self.fail_next = 0

    def __call__(self) -> FakeStream:
        if self.fail_next:
            self.fail_next -= 1
            raise FileNotFoundError("ip")
        stream = FakeStream(fd=100 + len(self.streams))
        self.streams.append(stream)
        return stream

    @property
    def last(self) -> FakeStream:
        return self.streams[-1]


class Rig:
    def __init__(self, tmp_path: Path | None = None) -> None:
        self.config = Config()
        self.sched = FakeScheduler()
        self.net = Net()
        self.spawner = Spawner()
        probe = RouteProbe(VpnConfig(), ProbesConfig(), runner=self.net, clock=self.sched.clock)
        self.log = EventLog(tmp_path) if tmp_path is not None else None
        self.watcher = RouteWatcher(
            self.config,
            self.sched,
            probe=probe,
            spawner=self.spawner,
            clock=self.sched.clock,
            log=self.log,
        )
        self.readings: list[VpnReading] = []

    def start(self) -> None:
        self.watcher.start(self.readings.append)

    def event(self, data: bytes | None = b"2: wlo1: <...> state UP\n") -> None:
        self.spawner.last.chunks.append(data)
        self.sched.ready(self.spawner.last.fd)

    @property
    def states(self) -> list[VpnState]:
        return [r.state for r in self.readings]

    def events(self) -> list[dict[str, object]]:
        assert self.log is not None
        return [json.loads(line) for line in self.log.events_path.read_text().splitlines()]


def test_is_a_vpn_source() -> None:
    assert isinstance(Rig().watcher, VpnSource)


def test_start_probes_once_and_watches() -> None:
    rig = Rig()
    rig.start()
    assert rig.states == [VpnState.VPN]
    assert rig.watcher.last_trigger == "start"
    assert rig.watcher.running
    assert len(rig.sched.watches) == 1
    assert rig.sched.delays() == [HEALTHY_AFTER_S]  # only the health timer; no polling
    rig.sched.advance(HEALTHY_AFTER_S)
    assert rig.watcher.watcher_up
    assert rig.sched.delays() == []  # idle: no timers at all (R13)
    assert rig.states == [VpnState.VPN]  # first health mark does not re-probe


def test_start_twice_raises() -> None:
    rig = Rig()
    rig.start()
    with pytest.raises(RuntimeError):
        rig.start()


def test_burst_is_debounced_into_one_probe() -> None:
    rig = Rig()
    rig.start()
    rig.sched.advance(HEALTHY_AFTER_S)
    rig.net.dev = "wlo1"  # the VPN drops
    rig.event(b"a\nb\nc\n")
    rig.sched.advance(0.05)
    rig.event()
    rig.sched.advance(0.1)
    rig.event()
    assert rig.states == [VpnState.VPN]
    rig.sched.advance(DEBOUNCE_S)
    assert rig.states == [VpnState.VPN, VpnState.NO_VPN]
    assert rig.watcher.last_trigger == "route-change"
    assert rig.watcher.last_latency_s == pytest.approx(DEBOUNCE_S)
    assert rig.watcher.events_seen == 5
    rig.sched.advance(10)
    assert len(rig.readings) == 2  # inactive: nothing more
    rig.event()  # a later change starts a new burst
    rig.sched.advance(DEBOUNCE_S)
    assert len(rig.readings) == 3


def test_drop_reaction_is_within_budget() -> None:
    """R13: a VPN drop is reported < 2 s after the first route event (here: the debounce)."""
    rig = Rig()
    rig.start()
    rig.net.dev = "wlo1"
    rig.event()
    rig.sched.advance(DEBOUNCE_S)
    assert rig.states[-1] is VpnState.NO_VPN
    assert rig.watcher.last_latency_s is not None
    assert rig.watcher.last_latency_s < 2.0


def test_no_data_yet_keeps_the_watch() -> None:
    rig = Rig()
    rig.start()
    rig.event(None)
    assert len(rig.sched.watches) == 1
    rig.sched.advance(1)
    assert rig.watcher.events_seen == 0


def test_active_rechecks_and_inactive_stops() -> None:
    rig = Rig()
    rig.start()
    rig.sched.advance(HEALTHY_AFTER_S)
    rig.watcher.set_active(True)
    assert rig.watcher.last_trigger == "activate"
    assert len(rig.readings) == 2
    interval = rig.config.vpn.recheck_interval_s
    assert rig.sched.delays() == [interval]
    rig.sched.advance(interval * 3)
    assert len(rig.readings) == 5
    assert rig.watcher.last_trigger == "recheck"
    rig.watcher.set_active(True)  # no change: no extra probe
    assert len(rig.readings) == 5
    rig.watcher.set_active(False)
    assert rig.sched.delays() == []
    rig.sched.advance(60)
    assert len(rig.readings) == 5


def test_route_change_restarts_the_recheck_interval() -> None:
    rig = Rig()
    rig.start()
    rig.watcher.set_active(True)
    rig.sched.advance(HEALTHY_AFTER_S)
    rig.event()
    rig.sched.advance(DEBOUNCE_S)
    assert rig.sched.delays() == [pytest.approx(rig.config.vpn.recheck_interval_s)]


def test_set_active_before_start_only_remembers() -> None:
    rig = Rig()
    rig.watcher.set_active(True)
    assert rig.readings == []
    rig.start()
    assert rig.sched.delays() == [HEALTHY_AFTER_S, rig.config.vpn.recheck_interval_s]


def test_probe_now_without_start_does_nothing() -> None:
    assert Rig().watcher.probe_now("manual") is None


def test_monitor_death_restarts_with_backoff(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start()
    rig.sched.advance(HEALTHY_AFTER_S)
    delays = []
    for _ in range(9):
        rig.event(b"")  # EOF: the monitor died
        assert rig.spawner.last.closed == 1
        assert not rig.watcher.watcher_up
        delays.append(rig.sched.delays()[0])
        rig.sched.advance(delays[-1])  # restart; it dies again before proving itself
    assert delays[:4] == [RESTART_INITIAL_S, 1.0, 2.0, 4.0]
    assert max(delays) == RESTART_MAX_S
    assert len(rig.spawner.streams) == 10
    errors = [e for e in rig.events() if e["event"] == "vpn_watcher"]
    assert errors[0]["reason"] == "route monitor exited"
    assert errors[0]["level"] == "error"


def test_restart_reprobes_and_logs_recovery(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start()
    rig.sched.advance(HEALTHY_AFTER_S)
    rig.event(b"")
    rig.sched.advance(RESTART_INITIAL_S)
    before = len(rig.readings)
    rig.sched.advance(HEALTHY_AFTER_S)
    assert rig.watcher.watcher_up
    assert len(rig.readings) == before + 1
    assert rig.watcher.last_trigger == "watcher-restart"
    assert any(e["reason"] == "route monitor running again" for e in rig.events())


def test_data_proves_a_restarted_monitor_at_once() -> None:
    rig = Rig()
    rig.start()
    rig.sched.advance(HEALTHY_AFTER_S)
    rig.event(b"")
    rig.sched.advance(RESTART_INITIAL_S)
    rig.event()  # data before the health timer
    assert rig.watcher.watcher_up
    assert rig.watcher.last_trigger == "watcher-restart"


def test_backoff_resets_after_a_long_run() -> None:
    rig = Rig()
    rig.start()
    for _ in range(4):
        rig.event(b"")
        rig.sched.advance(rig.sched.delays()[0])
    rig.sched.advance(BACKOFF_RESET_S)
    rig.event(b"")
    assert rig.sched.delays() == [RESTART_INITIAL_S]


def test_read_error_counts_as_death() -> None:
    rig = Rig()
    rig.start()
    rig.event(OSError("EIO"))  # type: ignore[arg-type]
    assert rig.sched.watches == {}
    assert rig.sched.delays()[0] == RESTART_INITIAL_S


def test_cannot_spawn_is_retried_and_blue_degrades(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.spawner.fail_next = 100
    rig.start()
    assert rig.states == [VpnState.VPN]  # a fresh real reading is still honest
    rig.watcher.set_active(True)
    rig.sched.advance(rig.config.vpn.max_reading_age_s + rig.config.vpn.recheck_interval_s)
    assert rig.states[-1] is VpnState.UNKNOWN
    assert "route-change watcher down" in rig.readings[-1].reason
    assert rig.readings[-1].routes  # the routes are kept for the log
    rig.net.dev = "wlo1"
    rig.sched.advance(rig.config.vpn.recheck_interval_s)
    assert rig.states[-1] is VpnState.NO_VPN  # a negative reading is never hidden
    assert any("cannot start the route monitor" in str(e["reason"]) for e in rig.events())


def test_readings_are_logged_only_on_change(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.start()
    rig.watcher.set_active(True)
    rig.sched.advance(30)
    rig.net.dev = "wlo1"
    rig.event()
    rig.sched.advance(DEBOUNCE_S)
    readings = [e for e in rig.events() if e["event"] == "reading"]
    assert [e["inputs"]["vpn_state"] for e in readings] == ["vpn", "no_vpn"]  # type: ignore[index]
    assert readings[1]["inputs"]["trigger"] == "route-change"  # type: ignore[index]
    assert readings[1]["inputs"]["latency_ms"] == "200"  # type: ignore[index]
    assert "v4 wlo1 routed" in readings[1]["inputs"]["routes"]  # type: ignore[index]


def test_stop_cancels_everything_and_is_idempotent() -> None:
    rig = Rig()
    rig.start()
    rig.watcher.set_active(True)
    rig.event()
    rig.watcher.stop()
    rig.watcher.stop()
    assert rig.sched.timers == {}
    assert rig.sched.watches == {}
    assert rig.spawner.last.closed == 1
    assert not rig.watcher.running
    rig.sched.advance(60)
    assert len(rig.readings) == 2  # start + activate


def test_stop_during_restart_wait_does_not_respawn() -> None:
    rig = Rig()
    rig.start()
    rig.event(b"")
    rig.watcher.stop()
    rig.sched.advance(60)
    assert len(rig.spawner.streams) == 1


def test_stale_watch_callback_after_close_is_dropped() -> None:
    rig = Rig()
    rig.start()
    callback = next(iter(rig.sched.watches.values()))[1]
    rig.watcher.stop()
    assert callback() is False


# ---------------------------------------------------------------------------------------------
# The real subprocess stream (no `ip monitor`: a harmless shell stands in)
# ---------------------------------------------------------------------------------------------


class EchoStream(IpMonitorStream):
    ARGV = ("sh", "-c", "printf 'one\\ntwo\\n'")


class SleepStream(IpMonitorStream):
    ARGV = ("sleep", "30")


def _drain(stream: IpMonitorStream, deadline_s: float = 5.0) -> bytes:
    data, end = b"", time.monotonic() + deadline_s
    while time.monotonic() < end:
        chunk = stream.read_available()
        if chunk == b"":
            return data
        if chunk:
            data += chunk
        time.sleep(0.01)
    raise AssertionError("stream did not end")


def test_ip_monitor_stream_reads_until_eof() -> None:
    stream = EchoStream()
    assert stream.fd >= 0
    assert _drain(stream) == b"one\ntwo\n"
    stream.close()
    stream.close()


def test_ip_monitor_stream_close_terminates() -> None:
    stream = SleepStream()
    assert stream.read_available() is None  # non-blocking
    started = time.monotonic()
    stream.close()
    assert time.monotonic() - started < 2.0
    assert stream._proc.returncode is not None


def test_ip_monitor_argv_is_fixed() -> None:
    assert IpMonitorStream.ARGV == ("ip", "monitor", "route", "rule", "link")
    assert vpn.IpMonitorStream is IpMonitorStream
