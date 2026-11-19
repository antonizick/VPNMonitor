"""Command-line interface (spec R10): the daemon, its control commands, logs and diagnostics."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vpn_monitor import __version__
from vpn_monitor.model import (
    Decision,
    FocusEvent,
    Indicator,
    VpnReading,
    VpnState,
    reading_to_dict,
)

if TYPE_CHECKING:
    from vpn_monitor.browsers import BrowserMatcher
    from vpn_monitor.config import Config

CONFIG_ERROR_EXIT = 2
HYPRLAND_EXIT = 2
NOT_RUNNING_EXIT = 3
CONTROL_EXIT = 1
LOG_TAIL_LINES = 200
PROBE_EXIT = {VpnState.VPN: 0, VpnState.NO_VPN: 1, VpnState.UNKNOWN: 3}
"""``vpn-monitor probe`` exit codes: 0 VPN, 1 not through a VPN, 3 unknown."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for ``vpn-monitor``."""
    parser = argparse.ArgumentParser(
        prog="vpn-monitor",
        description="Show whether the focused browser's traffic is routed through a VPN.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = sub.add_parser("run", help="run the daemon")
    run.add_argument(
        "--foreground",
        action="store_true",
        help="print a start-up line to stderr (the daemon never forks; systemd supervises it)",
    )
    run.add_argument("--config", type=Path, help="config file (default: the usual location)")
    sub.add_parser("pause", help="hide the bar and stop probing")
    sub.add_parser("resume", help="resume after a pause")
    sub.add_parser("toggle", help="pause if running, resume if paused")
    status = sub.add_parser("status", help="show daemon state")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    log = sub.add_parser("log", help="show the log")
    log.add_argument("-f", "--follow", action="store_true", help="follow new entries")
    log.add_argument("--events", action="store_true", help="show the JSONL event log")

    probe = sub.add_parser(
        "probe",
        help="check the VPN routes now and explain the verdict",
        description="Look up the route internet traffic takes for IPv4 and IPv6 (nothing is "
        "sent) and say whether it goes through a VPN. Exit code: 0 VPN, 1 not through a VPN, "
        "3 unknown.",
    )
    probe.add_argument("--json", action="store_true", help="machine-readable output")
    probe.add_argument(
        "--watch",
        action="store_true",
        help="keep running and print every change, with the reaction time (Ctrl-C to stop)",
    )
    probe.add_argument(
        "--log", action="store_true", help="with --watch: also write readings to the event log"
    )
    probe.add_argument("--config", type=Path, help="config file (default: the usual location)")

    focus = sub.add_parser(
        "focus",
        help="show the focused window class and whether it is a browser (never titles)",
        description="Print the focused window's class, the browser rule it matched and its "
        "monitor. Window titles are never read or shown. Exit code: 0 a browser is focused, "
        "1 something else (or nothing) is, 2 Hyprland is not running or the config is bad.",
    )
    focus.add_argument("--json", action="store_true", help="machine-readable output")
    focus.add_argument(
        "--watch", action="store_true", help="keep running and print every focus change"
    )
    focus.add_argument(
        "--log", action="store_true", help="with --watch: also write focus changes to the event log"
    )
    focus.add_argument("--config", type=Path, help="config file (default: the usual location)")

    preview = sub.add_parser(
        "preview",
        help="show the glow bar directly (no VPN or focus logic), for reviewing the look",
        description="Draw the bar on one monitor: red, blue, or cycling red, blue, hidden every "
        "2 s. Click-through like the real thing. Prints the draw counter on every fade and at "
        "exit (0 draws after a fade means no idle redraws).",
    )
    preview.add_argument("mode", choices=PREVIEW_MODES, help="what to show")
    preview.add_argument(
        "--seconds", type=float, default=0.0, help="exit after N seconds (default: until Ctrl-C)"
    )
    preview.add_argument("--monitor", help="connector name (default: the focused monitor)")
    preview.add_argument(
        "--backdrop",
        action="store_true",
        help="also open a plain fullscreen window under the bar (neutral screenshots, fullscreen "
        "check); it takes keyboard focus while open",
    )
    preview.add_argument(
        "--log", action="store_true", help="also write overlay events to the event log"
    )
    preview.add_argument("--config", type=Path, help="config file (default: the usual location)")
    return parser


PREVIEW_MODES = ("red", "blue", "cycle")
PREVIEW_STEP_S = 2.0
"""Seconds per step in ``preview cycle``."""


_HEADLINE = {
    VpnState.VPN: "VPN: internet traffic is routed through a VPN",
    VpnState.NO_VPN: "NO VPN: internet traffic is not (fully) routed through a VPN",
    VpnState.UNKNOWN: "UNKNOWN: the routes could not be checked (shown as red)",
}


def format_reading(reading: VpnReading) -> str:
    """Human form of a reading: headline, one line per family, then the reason."""
    lines = [_HEADLINE[reading.state]]
    for r in reading.routes:
        tag = "VPN" if r.is_vpn else ""
        dev = r.egress_interface or "-"
        lines.append(f"  IPv{r.family}  {r.kind.value:<11} {dev:<16} {tag}".rstrip())
    lines.append(f"  why: {reading.reason}")
    return "\n".join(lines)


def _probe(args: argparse.Namespace) -> int:
    from vpn_monitor.config import ConfigError, load_config

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"vpn-monitor: config error: {exc}", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    if args.watch:
        return _probe_watch(args, config)

    from vpn_monitor.vpn import read_vpn_state

    reading = read_vpn_state(config)
    if args.json:
        print(json.dumps(reading_to_dict(reading), indent=2))
    else:
        print(format_reading(reading))
    return PROBE_EXIT[reading.state]


def _probe_watch(args: argparse.Namespace, config: Config) -> int:  # pragma: no cover - live
    import signal

    from gi.repository import GLib

    from vpn_monitor.eventlog import EventLog
    from vpn_monitor.mainloop import GLibScheduler
    from vpn_monitor.vpn import RouteWatcher

    log = EventLog() if args.log else None
    loop: Any = GLib.MainLoop()
    last: list[tuple[VpnState, str]] = []

    def on_reading(reading: VpnReading) -> None:
        key = (reading.state, reading.reason)
        if last and last[-1] == key:
            return
        last.append(key)
        stamp = time.strftime("%H:%M:%S")
        latency = watcher.last_latency_s
        if args.json:
            row = reading_to_dict(reading)
            row.update(time=stamp, trigger=watcher.last_trigger, latency_s=latency)
            print(json.dumps(row), flush=True)
            return
        extra = f", {latency * 1000:.0f} ms after the first route event" if latency else ""
        print(f"[{stamp}] ({watcher.last_trigger}{extra})", flush=True)
        print(format_reading(reading), flush=True)

    def quit_loop() -> bool:
        loop.quit()
        return False

    watcher = RouteWatcher(config, GLibScheduler(), log=log)
    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, quit_loop)
    watcher.start(on_reading)
    watcher.set_active(True)
    try:
        loop.run()
    finally:
        watcher.stop()
        if log is not None:
            log.close()
    return 0


