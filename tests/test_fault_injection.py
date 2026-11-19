"""End-to-end fault injection (Phase 08, threat model T-rows): every fault ends red or hidden.

Each test runs the real :class:`Daemon` with the **real** component under attack (RouteWatcher,
RouteProbe, FocusWatcher, GlowOverlay or EventLog) and fakes only at the operating-system edge
(the ``ip`` runner, the socket, the GTK backend, the clock). The assertion is always the same
shape: the bar was blue, the fault happens, the bar is red or hidden and never blue again until a
fresh positive reading, and the fault is logged.
"""

from __future__ import annotations

import ast
import json
import os
import socket
import subprocess
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor.config import Config, ConfigError, parse_config
from vpn_monitor.daemon import Daemon
from vpn_monitor.eventlog import EventLog
from vpn_monitor.fakes import FakeFocusSource, FakeScheduler, FakeVpnSource, RecordingSink
from vpn_monitor.focus import FocusWatcher
from vpn_monitor.mainloop import boot_clock
from vpn_monitor.model import FamilyRoute, FocusEvent, Indicator, RouteKind, VpnReading, VpnState
from vpn_monitor.overlay import Bar, GlowOverlay
from vpn_monitor.vpn import CommandResult, RouteProbe, RouteWatcher, run_command

SRC = Path(__file__).resolve().parents[1] / "src" / "vpn_monitor"

BRAVE = FocusEvent("brave-browser", "0x1", "HDMI-A-1")
FOOT = FocusEvent("foot", "0x2", "HDMI-A-1")
LINKS = json.dumps(
    [{"ifname": "proton0", "linkinfo": {"info_kind": "wireguard"}}, {"ifname": "wlo1"}]
)


def events(log: EventLog) -> list[dict[str, Any]]:
    return [json.loads(x) for x in log.events_path.read_text().splitlines()]


def never_blue_after(sink: RecordingSink, index: int) -> bool:
    return all(d.indicator is not Indicator.BLUE for d in sink.decisions[index:])


# ---------------------------------------------------------------------------------------------
# The VPN path: real RouteWatcher + RouteProbe, fake `ip`
# ---------------------------------------------------------------------------------------------


class Ip:
    """Fake `ip`: routes both families via ``dev``; ``fault`` makes `ip route get` misbehave."""

    def __init__(self) -> None:
        self.dev = "proton0"
        self.fault: BaseException | None = None

    def __call__(self, argv: Sequence[str], timeout_s: float) -> CommandResult:
        if argv[1] == "-d":
            return CommandResult(0, LINKS, "")
        if self.fault is not None:
            raise self.fault
        return CommandResult(0, json.dumps([{"dst": argv[-1], "dev": self.dev}]), "")


