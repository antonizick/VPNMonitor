"""Command-line interface (spec R10). Subcommands are stubs until Phase 07."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from vpn_monitor import __version__

NOT_IMPLEMENTED_EXIT = 2


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    print(f"vpn-monitor {args.command}: not implemented yet", file=sys.stderr)
    return NOT_IMPLEMENTED_EXIT