def focus_row(event: FocusEvent, matcher: BrowserMatcher) -> dict[str, Any]:
    """JSON-friendly form of a focus event with the browser rule it matched (no title)."""
    result = matcher.match(event.window_class)
    return {
        "class": event.window_class,
        "browser": result.matched,
        "rule": result.rule,
        "monitor": event.monitor,
        "fullscreen": event.fullscreen,
    }


def format_focus(row: dict[str, Any]) -> str:
    """One human line for a focus row."""
    if not row["class"]:
        return "no window focused"
    verdict = f"BROWSER ({row['rule']})" if row["browser"] else "not a browser"
    fullscreen = "  fullscreen" if row["fullscreen"] else ""
    return f"{row['class']}  {verdict}  monitor={row['monitor'] or '?'}{fullscreen}"


def _focus(args: argparse.Namespace) -> int:
    from vpn_monitor.browsers import BrowserMatcher
    from vpn_monitor.config import ConfigError, load_config
    from vpn_monitor.focus import HyprlandClient, HyprlandError, HyprlandNotRunning, locate_sockets

    try:
        config = load_config(args.config)
        matcher = BrowserMatcher(config.browsers.classes, config.browsers.patterns)
        locate_sockets()
    except ConfigError as exc:
        print(f"vpn-monitor: config error: {exc}", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    except HyprlandNotRunning as exc:
        print(f"vpn-monitor: {exc}", file=sys.stderr)
        return HYPRLAND_EXIT
    if args.watch:
        return _focus_watch(args, matcher)
    try:
        event = HyprlandClient().active_focus()
    except (OSError, HyprlandError, HyprlandNotRunning) as exc:
        print(f"vpn-monitor: cannot read the focused window: {exc}", file=sys.stderr)
        return HYPRLAND_EXIT
    row = focus_row(event, matcher)
    print(json.dumps(row) if args.json else format_focus(row))
    return 0 if row["browser"] else 1


def _focus_watch(args: argparse.Namespace, matcher: BrowserMatcher) -> int:  # pragma: no cover
    import signal

    from gi.repository import GLib

    from vpn_monitor.eventlog import EventLog
    from vpn_monitor.focus import FocusWatcher
    from vpn_monitor.mainloop import GLibScheduler

    log = EventLog() if args.log else None
    loop: Any = GLib.MainLoop()

    def on_focus(event: FocusEvent) -> None:
        row = focus_row(event, matcher)
        latency = watcher.last_latency_s
        stamp = time.strftime("%H:%M:%S")
        if args.json:
            row.update(time=stamp, latency_ms=None if latency is None else latency * 1000)
            print(json.dumps(row), flush=True)
            return
        extra = f"  ({latency * 1000:.1f} ms)" if latency is not None else ""
        print(f"[{stamp}] {format_focus(row)}{extra}", flush=True)

    def quit_loop() -> bool:
        loop.quit()
        return False

    watcher = FocusWatcher(GLibScheduler(), log=log)
    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, quit_loop)
    watcher.start(on_focus)
    try:
        loop.run()
    finally:
        watcher.stop()
        if log is not None:
            log.close()
    return 0


