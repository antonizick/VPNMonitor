"""Human-readable log plus JSONL event log, with rotation and no window titles (R11, S1).

Both files live in ``$XDG_STATE_HOME/vpn-monitor/`` (default ``~/.local/state/vpn-monitor/``,
directory mode 0700): ``vpn-monitor.log`` for people and ``events.jsonl`` for tools. Both rotate
by size with the stdlib :class:`logging.handlers.RotatingFileHandler`.

JSONL schema, one object per line (``docs/VPM_ARCHITECTURE.md``, ADR-0014)::

    {"ts": "2026-11-18T22:31:05.123-06:00",   # wall clock, ISO 8601 with offset
     "event": "decision",                     # decision | reading | pause | config | error…
     "level": "info",                         # debug | info | warning | error
     "decision": "red",                       # hidden | red | blue, or null
     "monitor": "eDP-1",                      # or "" / null
     "reason": "browser focused, VPN reading is stale",
     "inputs": {"class": "brave-browser", "match": "exact:brave-browser", "monitor": "eDP-1",
                "fullscreen": "false", "paused": "false", "vpn_state": "vpn",
                "reading_age_s": "12.004", "routes": "v4 proton0 routed vpn; v6 - blocked",
                "reading_reason": "…"}}

Faults (spec R4: a broken log must never stop the indicator): if the directory or a file cannot
be opened, that log falls back to stderr (the service journal) and :attr:`EventLog.degraded`
says why; a failing write (disk full) is reported once on stderr and never raised. Files are
created mode 0600.

``inputs`` is a flat ``str -> str`` map. A window **title** never appears (S1): no type carries
one, and :class:`TitleGuard` lets tests (and later phases) assert it by raising on any record
whose text contains a registered title.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from vpn_monitor.model import Decision

HUMAN_LOG = "vpn-monitor.log"
EVENT_LOG = "events.jsonl"

WallClock = Callable[[], datetime]


class TitleLeakError(AssertionError):
    """A registered window title was about to be written to a log (spec S1)."""


class TitleGuard:
    """Raises :class:`TitleLeakError` if a record contains any registered title.

    Tests register the titles they put into fake Hyprland events; any later log record whose
    text contains one of them is a privacy bug. Matching is by substring, so a title embedded
    in a longer string is caught too.
    """

    def __init__(self, titles: Iterable[str] = ()) -> None:
        self._titles: set[str] = set()
        for title in titles:
            self.add(title)

    def add(self, title: str) -> None:
        """Register a title that must never be logged. Empty strings are ignored."""
        if title:
            self._titles.add(title)

    def check(self, record: object) -> None:
        """Raise if any string inside ``record`` (recursively) contains a registered title."""
        for text in _strings(record):
            for title in self._titles:
                if title in text:
                    raise TitleLeakError("a window title reached the log (spec S1)")


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _strings(item)


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Creates its files 0600 and reports a failing write once on stderr instead of raising."""

    def __init__(self, filename: Path, **kwargs: Any) -> None:
        self.write_failed = False
        super().__init__(filename, **kwargs)

    def _open(self) -> Any:
        fd = os.open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        return open(fd, self.mode, encoding=self.encoding, errors=self.errors)

    def handleError(self, record: logging.LogRecord) -> None:
        if not self.write_failed:
            self.write_failed = True
            error = sys.exc_info()[1]
            name = type(error).__name__ if error is not None else "error"
            print(
                f"vpn-monitor: cannot write {self.baseFilename} ({name}: {error}); "
                "further write errors are not reported",
                file=sys.stderr,
            )


def default_state_dir(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_STATE_HOME/vpn-monitor``, default ``~/.local/state/vpn-monitor``."""
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME") or ""
    root = Path(base) if os.path.isabs(base) else Path.home() / ".local" / "state"
    return root / "vpn-monitor"


def _local_now() -> datetime:
    return datetime.now().astimezone()


_LEVELS = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
}


class EventLog:
    """Writes every event to both logs. Not thread-safe by design (ADR-0012: one loop)."""

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        max_bytes: int = 1_000_000,
        backup_count: int = 3,
        guard: TitleGuard | None = None,
        wall_clock: WallClock = _local_now,
    ) -> None:
        self.state_dir = default_state_dir() if state_dir is None else state_dir
        self.degraded: str | None = None
        """Why a log fell back to stderr, or ``None`` when both files are open."""
        try:
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.state_dir, 0o700)
        except OSError as exc:
            self.degraded = f"log directory {self.state_dir}: {type(exc).__name__}: {exc}"
        self._guard = guard
        self._wall_clock = wall_clock
        self._closed = False

        tag = f"vpn_monitor.eventlog.{id(self):x}"
        self._human = self._logger(f"{tag}.human", HUMAN_LOG, max_bytes, backup_count)
        self._events = self._logger(f"{tag}.events", EVENT_LOG, max_bytes, backup_count)

    def _logger(self, name: str, filename: str, max_bytes: int, backups: int) -> logging.Logger:
        handler: logging.Handler
        try:
            path = self.state_dir / filename
            handler = _PrivateRotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            os.chmod(path, 0o600)  # files from before 0600 creation was added
        except OSError as exc:
            self.degraded = self.degraded or f"{filename}: {type(exc).__name__}: {exc}"
            handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(name)
        logger.handlers[:] = [handler]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        return logger

    @property
    def human_path(self) -> Path:
        return self.state_dir / HUMAN_LOG

    @property
    def events_path(self) -> Path:
        return self.state_dir / EVENT_LOG

    def record(
        self,
        event: str,
        *,
        reason: str,
        decision: Decision | None = None,
        inputs: Mapping[str, str] | None = None,
        level: int = logging.INFO,
    ) -> dict[str, Any]:
        """Write one event to both logs and return the JSON object that was written."""
        if self._closed:
            raise RuntimeError("EventLog is closed")
        merged: dict[str, str] = dict(decision.inputs) if decision is not None else {}
        merged.update(inputs or {})
        entry: dict[str, Any] = {
            "ts": self._wall_clock().isoformat(timespec="milliseconds"),
            "event": event,
            "level": _LEVELS.get(level, "info"),
            "decision": decision.indicator.value if decision is not None else None,
            "monitor": decision.monitor if decision is not None else None,
            "reason": reason,
            "inputs": merged,
        }
        if self._guard is not None:
            self._guard.check(entry)
        self._events.log(level, json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
        self._human.log(level, _human_line(entry))
        return entry

    def decision(self, decision: Decision, event: str = "decision") -> dict[str, Any]:
        """Log a Decision with its own reason and inputs."""
        return self.record(event, reason=decision.reason, decision=decision)

    def error(self, event: str, reason: str, inputs: Mapping[str, str] | None = None) -> None:
        """Log an error (spec R11: every error is logged with its reason)."""
        self.record(event, reason=reason, inputs=inputs, level=logging.ERROR)

    def close(self) -> None:
        """Flush and close both files. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for logger in (self._human, self._events):
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


def _human_line(entry: Mapping[str, Any]) -> str:
    head = f"{entry['ts']} {entry['level'].upper():7} {entry['event']}"
    if entry["decision"] is not None:
        where = f" on {entry['monitor']}" if entry["monitor"] else ""
        head += f" {entry['decision']}{where}"
    inputs = " ".join(f"{k}={v!r}" if " " in v else f"{k}={v}" for k, v in entry["inputs"].items())
    line = f"{head}: {entry['reason']}"
    return f"{line} [{inputs}]" if inputs else line
