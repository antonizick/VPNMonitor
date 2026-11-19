"""Hyprland focus watcher: socket2 events, initial-state query, reconnect (titles are dropped).

Hyprland publishes a line-based event stream on ``.socket2.sock`` and answers one-shot requests on
``.socket.sock``. :class:`FocusWatcher` is the daemon's :class:`~vpn_monitor.model.FocusSource`:

* The **parser** (:func:`parse_event_line`, :func:`parse_active_window`, :func:`parse_monitors`,
  :func:`parse_clients`) is pure and is the only place that sees raw Hyprland text. It never lets a
  window title (``title``, ``initialTitle``, the tail of ``activewindow>>``) out, so no later
  object or log line can contain one (spec S1).
* On every relevant event the watcher asks ``j/activewindow`` once (a burst of lines is coalesced
  into one request) and emits a :class:`~vpn_monitor.model.FocusEvent` only if it differs from the
  last one (ADR-0016). Event lines say *that* focus changed; the request says *to what*, including
  the monitor and fullscreen state, so a window moved to another monitor needs no cache upkeep.
* While the event socket is down it emits "no focus" (``FocusEvent("", "", "")``) so the engine
  hides the bar, reconnects with exponential back-off (at most :data:`RECONNECT_MAX_S`) and
  re-reads the initial state when it is back.
"""

from __future__ import annotations

import json
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from vpn_monitor.model import FocusCallback, FocusEvent

if TYPE_CHECKING:
    from vpn_monitor.eventlog import EventLog
    from vpn_monitor.mainloop import Handle, Scheduler

NO_FOCUS = FocusEvent("", "", "")
"""Delivered when nothing is focused or the event stream is down; the engine hides the bar."""

RECONNECT_INITIAL_S = 0.1
RECONNECT_MAX_S = 5.0
"""Back-off bounds for re-opening the event socket (spec task: at most 5 s)."""
BACKOFF_RESET_S = 10.0
"""A connection that lasted this long restarts the back-off at its initial value."""
REQUEST_TIMEOUT_S = 0.5
"""A local Hyprland request answers in a millisecond or two; give up after this long."""
MAX_LINE_BYTES = 65536
"""A line longer than this (an absurd title) is discarded up to its newline, never buffered."""

FULLSCREEN_BIT = 2
"""``fullscreen`` in ``j/activewindow`` is a mode: 0 none, 1 maximized, 2 fullscreen, 3 both."""

# Events after which the focused window, its monitor or its fullscreen state may have changed.
_REFRESH_EVENTS = frozenset(
    {
        "activewindow",
        "activewindowv2",
        "focusedmon",
        "focusedmonv2",
        "fullscreen",
        "closewindow",
        "movewindow",
        "movewindowv2",
        "monitoradded",
        "monitoraddedv2",
        "monitorremoved",
        "monitorremovedv2",
    }
)
_MONITOR_EVENTS = frozenset(
    {"monitoradded", "monitoraddedv2", "monitorremoved", "monitorremovedv2"}
)


class HyprlandNotRunning(RuntimeError):
    """The Hyprland sockets are not there (no Hyprland session, or not this user's)."""


class HyprlandError(RuntimeError):
    """Hyprland answered something that is not what was asked for."""


# ---------------------------------------------------------------------------------------------
# Parsing (the only place that sees titles)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyprEvent:
    """One socket2 event, reduced to what the watcher needs. Never holds a title."""

    name: str
    """Event name, for example ``activewindowv2``."""
    address: str = ""
    """Window address (``0x…``) for ``activewindowv2`` and ``closewindow``; else empty."""
    window_class: str = ""
    """Class from the v1 ``activewindow>>class,title`` event; the title is dropped here."""
    monitor: str = ""
    """Monitor name from ``focusedmon``; else empty."""
    refresh: bool = False
    """True if the focused window may have changed, so ``j/activewindow`` should be asked."""


def normalize_address(raw: str) -> str:
    """Hyprland events omit the ``0x`` prefix that its JSON replies carry; add it."""
    raw = raw.strip()
    if not raw:
        return ""
    return raw if raw.startswith("0x") else f"0x{raw}"


def parse_event_line(line: str) -> HyprEvent | None:
    """Parse one socket2 line, dropping any window title. ``None`` for a malformed line.

    The line is ``name>>data``. The name never contains ``>>``; the data may (a title can), so
    the split is on the first ``>>`` only. For ``activewindow`` the data is ``class,title`` and
    the title may contain commas, so only the text before the first comma is kept. Events whose
    data would carry a title (``windowtitle``, ``openwindow``…) are reduced to their name.
    """
    line = line.rstrip("\r\n")
    name, sep, data = line.partition(">>")
    if not sep or not name or not name.replace("_", "").isalnum():
        return None
    if name == "activewindow":
        return HyprEvent(name, window_class=data.partition(",")[0], refresh=True)
    if name in ("activewindowv2", "closewindow"):
        return HyprEvent(name, address=normalize_address(data.partition(",")[0]), refresh=True)
    if name in ("focusedmon", "focusedmonv2"):
        # focusedmon>>monitor,workspace. Monitor names have no commas.
        return HyprEvent(name, monitor=data.partition(",")[0], refresh=True)
    return HyprEvent(name, refresh=name in _REFRESH_EVENTS)