class Stream:
    """Fake `ip monitor` pipe: ``chunks`` is what the next reads return (b"" = exited)."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.chunks: list[bytes | None] = []

    def read_available(self) -> bytes | None:
        return self.chunks.pop(0) if self.chunks else None

    def close(self) -> None:
        pass


class VpnRig:
    def __init__(self, tmp: Path) -> None:
        self.config = Config()
        self.scheduler = FakeScheduler()
        self.ip = Ip()
        self.streams: list[Stream] = []
        self.spawn_fails = False
        self.log = EventLog(tmp)
        self.sink = RecordingSink()
        self.focus = FakeFocusSource()
        clock = self.scheduler.clock
        probe = RouteProbe(self.config.vpn, self.config.probes, runner=self.ip, clock=clock)
        self.watcher = RouteWatcher(
            self.config, self.scheduler, probe=probe, spawner=self.spawn, clock=clock, log=self.log
        )
        self.daemon = Daemon(
            self.config,
            focus=self.focus,
            vpn=self.watcher,
            sink=self.sink,
            scheduler=self.scheduler,
            log=self.log,
            clock=clock,
        )

    def spawn(self) -> Stream:
        if self.spawn_fails:
            raise FileNotFoundError("ip")
        stream = Stream(fd=200 + len(self.streams))
        self.streams.append(stream)
        return stream

    def route_change(self) -> None:
        stream = self.streams[-1]
        stream.chunks.append(b"10.2.0.0/16 dev proton0 table 245447468\n")
        self.scheduler.ready(stream.fd)

    def blue(self) -> int:
        """Start, focus Brave and check the bar is blue; return the index of that decision."""
        self.daemon.start()
        self.scheduler.advance(3)  # the route monitor proves itself (healthy)
        self.focus.emit(BRAVE)
        assert self.sink.last is not None
        assert self.sink.last.indicator is Indicator.BLUE
        return len(self.sink.decisions)

    @property
    def shown(self) -> Indicator | None:
        return self.sink.last.indicator if self.sink.last else None


@pytest.fixture
def vpn_rig(tmp_path: Path) -> Iterator[VpnRig]:
    rig = VpnRig(tmp_path)
    yield rig
    rig.log.close()


def test_ip_route_get_hangs_turns_red_and_is_logged(vpn_rig: VpnRig) -> None:
    mark = vpn_rig.blue()
    vpn_rig.ip.fault = subprocess.TimeoutExpired(["ip"], 1.0)
    vpn_rig.route_change()
    vpn_rig.scheduler.advance(0.3)  # debounce
    assert vpn_rig.shown is Indicator.RED
    assert never_blue_after(vpn_rig.sink, mark)
    readings = [e for e in events(vpn_rig.log) if e["event"] == "reading"]
    assert "timed out" in readings[-1]["reason"]
    assert readings[-1]["inputs"]["vpn_state"] == "unknown"


def test_ip_route_get_hangs_during_a_recheck_turns_red(vpn_rig: VpnRig) -> None:
    mark = vpn_rig.blue()
    vpn_rig.ip.fault = subprocess.TimeoutExpired(["ip"], 1.0)
    vpn_rig.scheduler.advance(vpn_rig.config.vpn.recheck_interval_s + 0.1)
    assert vpn_rig.shown is Indicator.RED
    assert never_blue_after(vpn_rig.sink, mark)


def test_ip_disappears_turns_red(vpn_rig: VpnRig) -> None:
    mark = vpn_rig.blue()
    vpn_rig.ip.fault = FileNotFoundError("ip")
    vpn_rig.route_change()
    vpn_rig.scheduler.advance(0.3)
    assert vpn_rig.shown is Indicator.RED
    assert never_blue_after(vpn_rig.sink, mark)


def test_ip_monitor_dies_for_good_turns_red_within_the_reading_age(vpn_rig: VpnRig) -> None:
    mark = vpn_rig.blue()
    vpn_rig.spawn_fails = True
    vpn_rig.streams[-1].chunks.append(b"")  # `ip monitor` exits; every restart fails
    vpn_rig.scheduler.ready(vpn_rig.streams[-1].fd)
    limit = vpn_rig.config.vpn.max_reading_age_s + vpn_rig.config.vpn.recheck_interval_s
    vpn_rig.scheduler.advance(limit + 0.1)
    assert vpn_rig.shown is Indicator.RED
    assert never_blue_after(vpn_rig.sink, mark)
    logged = events(vpn_rig.log)
    assert any(e["event"] == "vpn_watcher" and e["level"] == "error" for e in logged)
    assert any("watcher down" in e["reason"] for e in logged if e["event"] == "reading")
    # and it stays red while the monitor is still down, however long it takes
    vpn_rig.scheduler.advance(120)
    assert vpn_rig.shown is Indicator.RED


def test_ip_monitor_recovers_and_blue_needs_a_fresh_probe(vpn_rig: VpnRig) -> None:
    vpn_rig.blue()
    vpn_rig.spawn_fails = True
    vpn_rig.streams[-1].chunks.append(b"")
    vpn_rig.scheduler.ready(vpn_rig.streams[-1].fd)
    vpn_rig.scheduler.advance(20)
    assert vpn_rig.shown is Indicator.RED
    vpn_rig.spawn_fails = False
    vpn_rig.scheduler.advance(40)  # back-off restart, healthy, re-probe
    assert vpn_rig.shown is Indicator.BLUE


def test_real_hanging_command_is_cut_off_by_the_timeout() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_command(["sleep", "10"], 0.2)
    assert time.monotonic() - started < 2.0  # the main loop is blocked at most ~probe_timeout_s


def test_nothing_runs_nmcli() -> None:
    """ADR-0015 dropped NetworkManager; no string literal in the package names `nmcli`."""
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                assert "nmcli" not in node.value, path.name


# ---------------------------------------------------------------------------------------------
# The focus path: real FocusWatcher over a socketpair
# ---------------------------------------------------------------------------------------------


class Socket2:
    def __init__(self) -> None:
        self.server, self.client = socket.socketpair()
        self.client.setblocking(False)

    @property
    def fd(self) -> int:
        return self.client.fileno()

    def read_available(self) -> bytes | None:
        try:
            return self.client.recv(65536)
        except BlockingIOError:
            return None

    def close(self) -> None:
        self.client.close()
        self.server.close()


class Query:
    def __init__(self) -> None:
        self.answer = BRAVE

    def active_focus(self) -> FocusEvent:
        return self.answer

    def invalidate_monitors(self) -> None:
        pass


def test_hyprland_socket_closes_mid_line_hides_and_recovers(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    log = EventLog(tmp_path)
    sockets: list[Socket2] = []

    def spawn() -> Socket2:
        sockets.append(Socket2())
        return sockets[-1]

    query = Query()
    focus = FocusWatcher(scheduler, spawner=spawn, query=query, clock=scheduler.clock, log=log)
    vpn = FakeVpnSource()
    sink = RecordingSink()
    daemon = Daemon(
        Config(), focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log,
        clock=scheduler.clock,
    )  # fmt: skip
    daemon.start()
    routes = (FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True),)
    vpn.emit(VpnReading(VpnState.VPN, routes, "v4 via proton0", scheduler.now))
    assert sink.last is not None
    assert sink.last.indicator is Indicator.BLUE

    # Hyprland dies half-way through a line: the fragment must not be parsed as a focus change.
    query.answer = FOOT
    sockets[-1].server.sendall(b"activewindow>>foo")
    sockets[-1].server.close()
    scheduler.ready(sockets[-1].fd)
    scheduler.ready(sockets[-1].fd)
    assert sink.last.indicator is Indicator.HIDDEN  # "no focus" while disconnected
    assert any(e["event"] == "focus_watcher" for e in events(log))

    # Back: the initial state is re-read and the bar returns.
    query.answer = BRAVE
    vpn.emit(VpnReading(VpnState.VPN, routes, "v4 via proton0", scheduler.now))
    scheduler.advance(1)
    assert len(sockets) == 2
    assert sink.last.indicator is Indicator.BLUE
    daemon.stop()
    for s in sockets:
        s.close()
    log.close()


# ---------------------------------------------------------------------------------------------
# The overlay: real GlowOverlay, failing backend
# ---------------------------------------------------------------------------------------------


class FlakyBackend:
    """Surface creation raises while ``broken``; otherwise records created surfaces."""

    def __init__(self) -> None:
        self.broken = True
        self.created: list[str] = []

    def monitors(self) -> set[str]:
        return {"HDMI-A-1"}

    def create(self, monitor: str, bar: Bar) -> Any:
        if self.broken:
            raise RuntimeError("cannot create layer surface")
        self.created.append(monitor)
        return _Surface()

    def watch_monitors(self, callback: Callable[[set[str]], None]) -> None:
        pass

    def close(self) -> None:
        pass


class _Surface:
    def map(self) -> None: ...
    def unmap(self) -> None: ...
    def queue_draw(self) -> None: ...
    def start_ticks(self) -> None: ...
    def destroy(self) -> None: ...


def test_overlay_surface_creation_fails_daemon_keeps_running(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    log = EventLog(tmp_path)
    backend = FlakyBackend()
    overlay = GlowOverlay(Config().appearance, backend=backend, log=log, clock=scheduler.clock)
    focus, vpn = FakeFocusSource(), FakeVpnSource()
    daemon = Daemon(
        Config(), focus=focus, vpn=vpn, sink=overlay, scheduler=scheduler, log=log,
        clock=scheduler.clock,
    )  # fmt: skip
    daemon.start()
    routes = (FamilyRoute(4, "192.0.2.1", "wlo1", RouteKind.ROUTED, False),)
    vpn.emit(VpnReading(VpnState.NO_VPN, routes, "v4 via wlo1", scheduler.now))
    focus.emit(BRAVE)  # wants red; the surface cannot be made, so nothing is drawn
    logged = events(log)
    assert any(e["event"] == "overlay_error" for e in logged)
    assert daemon.status()["indicator"] == "red"  # the decision is still right and logged
    backend.broken = False
    focus.emit(FOOT)
    focus.emit(BRAVE)
    assert backend.created == ["HDMI-A-1"]  # recovers on the next decision
    daemon.stop()
    log.close()


# ---------------------------------------------------------------------------------------------
# The log: unwritable directory, failing writes
# ---------------------------------------------------------------------------------------------

needs_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")


@needs_non_root
def test_unwritable_log_directory_falls_back_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    locked = tmp_path / "state"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        log = EventLog(locked / "vpn-monitor")
        assert log.degraded is not None
        scheduler = FakeScheduler()
        focus, vpn, sink = FakeFocusSource(), FakeVpnSource(), RecordingSink()
        daemon = Daemon(
            Config(), focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log,
            clock=scheduler.clock,
        )  # fmt: skip
        daemon.start()
        focus.emit(BRAVE)
        assert sink.last is not None
        assert sink.last.indicator is Indicator.RED  # the indicator works without its log
        err = capsys.readouterr().err
        assert "log_degraded" in err
        assert '"decision":"red"' in err  # events reach the journal instead
        daemon.stop()
        log.close()
    finally:
        locked.chmod(0o700)


@needs_non_root
def test_read_only_existing_log_files_fall_back_to_stderr(tmp_path: Path) -> None:
    EventLog(tmp_path).close()
    for name in ("events.jsonl", "vpn-monitor.log"):
        (tmp_path / name).chmod(0o400)
    log = EventLog(tmp_path)
    assert log.degraded is not None
    log.record("probe", reason="still works")
    log.close()


def test_failing_writes_are_reported_once_and_never_raise(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    log = EventLog(tmp_path)
    scheduler = FakeScheduler()
    focus, vpn, sink = FakeFocusSource(), FakeVpnSource(), RecordingSink()
    daemon = Daemon(
        Config(), focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log,
        clock=scheduler.clock,
    )  # fmt: skip
    daemon.start()

    def full(*_args: object) -> None:
        raise OSError(28, "No space left on device")

    for logger in (log._human, log._events):
        for handler in logger.handlers:
            monkeypatch.setattr(handler, "emit", _failing_emit(handler, full))
    focus.emit(BRAVE)
    focus.emit(FOOT)
    focus.emit(BRAVE)
    assert sink.last is not None
    assert sink.last.indicator is Indicator.RED
    err = capsys.readouterr().err
    assert err.count("No space left on device") == 2  # once per file, not once per event
    daemon.stop()
    log.close()


def _failing_emit(handler: Any, fail: Callable[..., None]) -> Callable[[Any], None]:
    def emit(record: Any) -> None:
        try:
            fail()
        except OSError:
            handler.handleError(record)

    return emit


def test_log_files_are_private(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    log.record("probe", reason="x")
    for path in (log.events_path, log.human_path):
        assert path.stat().st_mode & 0o777 == 0o600
    log.close()


def test_existing_loose_log_files_are_tightened(tmp_path: Path) -> None:
    for name in ("events.jsonl", "vpn-monitor.log"):
        (tmp_path / name).write_text("")
        (tmp_path / name).chmod(0o644)
    log = EventLog(tmp_path)
    for path in (log.events_path, log.human_path):
        assert path.stat().st_mode & 0o777 == 0o600
    log.close()


def test_rotated_files_are_private(tmp_path: Path) -> None:
    log = EventLog(tmp_path, max_bytes=10_000, backup_count=2)
    for i in range(400):
        log.record("probe", reason=f"line {i} " + "x" * 40)
    rotated = sorted(tmp_path.glob("*.jsonl*"))
    assert len(rotated) == 3
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in rotated)
    assert all(p.stat().st_size <= 10_000 + 200 for p in rotated)  # size is bounded
    log.close()


# ---------------------------------------------------------------------------------------------
# Suspend / resume and clock jumps
# ---------------------------------------------------------------------------------------------


class SuspendClocks:
    """Two clocks as the kernel keeps them: ``monotonic`` stops in suspend, ``boot`` does not.

    The GLib timers (the FakeScheduler) run on the monotonic clock; the engine and the readings
    use ``boot`` (ADR-0019).
    """

    def __init__(self, scheduler: FakeScheduler) -> None:
        self.scheduler = scheduler
        self.slept = 0.0

    def boot(self) -> float:
        return self.scheduler.now + self.slept

    def suspend(self, seconds: float) -> None:
        self.slept += seconds


def test_resume_after_suspend_is_red_at_the_first_wake_up(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    clocks = SuspendClocks(scheduler)
    log = EventLog(tmp_path)
    focus, vpn, sink = FakeFocusSource(), FakeVpnSource(), RecordingSink()
    daemon = Daemon(
        Config(), focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log, clock=clocks.boot
    )
    daemon.start()
    routes = (FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True),)
    vpn.emit(VpnReading(VpnState.VPN, routes, "v4 via proton0", clocks.boot()))
    focus.emit(BRAVE)
    assert sink.last is not None
    assert sink.last.indicator is Indicator.BLUE
    mark = len(sink.decisions)

    clocks.suspend(3600)  # the lid closes; monotonic (and every GLib timer) stands still
    focus.emit(FocusEvent("brave-browser", "0x9", "HDMI-A-1"))  # first event after resume
    assert sink.last.indicator is Indicator.RED
    assert "stale" in sink.last.reason
    assert never_blue_after(sink, mark)
    daemon.stop()
    log.close()


def test_resume_with_no_event_is_red_when_the_pending_timer_fires(tmp_path: Path) -> None:
    scheduler = FakeScheduler()
    clocks = SuspendClocks(scheduler)
    log = EventLog(tmp_path)
    focus, vpn, sink = FakeFocusSource(), FakeVpnSource(), RecordingSink()
    config = Config()
    daemon = Daemon(
        config, focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log, clock=clocks.boot
    )
    daemon.start()
    routes = (FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True),)
    vpn.emit(VpnReading(VpnState.VPN, routes, "v4 via proton0", clocks.boot()))
    focus.emit(BRAVE)
    mark = len(sink.decisions)
    clocks.suspend(3600)
    # Nothing happens after resume except the deadline timer armed before the suspend.
    scheduler.advance(config.vpn.max_reading_age_s + 0.1)
    assert sink.last is not None
    assert sink.last.indicator is Indicator.RED
    assert never_blue_after(sink, mark)
    daemon.stop()
    log.close()


def test_boot_clock_counts_suspend_and_never_runs_behind_monotonic() -> None:
    boot, mono = boot_clock(), time.monotonic()
    assert boot == pytest.approx(time.clock_gettime(time.CLOCK_BOOTTIME), abs=0.05)
    assert boot >= mono - 0.05


def test_the_daemon_and_the_vpn_watcher_share_the_boot_clock() -> None:
    """A reading timestamp and the engine's ``now`` must come from the same clock."""
    import inspect

    daemon_default = inspect.signature(Daemon.__init__).parameters["clock"].default
    watcher_default = inspect.signature(RouteWatcher.__init__).parameters["clock"].default
    probe_default = inspect.signature(RouteProbe.__init__).parameters["clock"].default
    assert daemon_default is watcher_default is probe_default is boot_clock