def focused_monitor() -> str | None:
    """Name of Hyprland's focused monitor, or ``None`` if Hyprland cannot say."""
    from vpn_monitor.focus import HyprlandError, HyprlandNotRunning, socket_request

    try:
        data = json.loads(socket_request("j/monitors"))
    except (OSError, ValueError, HyprlandError, HyprlandNotRunning):
        return None
    if not isinstance(data, list):
        return None
    for monitor in data:
        if isinstance(monitor, dict) and monitor.get("focused") and monitor.get("name"):
            return str(monitor["name"])
    return None


def preview_steps(mode: str) -> tuple[Indicator, ...]:
    """The indicators ``preview`` shows, in order (``cycle`` repeats them)."""
    if mode == "red":
        return (Indicator.RED,)
    if mode == "blue":
        return (Indicator.BLUE,)
    return (Indicator.RED, Indicator.BLUE, Indicator.HIDDEN)


def _preview(args: argparse.Namespace, argv: Sequence[str]) -> int:  # pragma: no cover - live
    from vpn_monitor.config import ConfigError, load_config
    from vpn_monitor.overlay import ensure_layer_shell

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"vpn-monitor: config error: {exc}", file=sys.stderr)
        return CONFIG_ERROR_EXIT
    ensure_layer_shell(argv)  # re-execs once with LD_PRELOAD; returns if already done

    import signal

    from gi.repository import GLib

    from vpn_monitor.eventlog import EventLog
    from vpn_monitor.overlay import GlowOverlay, GtkBackend

    try:
        backend = GtkBackend()
    except RuntimeError as exc:
        print(f"vpn-monitor: {exc}", file=sys.stderr)
        return 1
    monitor = args.monitor or focused_monitor() or min(backend.monitors(), default="")
    if monitor not in backend.monitors():
        known = ", ".join(sorted(backend.monitors())) or "none"
        print(f"vpn-monitor: no monitor {monitor!r} (known: {known})", file=sys.stderr)
        return 1
    log = EventLog() if args.log else None
    # Each settled fade is reported: the counter must not move between these lines while idle.
    overlay = GlowOverlay(
        config.appearance,
        backend=backend,
        log=log,
        on_settled=lambda bar: report(f"fade finished ({bar.indicator.value})"),
    )
    loop: Any = GLib.MainLoop()
    steps = preview_steps(args.mode)
    started = time.monotonic()
    backdrop = _open_backdrop(monitor) if args.backdrop else None

    def report(label: str) -> None:
        stats = overlay.stats()
        print(
            f"[{time.monotonic() - started:6.2f} s] {label}: draws {stats['draws']}, "
            f"idle redraws {stats['idle_draws']}, animating {stats['animating']}",
            flush=True,
        )

    def show(index: int) -> bool:
        indicator = steps[index % len(steps)]
        overlay.apply(Decision(indicator, monitor if indicator is not Indicator.HIDDEN else "", ""))
        report(f"{indicator.value} on {monitor}")
        if len(steps) > 1:
            GLib.timeout_add(int(PREVIEW_STEP_S * 1000), show, index + 1)
        return False

    def quit_loop() -> bool:
        loop.quit()
        return False

    for signum in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, quit_loop)
    if args.seconds > 0:
        GLib.timeout_add(int(args.seconds * 1000), quit_loop)
    GLib.idle_add(show, 0)
    try:
        loop.run()
    finally:
        report("exit")
        overlay.close()
        if backdrop is not None:
            backdrop.destroy()
        if log is not None:
            log.close()
    return 0


