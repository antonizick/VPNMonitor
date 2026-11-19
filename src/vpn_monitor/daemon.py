"""Wiring: watchers -> engine -> overlay, on the GLib main loop (spec A4, R10, R11, S3).

:class:`Daemon` owns the engine and connects the injected sources and sink to it. It has no
dependency on GLib or GTK (the scheduler, sources and sink are injected), so the whole pipeline is
tested with fakes. :func:`run` builds the real parts and runs the main loop.

After **every** input the daemon does the same three things: apply and log the Decision if it
changed, tell the VPN source whether re-checks are wanted (``engine.active``), and re-arm one timer
at ``engine.next_deadline()``. That timer is what turns a silent, stuck VPN watcher into red
(ADR-0013): without it a bar could stay blue after its reading went stale.

Fail-safe (spec R4/S6): an exception in any callback is logged and treated as an unknown VPN
reading (red); if the engine itself fails, a bar that was blue is forced red.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vpn_monitor import __version__
from vpn_monitor.config import Config, ConfigError, load_config
from vpn_monitor.control import AlreadyRunning, ControlServer, InstanceLock
from vpn_monitor.engine import Engine
from vpn_monitor.eventlog import EventLog
from vpn_monitor.mainloop import Handle, Scheduler
from vpn_monitor.model import (
    Decision,
    FocusEvent,
    FocusSource,
    Indicator,
    IndicatorSink,
    VpnReading,
    VpnSource,
    VpnState,
    reading_to_dict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

TIMER_SLACK_S = 0.001
"""Added to the engine's deadline so a rounded-down timer never fires just before it."""

SinkFactory = Callable[[Any], IndicatorSink]
ConfigLoader = Callable[[], Config]