def parse_monitors(text: str) -> dict[int, str]:
    """Map Hyprland monitor id to monitor name from a ``j/monitors`` reply."""
    data = _loads(text)
    if not isinstance(data, list):
        raise HyprlandError("j/monitors did not return a list")
    names: dict[int, str] = {}
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            name = item.get("name")
            if isinstance(name, str):
                names[item["id"]] = name
    return names


def _focus_from_client(item: dict[str, object], monitors: dict[int, str]) -> FocusEvent:
    window_class = item.get("class")
    address = item.get("address")
    monitor_id = item.get("monitor")
    fullscreen = item.get("fullscreen")
    return FocusEvent(
        window_class=window_class if isinstance(window_class, str) else "",
        address=address if isinstance(address, str) else "",
        monitor=monitors.get(monitor_id, "") if isinstance(monitor_id, int) else "",
        fullscreen=(
            fullscreen
            if isinstance(fullscreen, bool)
            else isinstance(fullscreen, int) and bool(fullscreen & FULLSCREEN_BIT)
        ),
    )


def parse_active_window(text: str, monitors: dict[int, str]) -> FocusEvent:
    """Turn a ``j/activewindow`` reply into a :class:`FocusEvent`. No window → :data:`NO_FOCUS`.

    Only the class, address, monitor and fullscreen fields are read; ``title`` and
    ``initialTitle`` are never copied (spec S1). An unknown monitor id gives ``monitor=""``.
    """
    data = _loads(text)
    if not data:
        return NO_FOCUS
    if not isinstance(data, dict):
        raise HyprlandError("j/activewindow did not return an object")
    event = _focus_from_client(data, monitors)
    return event if event.window_class else NO_FOCUS


def parse_clients(text: str, monitors: dict[int, str]) -> list[FocusEvent]:
    """Turn a ``j/clients`` reply into one :class:`FocusEvent` per mapped window (no titles)."""
    data = _loads(text)
    if not isinstance(data, list):
        raise HyprlandError("j/clients did not return a list")
    return [
        _focus_from_client(item, monitors)
        for item in data
        if isinstance(item, dict) and item.get("mapped", True) is not False
    ]


def _loads(text: str) -> object:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except ValueError as exc:
        # Deliberately without the text: it holds titles.
        raise HyprlandError("Hyprland sent a reply that is not JSON") from exc


# ---------------------------------------------------------------------------------------------
# Sockets
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HyprlandSockets:
    """Paths of the two Hyprland sockets of one running instance."""

    request: Path
    events: Path