def _open_backdrop(monitor: str) -> Any:  # pragma: no cover - live
    """A plain dark fullscreen toplevel on ``monitor`` (screenshots without personal content)."""
    from gi.repository import Gdk, Gtk

    display: Any = Gdk.Display.get_default()
    model = display.get_monitors()
    window: Any = Gtk.Window(title="vpn-monitor preview backdrop")
    css: Any = Gtk.CssProvider()
    css.load_from_string("window.vpm-backdrop { background: #1e1f22; }")
    Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    window.add_css_class("vpm-backdrop")
    for i in range(model.get_n_items()):
        gdk_monitor = model.get_item(i)
        if gdk_monitor.get_connector() == monitor:
            window.fullscreen_on_monitor(gdk_monitor)
    window.present()
    return window


def notify(summary: str) -> None:
    """Desktop notification via ``notify-send``; silently skipped if it is missing or fails."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            ["notify-send", "-a", "VPN Monitor", "-u", "low", "-t", "2500", summary],
            check=False,
            timeout=5,
            capture_output=True,
        )


def _ask_daemon(command: str) -> dict[str, Any] | int:
    """Send ``command``; return the reply, or the exit code to use after printing the error."""
    from vpn_monitor.control import ControlError, DaemonNotRunning, send_command

    try:
        reply = send_command(command)
    except DaemonNotRunning:
        print("vpn-monitor: not running (start it with `vpn-monitor run`)", file=sys.stderr)
        return NOT_RUNNING_EXIT
    except ControlError as exc:
        print(f"vpn-monitor: {exc}", file=sys.stderr)
        return CONTROL_EXIT
    if not reply.get("ok"):
        print(f"vpn-monitor: the daemon refused {command!r}: {reply.get('error')}", file=sys.stderr)
        return CONTROL_EXIT
    return reply


def _control(command: str) -> int:
    reply = _ask_daemon(command)
    if isinstance(reply, int):
        return reply
    paused = bool(reply.get("paused"))
    print("vpn-monitor paused" if paused else "vpn-monitor resumed")
    notify("VPN Monitor paused" if paused else "VPN Monitor resumed")
    return 0


def _age(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {secs:02d}s"


def format_status(status: dict[str, Any]) -> str:
    """Human form of the daemon's ``status`` reply."""
    lines = [
        f"vpn-monitor {status['version']} running (pid {status['pid']}), "
        f"up {_age(status['uptime_s'])}"
    ]
    if status["paused"]:
        left = status.get("pause_resumes_in_s")
        extra = f", resumes in {_age(left)}" if left is not None else " until resumed"
        lines.append(f"  PAUSED{extra}")
    shown = status["indicator"].upper()
    where = f" on {status['monitor']}" if status["monitor"] else ""
    lines.append(f"  indicator: {shown}{where}: {status['reason']}")
    focus = status["focus"]
    if focus["class"]:
        verdict = f"BROWSER ({focus['match']})" if focus["match"] != "none" else "not a browser"
        lines.append(f"  focus: {focus['class']}  {verdict}  monitor={focus['monitor'] or '?'}")
    else:
        lines.append("  focus: no window focused")
    reading = status["reading"]
    if reading is None:
        lines.append("  vpn: no reading yet")
    else:
        lines.append(
            f"  vpn: {reading['state'].upper()} ({reading['age_s']} s old): {reading['reason']}"
        )
        for route in reading["routes"]:
            tag = " VPN" if route["vpn"] else ""
            lines.append(
                f"    IPv{route['family']}  {route['kind']:<11} {route['interface'] or '-'}{tag}"
            )
    fw, vw = status.get("focus_watcher", {}), status.get("vpn_watcher", {})
    if fw:
        lines.append(
            f"  focus watcher: connected={fw.get('connected')} reconnects={fw.get('reconnects')}"
        )
    if vw:
        lines.append(
            f"  vpn watcher: up={vw.get('watcher_up')} last trigger={vw.get('last_trigger')!r}"
        )
    lines.append(f"  config: {status['config'] or 'built-in defaults'}")
    return "\n".join(lines)