class Daemon:
    """Connects a focus source and a VPN source to the engine and the engine to a sink."""

    def __init__(
        self,
        config: Config,
        *,
        focus: FocusSource,
        vpn: VpnSource,
        sink: IndicatorSink,
        scheduler: Scheduler,
        log: EventLog,
        clock: Callable[[], float] = time.monotonic,
        sink_factory: SinkFactory | None = None,
        config_loader: ConfigLoader | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._focus = focus
        self._vpn = vpn
        self._sink = sink
        self._scheduler = scheduler
        self._log = log
        self._clock = clock
        self._sink_factory = sink_factory
        self._config_loader = config_loader
        self._on_stop = on_stop

        self._engine = Engine.from_config(config, clock)
        self._last_focus: FocusEvent | None = None
        self._last_reading: VpnReading | None = None
        self._timer: Handle | None = None
        self._pause_timer: Handle | None = None
        self._pause_ends_at: float | None = None
        self._vpn_active = False
        self._started_at = clock()
        self._stopped = False

    # -- lifecycle ----------------------------------------------------------------------------

    def start(self) -> None:
        """Log the start-up facts and start both sources (focus delivers "no focus" first)."""
        source = str(self._config.source) if self._config.source else "built-in defaults"
        self._log.record(
            "daemon_started",
            reason=f"vpn-monitor {__version__} started",
            inputs={"config": source, "pid": str(os.getpid())},
        )
        for warning in self._config.warnings:
            self._log.record("config_warning", reason=warning)
        try:
            self._vpn.start(self._on_vpn)
        except Exception as exc:
            self._log.error("vpn_source_failed", f"start failed: {type(exc).__name__}: {exc}")
            self._fail_safe("vpn start")
        try:
            self._focus.start(self._on_focus)
        except Exception as exc:
            self._log.error("focus_source_failed", f"start failed: {type(exc).__name__}: {exc}")

    def stop(self, reason: str = "stopped") -> None:
        """Stop the sources, cancel timers and remove the bar. Safe to call twice."""
        if self._stopped:
            return
        self._stopped = True
        for handle in (self._timer, self._pause_timer):
            if handle is not None:
                self._scheduler.cancel(handle)
        self._timer = self._pause_timer = None
        for name, stop in (("vpn", self._vpn.stop), ("focus", self._focus.stop)):
            try:
                stop()
            except Exception as exc:
                self._log.error(f"{name}_source_failed", f"stop failed: {type(exc).__name__}")
        try:
            self._sink.close()  # removes the bar
        except Exception as exc:
            self._log.error("overlay_failed", f"close failed: {type(exc).__name__}: {exc}")
        self._log.record("daemon_stopped", reason=reason)

    def request_stop(self, reason: str) -> None:
        """Stop and ask the main loop to quit (SIGTERM / SIGINT)."""
        self.stop(reason)
        if self._on_stop is not None:
            self._on_stop()

    # -- inputs -------------------------------------------------------------------------------

    def _on_focus(self, event: FocusEvent) -> None:
        self._last_focus = event
        self._feed("focus", lambda: self._engine.on_focus(event))

    def _on_vpn(self, reading: VpnReading) -> None:
        self._last_reading = reading
        self._feed("vpn", lambda: self._engine.on_vpn(reading))

    def _on_timer(self) -> None:
        self._timer = None
        self._feed("timer", self._engine.tick)

    def _feed(self, source: str, step: Callable[[], Decision | None]) -> None:
        """Run one engine input, then apply the result, sync the VPN source and re-arm the timer."""
        if self._stopped:
            return
        try:
            decision = step()
        except Exception as exc:
            self._log.error(f"{source}_failed", f"{type(exc).__name__}: {exc}")
            self._fail_safe(source)
            return
        self._settle(decision)

    def _settle(self, decision: Decision | None) -> None:
        if decision is not None:
            self._apply(decision)
        active = self._engine.active
        if active != self._vpn_active:
            self._vpn_active = active
            try:
                self._vpn.set_active(active)
            except Exception as exc:
                self._log.error("vpn_source_failed", f"set_active failed: {type(exc).__name__}")
        self._arm_timer()

    def _apply(self, decision: Decision) -> None:
        self._log.decision(decision)
        try:
            self._sink.apply(decision)
        except Exception as exc:  # the overlay never raises, but the bar must not go stale
            self._log.error("overlay_failed", f"apply failed: {type(exc).__name__}: {exc}")

    def _arm_timer(self) -> None:
        if self._timer is not None:
            self._scheduler.cancel(self._timer)
            self._timer = None
        deadline = self._engine.next_deadline()
        if deadline is not None:
            delay = max(0.0, deadline - self._clock()) + TIMER_SLACK_S
            self._timer = self._scheduler.call_later(delay, self._on_timer)

    def _fail_safe(self, source: str) -> None:
        """Turn a failure into red: an unknown reading, or a forced red if the engine is broken."""
        now = self._clock()
        reading = VpnReading(VpnState.UNKNOWN, (), f"{source} failed", now)
        try:
            self._settle(self._engine.on_vpn(reading))
            return
        except Exception as exc:
            self._log.error("engine_failed", f"{type(exc).__name__}: {exc}")
        current = self._engine.decision
        if current.indicator is Indicator.BLUE:
            self._apply(Decision(Indicator.RED, current.monitor, f"{source} failed (fail-safe)"))

    # -- control commands ---------------------------------------------------------------------

    def handle_command(self, command: str) -> dict[str, Any]:
        """Run a control-socket command and return the reply payload."""
        if command == "pause":
            self.set_paused(True)
        elif command == "resume":
            self.set_paused(False)
        elif command == "toggle":
            self.set_paused(not self._engine.paused)
        elif command == "status":
            return self.status()
        else:  # pragma: no cover - the server only passes known commands
            raise ValueError(command)
        return {"paused": self._engine.paused}

    def set_paused(self, paused: bool) -> None:
        """Pause (bar hidden, no probing) or resume; honours ``pause.auto_resume_minutes``."""
        if self._pause_timer is not None:
            self._scheduler.cancel(self._pause_timer)
            self._pause_timer = None
        self._pause_ends_at = None
        minutes = self._config.pause.auto_resume_minutes
        if paused and minutes > 0:
            self._pause_ends_at = self._clock() + minutes * 60
            self._pause_timer = self._scheduler.call_later(minutes * 60, self._auto_resume)
        reason = "paused by command"
        if paused and minutes > 0:
            reason += f" (resumes after {minutes} min)"
        self._log.record("pause" if paused else "resume", reason=reason if paused else "resumed")
        self._feed("pause", lambda: self._engine.on_pause(paused))

    def _auto_resume(self) -> None:
        self._pause_timer = None
        self._pause_ends_at = None
        self._log.record("resume", reason="pause expired")
        self._feed("pause", lambda: self._engine.on_pause(False))

    def status(self) -> dict[str, Any]:
        """Everything ``vpn-monitor status`` shows. Window classes only, never titles (S1)."""
        now = self._clock()
        decision = self._engine.decision
        inputs = decision.inputs
        reading = self._last_reading
        result: dict[str, Any] = {
            "version": __version__,
            "pid": os.getpid(),
            "uptime_s": round(now - self._started_at, 1),
            "paused": self._engine.paused,
            "pause_resumes_in_s": (
                None if self._pause_ends_at is None else round(self._pause_ends_at - now, 1)
            ),
            "indicator": decision.indicator.value,
            "monitor": decision.monitor,
            "reason": decision.reason,
            "focus": {
                "class": inputs.get("class", ""),
                "match": inputs.get("match", "none"),
                "monitor": inputs.get("monitor", ""),
                "fullscreen": inputs.get("fullscreen", "false") == "true",
            },
            "reading": None,
            "config": str(self._config.source) if self._config.source else None,
        }
        if reading is not None:
            age = round(now - reading.timestamp, 1)
            result["reading"] = {**reading_to_dict(reading), "age_s": age}
        result["focus_watcher"] = _watcher_facts(self._focus, ("connected", "reconnects"))
        result["vpn_watcher"] = _watcher_facts(self._vpn, ("watcher_up", "last_trigger"))
        return result

    # -- configuration ------------------------------------------------------------------------

    def reload(self) -> None:
        """Re-read the config (SIGHUP). A broken file is logged and the old config kept."""
        if self._config_loader is None:
            return
        try:
            new = self._config_loader()
        except ConfigError as exc:
            self._log.error("config_reload_failed", f"kept the old config: {exc}")
            return
        old, self._config = self._config, new
        paused = self._engine.paused
        self._engine = Engine.from_config(new, self._clock)
        for warning in new.warnings:
            self._log.record("config_warning", reason=warning)
        if new.appearance != old.appearance and self._sink_factory is not None:
            try:
                self._sink.close()
                self._sink = self._sink_factory(new.appearance)
            except Exception as exc:
                self._log.error("overlay_failed", f"rebuild failed: {type(exc).__name__}: {exc}")
        if (new.vpn, new.probes) != (old.vpn, old.probes):
            self._log.record(
                "config_reload", reason="[vpn] and [probes] changes need a restart to take effect"
            )
        self._log.record("config_reload", reason="configuration reloaded")
        # Replay the inputs into the new engine; the new Decision always reaches the overlay.
        self._engine.on_pause(paused)
        steps: list[Callable[[], Decision | None]] = []
        if self._last_focus is not None:
            focus = self._last_focus
            steps.append(lambda: self._engine.on_focus(focus))
        if self._last_reading is not None:
            reading = self._last_reading
            steps.append(lambda: self._engine.on_vpn(reading))
        decision: Decision | None = None
        for step in steps:
            decision = step() or decision
        self._settle(decision if decision is not None else self._engine.decision)


def _watcher_facts(source: object, names: Sequence[str]) -> dict[str, Any]:
    """Optional status attributes of a real watcher (fakes simply have none)."""
    return {name: getattr(source, name) for name in names if hasattr(source, name)}


def run(  # pragma: no cover - live
    *, foreground: bool = False, argv: Sequence[str] = (), config_path: Any = None
) -> int:
    """Run the daemon until stopped; return the process exit code.

    ``argv`` is the original command line, needed to re-exec once with ``LD_PRELOAD`` set so that
    GTK can create layer-shell surfaces (it must happen before Gtk is imported).
    """
    argv = list(argv)
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"vpn-monitor: config error: {exc}", file=sys.stderr)
        return 2

    from vpn_monitor.overlay import ensure_layer_shell

    ensure_layer_shell(argv)  # re-execs once; everything below runs in the preloaded process

    lock = InstanceLock()
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        print(f"vpn-monitor: {exc} (see `vpn-monitor status`)", file=sys.stderr)
        return 1

    from gi.repository import GLib

    from vpn_monitor.focus import FocusWatcher
    from vpn_monitor.mainloop import GLibScheduler
    from vpn_monitor.overlay import GlowOverlay
    from vpn_monitor.vpn import RouteWatcher

    log = EventLog(max_bytes=config.log.max_bytes, backup_count=config.log.backup_count)
    loop: Any = GLib.MainLoop()
    scheduler = GLibScheduler()
    server: ControlServer | None = None
    daemon: Daemon | None = None
    try:
        try:
            sink: IndicatorSink = GlowOverlay(config.appearance, log=log)
        except RuntimeError as exc:
            log.error("overlay_unavailable", str(exc))
            print(f"vpn-monitor: {exc}", file=sys.stderr)
            return 1

        daemon = Daemon(
            config,
            focus=FocusWatcher(scheduler, log=log),
            vpn=RouteWatcher(config, scheduler, log=log),
            sink=sink,
            scheduler=scheduler,
            log=log,
            sink_factory=lambda appearance: GlowOverlay(appearance, log=log),
            config_loader=lambda: load_config(config_path),
            on_stop=loop.quit,
        )
        server = ControlServer(scheduler, daemon.handle_command, log=log)
        server.start()

        def stop(name: str) -> Callable[[], bool]:
            def handler() -> bool:
                assert daemon is not None
                daemon.request_stop(f"{name} received")
                return False

            return handler

        def hangup() -> bool:
            assert daemon is not None
            daemon.reload()
            return True

        for signum, name in ((signal.SIGTERM, "SIGTERM"), (signal.SIGINT, "SIGINT")):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, stop(name))
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, hangup)

        daemon.start()
        if foreground:
            print(f"vpn-monitor {__version__} running (Ctrl-C to stop)", file=sys.stderr)
        loop.run()
        return 0
    finally:
        if daemon is not None:
            daemon.stop("main loop ended")
        if server is not None:
            server.stop()
        lock.release()
        log.close()