def locate_sockets(env: dict[str, str] | None = None) -> HyprlandSockets:
    """Find the sockets of the running Hyprland, or raise :class:`HyprlandNotRunning`.

    Uses ``$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE``. If that instance is gone (Hyprland
    was restarted and this process still has the old signature) the newest instance directory that
    has both sockets is used instead.
    """
    env = dict(os.environ) if env is None else env
    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise HyprlandNotRunning("Hyprland not running: XDG_RUNTIME_DIR is not set")
    base = Path(runtime) / "hypr"
    candidates: list[Path] = []
    signature = env.get("HYPRLAND_INSTANCE_SIGNATURE")
    if signature:
        candidates.append(base / signature)
    try:
        others = sorted(
            (p for p in base.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        others = []
    candidates.extend(p for p in others if p not in candidates)
    for directory in candidates:
        sockets = HyprlandSockets(directory / ".socket.sock", directory / ".socket2.sock")
        if sockets.request.exists() and sockets.events.exists():
            return sockets
    raise HyprlandNotRunning("Hyprland not running: no Hyprland sockets found")


class EventStream(Protocol):
    """A connected socket2 stream (the real one, or a test double)."""

    @property
    def fd(self) -> int:
        """File descriptor to watch for readability."""
        ...

    def read_available(self) -> bytes | None:
        """Read what is available: data, ``b""`` at end of stream, ``None`` if nothing yet."""
        ...

    def close(self) -> None:
        """Close the stream. Safe to call twice."""
        ...


class SocketEventStream:
    """Non-blocking Unix-socket connection to ``.socket2.sock``."""

    def __init__(self, path: Path) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(REQUEST_TIMEOUT_S)
            sock.connect(str(path))
        except OSError:
            sock.close()
            raise
        sock.setblocking(False)
        self._sock = sock

    @property
    def fd(self) -> int:
        return self._sock.fileno()

    def read_available(self) -> bytes | None:
        try:
            return self._sock.recv(65536)
        except BlockingIOError:
            return None

    def close(self) -> None:
        self._sock.close()


Spawner = Callable[[], EventStream]
"""Opens an :class:`EventStream`; raises ``OSError`` or :class:`HyprlandNotRunning` if it cannot."""


def default_spawner() -> EventStream:
    """Open the event socket of the running Hyprland (looked up on every call)."""
    return SocketEventStream(locate_sockets().events)


class FocusQuery(Protocol):
    """Asks Hyprland what is focused right now."""

    def active_focus(self) -> FocusEvent:
        """The focused window as a :class:`FocusEvent` (:data:`NO_FOCUS` if none).

        Raises ``OSError`` or :class:`HyprlandError` if Hyprland cannot answer.
        """
        ...

    def invalidate_monitors(self) -> None:
        """Forget the monitor id → name table (a monitor was added or removed)."""
        ...


Requester = Callable[[str], str]
"""Sends one request (``j/clients``) and returns Hyprland's raw reply."""


def socket_request(command: str) -> str:
    """Send one request to the running Hyprland over its request socket."""
    path = locate_sockets().request
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(REQUEST_TIMEOUT_S)
        sock.connect(str(path))
        sock.sendall(command.encode())
        chunks: list[bytes] = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


class HyprlandClient:
    """:class:`FocusQuery` over the request socket, with a monitor id → name table."""

    def __init__(self, requester: Requester = socket_request) -> None:
        self._request = requester
        self._monitors: dict[int, str] | None = None

    def invalidate_monitors(self) -> None:
        self._monitors = None

    def monitors(self) -> dict[int, str]:
        """Monitor id → name (cached until a monitor event invalidates it)."""
        if self._monitors is None:
            self._monitors = parse_monitors(self._request("j/monitors"))
        return self._monitors

    def active_focus(self) -> FocusEvent:
        text = self._request("j/activewindow")
        focus = parse_active_window(text, self.monitors())
        if focus.window_class and not focus.monitor:
            # An id we have not seen: the monitor table is stale. Refresh once and re-resolve.
            self.invalidate_monitors()
            focus = parse_active_window(text, self.monitors())
        return focus

    def all_windows(self) -> list[FocusEvent]:
        """Every mapped window (class, address, monitor, fullscreen; no titles)."""
        self.invalidate_monitors()
        return parse_clients(self._request("j/clients"), self.monitors())


# ---------------------------------------------------------------------------------------------
# Watcher
# ---------------------------------------------------------------------------------------------


class FocusWatcher:
    """:class:`~vpn_monitor.model.FocusSource` fed by Hyprland's socket2.

    ``start`` delivers "no focus", connects, reads the initial state and delivers it. After that a
    callback is made whenever the focused window, its monitor or its fullscreen state differs
    from the last one delivered. If the stream drops, "no focus" is delivered at once and the
    stream is reopened with back-off; the initial state is re-read when it is back.
    """

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        spawner: Spawner = default_spawner,
        query: FocusQuery | None = None,
        clock: Callable[[], float] = time.monotonic,
        log: EventLog | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._spawner = spawner
        self._query: FocusQuery = query if query is not None else HyprlandClient()
        self._clock = clock
        self._log = log

        self._callback: FocusCallback | None = None
        self._stream: EventStream | None = None
        self._watch: Handle | None = None
        self._restart: Handle | None = None
        self._backoff_s = RECONNECT_INITIAL_S
        self._connected_at = 0.0
        self._buffer = bytearray()
        self._discarding = False
        self._last: FocusEvent | None = None
        self._last_error = ""

        self.last_focus: FocusEvent | None = None
        self.last_latency_s: float | None = None
        """Seconds from receiving event data to delivering the resulting focus change."""
        self.events_seen = 0
        self.reconnects = 0

    # -- FocusSource --------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._callback is not None

    @property
    def connected(self) -> bool:
        return self._stream is not None

    def start(self, callback: FocusCallback) -> None:
        if self._callback is not None:
            raise RuntimeError("FocusWatcher already started")
        self._callback = callback
        self._deliver(NO_FOCUS, "start")  # until the connection proves itself, nothing is focused
        self._connect()

    def stop(self) -> None:
        self._callback = None
        if self._restart is not None:
            self._scheduler.cancel(self._restart)
            self._restart = None
        self._close_stream()

    # -- connection ---------------------------------------------------------------------------

    def _connect(self) -> None:
        self._restart = None
        if self._callback is None:
            return
        try:
            stream = self._spawner()
        except (OSError, HyprlandNotRunning) as exc:
            self._error(f"cannot open the Hyprland event socket: {_why(exc)}")
            self._schedule_reconnect()
            return
        self._stream = stream
        self._connected_at = self._clock()
        self._buffer.clear()
        self._discarding = False
        self._watch = self._scheduler.watch_fd(stream.fd, self._on_readable)
        self._query.invalidate_monitors()
        trigger = "reconnect" if self.reconnects else "start"
        if self._refresh(trigger):
            self._last_error = ""
        else:
            self._close_stream()
            self._schedule_reconnect()

    def _on_readable(self) -> bool:
        stream = self._stream
        if stream is None:
            return False
        received = self._clock()
        try:
            data = stream.read_available()
        except OSError as exc:
            return self._died(f"event socket read failed: {_why(exc)}")
        if data is None:
            return True
        if not data:
            return self._died("Hyprland closed the event socket")
        refresh = False
        for event in self._split(data):
            self.events_seen += 1
            refresh = refresh or (event.refresh and not self._repeats_focus(event))
            if event.name in _MONITOR_EVENTS:
                self._query.invalidate_monitors()
        if refresh and not self._refresh("event", received):
            return self._died("cannot read the active window; reconnecting")
        return True

    def _repeats_focus(self, event: HyprEvent) -> bool:
        """True for an ``activewindow``/``activewindowv2`` that names the window already delivered.

        Hyprland re-sends both whenever the focused window's **title** changes (a terminal or a
        page updating its title about once a second), although focus did not move. Asking
        ``j/activewindow`` for each of those was the whole idle cost measured in Phase 08. A real
        focus change always brings a v2 event with a different address; monitor and fullscreen
        changes come with their own events (``movewindow``, ``focusedmon``, ``fullscreen``), which
        still refresh.
        """
        last = self._last
        if last is None or not last.address:
            return False
        if event.name == "activewindowv2":
            return event.address == last.address
        if event.name == "activewindow":
            return event.window_class == last.window_class
        return False

    def _died(self, reason: str) -> bool:
        """The stream is unusable: hide the bar, schedule a reconnect. Returns False (no watch)."""
        ran_for = self._clock() - self._connected_at
        self._watch = None  # the caller returns False, which removes the watch
        self._close_stream()
        self._deliver(NO_FOCUS, "disconnected")
        if ran_for >= BACKOFF_RESET_S:
            self._backoff_s = RECONNECT_INITIAL_S
        self._error(reason)
        self._schedule_reconnect()
        return False

    def _split(self, data: bytes) -> list[HyprEvent]:
        """Feed raw bytes in; return the parsed events of every complete line."""
        events: list[HyprEvent] = []
        self._buffer.extend(data)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                if len(self._buffer) > MAX_LINE_BYTES:
                    self._buffer.clear()
                    self._discarding = True
                break
            raw = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if self._discarding:
                self._discarding = False
                continue
            event = parse_event_line(raw.decode("utf-8", errors="replace"))
            if event is not None:
                events.append(event)
        return events

    def _schedule_reconnect(self) -> None:
        if self._callback is None or self._restart is not None:
            return
        delay = self._backoff_s
        self._backoff_s = min(self._backoff_s * 2, RECONNECT_MAX_S)
        self.reconnects += 1
        self._restart = self._scheduler.call_later(delay, self._connect)

    def _close_stream(self) -> None:
        if self._watch is not None:
            self._scheduler.cancel(self._watch)
            self._watch = None
        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.close()

    # -- focus --------------------------------------------------------------------------------

    def _refresh(self, trigger: str, received: float | None = None) -> bool:
        """Ask Hyprland what is focused and deliver it if it changed. False if it cannot say."""
        try:
            focus = self._query.active_focus()
        except (OSError, HyprlandError, HyprlandNotRunning) as exc:
            self._error(f"cannot read the active window: {_why(exc)}")
            self._deliver(NO_FOCUS, "error")  # cannot tell: hide rather than keep a stale bar
            return False
        self.last_latency_s = None if received is None else max(0.0, self._clock() - received)
        self._deliver(focus, trigger)
        return True

    def _deliver(self, focus: FocusEvent, trigger: str) -> None:
        callback = self._callback
        if callback is None or focus == self._last:
            return
        self._last = self.last_focus = focus
        if self._log is not None:
            self._log.record(
                "focus",
                reason="focus changed" if focus.window_class else "no window focused",
                inputs={
                    "class": focus.window_class,
                    "monitor": focus.monitor,
                    "fullscreen": str(focus.fullscreen).lower(),
                    "trigger": trigger,
                },
            )
        callback(focus)

    def _error(self, reason: str) -> None:
        if self._log is None or reason == self._last_error:
            return  # one line per distinct failure, not one per retry
        self._last_error = reason
        self._log.error("focus_watcher", reason, {"retry_in_s": f"{self._backoff_s:g}"})


def _why(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return (text or type(exc).__name__)[:160]