def _status(args: argparse.Namespace) -> int:
    reply = _ask_daemon("status")
    if isinstance(reply, int):
        return reply
    status = {key: value for key, value in reply.items() if key != "ok"}
    print(json.dumps(status, indent=2) if args.json else format_status(status))
    return 0


def _log(args: argparse.Namespace) -> int:
    from collections import deque

    from vpn_monitor.eventlog import EVENT_LOG, HUMAN_LOG, default_state_dir

    path = default_state_dir() / (EVENT_LOG if args.events else HUMAN_LOG)
    if not path.exists():
        print(f"vpn-monitor: no log yet at {path}", file=sys.stderr)
        return 1
    if args.follow:  # pragma: no cover - replaces the process
        os.execvp("tail", ["tail", "-n", str(LOG_TAIL_LINES), "-F", str(path)])
    with path.open(encoding="utf-8", errors="replace") as handle:
        sys.stdout.writelines(deque(handle, maxlen=LOG_TAIL_LINES))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "probe":
        return _probe(args)
    if args.command == "focus":
        return _focus(args)
    if args.command == "preview":
        return _preview(args, raw)
    if args.command == "run":
        from vpn_monitor.daemon import run

        return run(foreground=args.foreground, argv=raw, config_path=args.config)
    if args.command in ("pause", "resume", "toggle"):
        return _control(args.command)
    if args.command == "status":
        return _status(args)
    if args.command == "log":
        return _log(args)
    parser.error(f"unknown command {args.command!r}")  # pragma: no cover - argparse rejects it