def test_wall_clock_jumps_only_change_log_timestamps(tmp_path: Path) -> None:
    """Decisions never read the wall clock: a jump of the date changes nothing but ``ts``."""
    from datetime import datetime, timedelta, timezone

    wall = [datetime(2026, 11, 19, 10, 0, tzinfo=timezone(timedelta(hours=-6)))]
    log = EventLog(tmp_path, wall_clock=lambda: wall[0])
    scheduler = FakeScheduler()
    focus, vpn, sink = FakeFocusSource(), FakeVpnSource(), RecordingSink()
    daemon = Daemon(
        Config(), focus=focus, vpn=vpn, sink=sink, scheduler=scheduler, log=log,
        clock=scheduler.clock,
    )  # fmt: skip
    daemon.start()
    routes = (FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, True),)
    vpn.emit(VpnReading(VpnState.VPN, routes, "v4 via proton0", scheduler.now))
    focus.emit(BRAVE)
    wall[0] -= timedelta(days=400)  # NTP / manual clock change backwards
    focus.emit(FOOT)
    focus.emit(BRAVE)
    assert sink.last is not None
    assert sink.last.indicator is Indicator.BLUE  # still fresh by the boot clock
    assert events(log)[-1]["ts"].startswith("2025-")
    daemon.stop()
    log.close()


def test_config_never_allows_a_red_delay() -> None:
    """S6: a red confirmation delay would keep a false blue on screen."""
    with pytest.raises(ConfigError, match="red_confirm_ms"):
        parse_config({"indicator": {"red_confirm_ms": 500}})
