"""Command-line interface (spec R10). Daemon subcommands are stubs until Phase 07."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from vpn_monitor import __version__
from vpn_monitor.model import VpnReading, VpnState

if TYPE_CHECKING:
    from vpn_monitor.config import Config

NOT_IMPLEMENTED_EXIT = 2
CONFIG_ERROR_EXIT = 2
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
    run.add_argument("--foreground", action="store_true", help="stay in the foreground")
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
    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "probe":
        return _probe(args)
    print(f"vpn-monitor {args.command}: not implemented yet", file=sys.stderr)
    return NOT_IMPLEMENTED_EXIT
