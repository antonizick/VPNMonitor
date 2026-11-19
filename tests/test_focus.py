"""Focus watcher: parsing, titles never leak, coalescing, reconnect with back-off (spec R6, S1)."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from vpn_monitor import focus
from vpn_monitor.browsers import BrowserMatcher
from vpn_monitor.eventlog import EventLog, TitleGuard
from vpn_monitor.fakes import FakeScheduler
from vpn_monitor.focus import (
    NO_FOCUS,
    RECONNECT_INITIAL_S,
    RECONNECT_MAX_S,
    FocusWatcher,
    HyprlandClient,
    HyprlandError,
    HyprlandNotRunning,
    SocketEventStream,
    locate_sockets,
    normalize_address,
    parse_active_window,
    parse_clients,
    parse_event_line,
    parse_monitors,
)
from vpn_monitor.model import FocusEvent, FocusSource

FIXTURES = Path(__file__).parent / "fixtures" / "focus"
MONITORS = {1: "eDP-1", 2: "HDMI-A-1"}
TITLE = "Secret, title >> with commas"


def active_json(cls: str = "brave-browser", *, monitor: int = 2, fullscreen: int = 0) -> str:
    return json.dumps(
        {
            "address": "0x55ce5378a830",
            "class": cls,
            "title": TITLE,
            "initialClass": cls,
            "initialTitle": TITLE,
            "monitor": monitor,
            "fullscreen": fullscreen,
        }
    )


# -- parsing ---------------------------------------------------------------------------------


def test_activewindow_keeps_only_the_class() -> None:
    event = parse_event_line("activewindow>>foot,Some title, with commas >> and arrows\n")
    assert event is not None
    assert event.window_class == "foot"
    assert event.refresh
    assert "title" not in repr(event)
    assert "commas" not in repr(event)


def test_activewindowv2_address_gets_prefix() -> None:
    event = parse_event_line("activewindowv2>>55ce54548430")
    assert event is not None
    assert event.address == "0x55ce54548430"
    empty = parse_event_line("activewindowv2>>,")
    assert empty is not None
    assert empty.address == ""
    assert empty.refresh


def test_focusedmon_and_closewindow() -> None:
    mon = parse_event_line("focusedmon>>HDMI-A-1,4")
    assert mon is not None
    assert mon.monitor == "HDMI-A-1"
    assert mon.refresh
    closed = parse_event_line("closewindow>>55ce54548430")
    assert closed is not None
    assert closed.address == "0x55ce54548430"
    assert closed.refresh


@pytest.mark.parametrize(
    "line",
    [
        "windowtitle>>55ce,Secret, title",
        "windowtitlev2>>55ce,Secret, title",
        "openwindow>>55ce,5,foot,Top secret, window",
    ],
)
def test_title_carrying_events_are_reduced_to_their_name(line: str) -> None:
    event = parse_event_line(line)
    assert event is not None
    assert event.address == event.window_class == event.monitor == ""
    assert not event.refresh
    assert "ecret" not in repr(event)


@pytest.mark.parametrize("line", ["", "no separator", ">>x", "bad name>>x", "a>b>>x\u0000"])
def test_malformed_lines_are_ignored(line: str) -> None:
    assert parse_event_line(line) is None


def test_fixture_stream_parses_and_never_holds_a_title() -> None:
    lines = (FIXTURES / "socket2.txt").read_text().splitlines()
    events = [e for line in lines if (e := parse_event_line(line)) is not None]
    assert len(events) == len(lines)
    blob = repr(events)
    for word in ("Secret", "Top secret", "arrows"):
        assert word not in blob
    assert sum(e.refresh for e in events) == 11


def test_normalize_address() -> None:
    assert normalize_address("0xabc") == "0xabc"
    assert normalize_address(" abc ") == "0xabc"
    assert normalize_address("") == ""


def test_parse_active_window_drops_titles() -> None:
    event = parse_active_window(active_json(fullscreen=2), MONITORS)
    assert event == FocusEvent("brave-browser", "0x55ce5378a830", "HDMI-A-1", True)
    assert TITLE not in repr(event)


@pytest.mark.parametrize(
    ("mode", "expected"), [(0, False), (1, False), (2, True), (3, True), (True, True)]
)
def test_fullscreen_modes(mode: object, expected: bool) -> None:
    text = json.dumps({"class": "foot", "address": "0x1", "monitor": 1, "fullscreen": mode})
    assert parse_active_window(text, MONITORS).fullscreen is expected


@pytest.mark.parametrize("text", ["{}", "", "  \n", "null"])
def test_no_active_window_is_no_focus(text: str) -> None:
    assert parse_active_window(text, MONITORS) == NO_FOCUS


def test_empty_class_is_no_focus_and_unknown_monitor_is_blank() -> None:
    assert parse_active_window(json.dumps({"class": "", "address": "0x1"}), MONITORS) == NO_FOCUS
    event = parse_active_window(active_json(monitor=9), MONITORS)
    assert event.monitor == ""
    assert event.window_class == "brave-browser"


def test_bad_json_error_does_not_quote_the_reply() -> None:
    with pytest.raises(HyprlandError) as info:
        parse_active_window("{" + TITLE, MONITORS)
    assert TITLE not in str(info.value)
    with pytest.raises(HyprlandError):
        parse_active_window("[1]", MONITORS)
    with pytest.raises(HyprlandError):
        parse_monitors("{}")
    with pytest.raises(HyprlandError):
        parse_clients("{}", MONITORS)


def test_parse_monitors_and_clients() -> None:
    names = parse_monitors(json.dumps([{"id": 1, "name": "eDP-1"}, {"id": "x"}, 3, {"id": 2}]))
    assert names == {1: "eDP-1"}
    clients = json.dumps(
        [
            {"class": "foot", "address": "0x1", "monitor": 1, "title": TITLE, "mapped": True},
            {"class": "ghost", "address": "0x2", "monitor": 1, "mapped": False},
            "junk",
        ]
    )
    assert parse_clients(clients, MONITORS) == [FocusEvent("foot", "0x1", "eDP-1")]


def test_class_fixtures_agree_with_the_default_matcher() -> None:
    data = json.loads((FIXTURES / "classes.json").read_text())
    matcher = BrowserMatcher()
    for group in ("observed", "expected"):
        assert all(matcher.match(c).matched for c in data[group]["browser"])
        assert not any(matcher.match(c).matched for c in data[group]["not_browser"])


# -- locating sockets --------------------------------------------------------------------------


def make_instance(runtime: Path, signature: str, *, sockets: bool = True) -> Path:
    directory = runtime / "hypr" / signature
    directory.mkdir(parents=True)
    if sockets:
        (directory / ".socket.sock").touch()
        (directory / ".socket2.sock").touch()
    return directory


def test_locate_sockets_uses_the_signature(tmp_path: Path) -> None:
    directory = make_instance(tmp_path, "sig1")
    found = locate_sockets(
        {"XDG_RUNTIME_DIR": str(tmp_path), "HYPRLAND_INSTANCE_SIGNATURE": "sig1"}
    )
    assert found.request == directory / ".socket.sock"
    assert found.events == directory / ".socket2.sock"


def test_locate_sockets_falls_back_to_another_live_instance(tmp_path: Path) -> None:
    live = make_instance(tmp_path, "new")
    make_instance(tmp_path, "empty", sockets=False)
    env = {"XDG_RUNTIME_DIR": str(tmp_path), "HYPRLAND_INSTANCE_SIGNATURE": "old"}
    assert locate_sockets(env).events == live / ".socket2.sock"


def test_locate_sockets_not_running(tmp_path: Path) -> None:
    with pytest.raises(HyprlandNotRunning, match="Hyprland not running"):
        locate_sockets({"XDG_RUNTIME_DIR": str(tmp_path)})
    with pytest.raises(HyprlandNotRunning, match="XDG_RUNTIME_DIR"):
        locate_sockets({})


# -- the client --------------------------------------------------------------------------------


class Replies:
    def __init__(self, **replies: str) -> None:
        self.replies = {"j/monitors": json.dumps([{"id": 1, "name": "eDP-1"}]), **replies}
        self.calls: list[str] = []

    def __call__(self, command: str) -> str:
        self.calls.append(command)
        reply = self.replies[command]
        if isinstance(reply, BaseException):  # pragma: no cover - not used
            raise reply
        return reply


def test_client_caches_monitors_and_refreshes_on_unknown_id() -> None:
    replies = Replies(**{"j/activewindow": active_json(monitor=2)})
    client = HyprlandClient(replies)
    # Monitor 2 is unknown to the first table; the client refreshes once and re-resolves.
    replies.replies["j/monitors"] = json.dumps(
        [{"id": 1, "name": "eDP-1"}, {"id": 2, "name": "HDMI-A-1"}]
    )
    client.monitors()  # cached with both... then make it stale again
    client._monitors = {1: "eDP-1"}
    assert client.active_focus().monitor == "HDMI-A-1"
    assert replies.calls.count("j/monitors") == 2
    client.active_focus()
    assert replies.calls.count("j/monitors") == 2  # cached now


def test_client_all_windows() -> None:
    replies = Replies(
        **{"j/clients": json.dumps([{"class": "foot", "address": "0x1", "monitor": 1}])}
    )
    assert HyprlandClient(replies).all_windows() == [FocusEvent("foot", "0x1", "eDP-1")]


def test_socket_request_against_a_real_unix_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = make_instance(tmp_path, "sig")
    (directory / ".socket.sock").unlink()
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(directory / ".socket.sock"))
    server.listen(1)
    seen: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            seen.append(conn.recv(100))
            conn.sendall(b'{"class":"foot"}')

    thread = threading.Thread(target=serve)
    thread.start()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")
    try:
        assert focus.socket_request("j/activewindow") == '{"class":"foot"}'
    finally:
        thread.join(2)
        server.close()
    assert seen == [b"j/activewindow"]


# -- the watcher -------------------------------------------------------------------------------


class FakeStream:
    """A real socketpair so the fd is genuine; ``feed`` writes what Hyprland would send."""

    def __init__(self) -> None:
        self._server, self._client = socket.socketpair()
        self._client.setblocking(False)
        self.closed = 0

    @property
    def fd(self) -> int:
        return self._client.fileno()

    def feed(self, text: str) -> None:
        self._server.sendall(text.encode())

    def hang_up(self) -> None:
        self._server.close()

    def read_available(self) -> bytes | None:
        try:
            return self._client.recv(65536)
        except BlockingIOError:
            return None

    def close(self) -> None:
        self.closed += 1
        self._client.close()
        self._server.close()


class FakeQuery:
    def __init__(self, *answers: FocusEvent | BaseException) -> None:
        self.answers = list(answers)
        self.calls = 0
        self.invalidated = 0

    def active_focus(self) -> FocusEvent:
        self.calls += 1
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, BaseException):
            raise item
        return item

    def invalidate_monitors(self) -> None:
        self.invalidated += 1


BRAVE = FocusEvent("brave-browser", "0x1", "HDMI-A-1")
FOOT = FocusEvent("foot", "0x2", "HDMI-A-1")


class Rig:
    def __init__(self, query: FakeQuery, log: EventLog | None = None) -> None:
        self.scheduler = FakeScheduler()
        self.query = query
        self.streams: list[FakeStream] = []
        self.refuse: list[BaseException] = []
        self.events: list[FocusEvent] = []
        self.watcher = FocusWatcher(
            self.scheduler, spawner=self.spawn, query=query, clock=self.scheduler.clock, log=log
        )

    def spawn(self) -> FakeStream:
        if self.refuse:
            raise self.refuse.pop(0)
        stream = FakeStream()
        self.streams.append(stream)
        return stream

    def start(self) -> None:
        self.watcher.start(self.events.append)

    @property
    def stream(self) -> FakeStream:
        return self.streams[-1]

    def deliver(self, text: str) -> None:
        self.stream.feed(text)
        self.scheduler.ready(self.stream.fd)


def test_is_a_focus_source() -> None:
    assert isinstance(FocusWatcher(FakeScheduler()), FocusSource)


def test_start_delivers_no_focus_then_the_initial_state() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()
    assert rig.events == [BRAVE] or rig.events == [NO_FOCUS, BRAVE]
    assert rig.watcher.connected
    assert rig.watcher.running
    assert rig.query.invalidated >= 1


def test_start_twice_is_an_error_and_stop_is_safe_twice() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()
    with pytest.raises(RuntimeError):
        rig.start()
    rig.watcher.stop()
    rig.watcher.stop()
    assert not rig.watcher.running
    assert rig.stream.closed == 1
    assert rig.scheduler.watches == {}


def test_events_trigger_one_query_and_duplicates_are_not_redelivered() -> None:
    rig = Rig(FakeQuery(BRAVE, FOOT))
    rig.start()
    before = rig.query.calls
    # v1 + v2 lines of one change arrive together: a single query.
    rig.deliver("activewindow>>foot,x\nactivewindowv2>>2\n")
    assert rig.query.calls == before + 1
    assert rig.events[-1] == FOOT
    rig.deliver("activewindowv2>>2\n")  # the answer is unchanged
    assert rig.events.count(FOOT) == 1
    assert rig.watcher.last_focus == FOOT
    assert rig.watcher.events_seen == 3


def test_irrelevant_events_do_not_query() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()
    before = rig.query.calls
    rig.deliver("workspace>>3\nwindowtitle>>1\nopenwindow>>1,2,foot,t\n")
    assert rig.query.calls == before


def test_title_updates_of_the_focused_window_do_not_query() -> None:
    """Hyprland re-sends activewindow(v2) on every title change; that is not a focus change."""
    rig = Rig(FakeQuery(FOOT))
    rig.start()
    before = rig.query.calls
    for _ in range(5):  # a terminal updating its title once a second
        rig.deliver("windowtitle>>2\nwindowtitlev2>>2,t\nactivewindow>>foot,t\nactivewindowv2>>2\n")
    assert rig.query.calls == before
    assert rig.events[-1] == FOOT


def test_same_class_other_window_still_queries() -> None:
    other_brave = FocusEvent("brave-browser", "0x9", "DP-1")
    rig = Rig(FakeQuery(BRAVE, other_brave))
    rig.start()
    before = rig.query.calls
    rig.deliver("activewindow>>brave-browser,t\nactivewindowv2>>9\n")  # new address
    assert rig.query.calls == before + 1
    assert rig.events[-1] == other_brave


def test_repeated_focus_with_monitor_or_fullscreen_event_still_queries() -> None:
    moved = FocusEvent("foot", "0x2", "DP-1", fullscreen=True)
    rig = Rig(FakeQuery(FOOT, moved))
    rig.start()
    before = rig.query.calls
    rig.deliver("activewindowv2>>2\nfullscreen>>1\n")
    assert rig.query.calls == before + 1
    assert rig.events[-1] == moved


def test_repeat_check_needs_a_delivered_window() -> None:
    rig = Rig(FakeQuery(FocusEvent("", "", ""), FOOT))
    rig.start()  # nothing focused yet: no address to compare with
    before = rig.query.calls
    rig.deliver("activewindowv2>>2\n")
    assert rig.query.calls == before + 1


def test_partial_lines_are_buffered_until_complete() -> None:
    rig = Rig(FakeQuery(BRAVE, FOOT))
    rig.start()
    before = rig.query.calls
    rig.deliver("activewindowv2>>")
    assert rig.query.calls == before
    rig.deliver("2\n")
    assert rig.query.calls == before + 1


def test_monitor_events_invalidate_the_monitor_table() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()
    before = rig.query.invalidated
    rig.deliver("monitoraddedv2>>2,HDMI-A-1,desc\n")
    assert rig.query.invalidated == before + 1


def test_oversized_line_is_discarded_not_buffered() -> None:
    rig = Rig(FakeQuery(BRAVE, FOOT))
    rig.start()
    rig.deliver("activewindow>>foot," + "x" * focus.MAX_LINE_BYTES)
    rig.deliver("x" * 100)
    assert len(rig.watcher._buffer) == 0
    before = rig.query.calls
    rig.deliver("tail of the long title\nactivewindowv2>>2\n")
    assert rig.query.calls == before + 1  # the tail line was dropped, the next one parsed


def test_latency_is_measured_from_receipt() -> None:
    rig = Rig(FakeQuery(BRAVE, FOOT))
    rig.start()
    rig.deliver("activewindowv2>>2\n")
    assert rig.watcher.last_latency_s == 0.0


def test_hangup_hides_the_bar_then_reconnects_and_rereads() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()
    first = rig.stream
    first.hang_up()
    rig.scheduler.ready(first.fd)
    assert rig.events[-1] == NO_FOCUS
    assert not rig.watcher.connected
    assert rig.scheduler.delays() == pytest.approx([RECONNECT_INITIAL_S])
    rig.scheduler.advance(RECONNECT_INITIAL_S)
    assert rig.watcher.connected
    assert len(rig.streams) == 2
    assert rig.events[-1] == BRAVE  # initial state re-read after the reconnect
    assert first.closed == 1


def test_read_error_is_handled_like_a_hangup() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.start()

    def boom() -> bytes | None:
        raise ConnectionResetError("reset")

    rig.stream.read_available = boom  # type: ignore[method-assign]
    rig.scheduler.ready(rig.stream.fd)
    assert rig.events[-1] == NO_FOCUS
    assert not rig.watcher.connected


def test_backoff_doubles_up_to_five_seconds_and_resets_after_a_good_run() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.refuse = [FileNotFoundError("no socket")] * 8
    rig.start()
    seen: list[float] = []
    for _ in range(8):
        seen.append(rig.scheduler.delays()[0])
        rig.scheduler.advance(seen[-1])
    assert seen == sorted(seen)
    assert max(seen) == pytest.approx(RECONNECT_MAX_S)
    assert RECONNECT_MAX_S == 5.0
    assert seen[:3] == pytest.approx([0.1, 0.2, 0.4])
    assert rig.watcher.connected  # the 9th attempt succeeded
    rig.scheduler.advance(focus.BACKOFF_RESET_S + 1)
    rig.stream.hang_up()
    rig.scheduler.ready(rig.stream.fd)
    assert rig.scheduler.delays() == pytest.approx([RECONNECT_INITIAL_S])


def test_hyprland_not_running_at_start_hides_and_keeps_trying() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.refuse = [HyprlandNotRunning("Hyprland not running")]
    rig.start()
    assert rig.events == [NO_FOCUS]
    assert not rig.watcher.connected
    rig.scheduler.advance(RECONNECT_INITIAL_S)
    assert rig.events[-1] == BRAVE


def test_query_failure_hides_the_bar_and_reconnects() -> None:
    rig = Rig(FakeQuery(BRAVE, HyprlandError("bad reply")))
    rig.start()
    rig.deliver("activewindowv2>>2\n")
    assert rig.events[-1] == NO_FOCUS
    assert not rig.watcher.connected
    assert rig.scheduler.delays() == pytest.approx([RECONNECT_INITIAL_S])


def test_query_failure_at_connect_retries() -> None:
    rig = Rig(FakeQuery(OSError("refused"), BRAVE))
    rig.start()
    assert not rig.watcher.connected
    assert rig.events == [NO_FOCUS]
    rig.scheduler.advance(RECONNECT_INITIAL_S)
    assert rig.events[-1] == BRAVE
    assert rig.watcher.connected


def test_stop_cancels_a_pending_reconnect() -> None:
    rig = Rig(FakeQuery(BRAVE))
    rig.refuse = [OSError("x")]
    rig.start()
    rig.watcher.stop()
    assert rig.scheduler.timers == {}


def test_reconnect_against_a_real_socket_server(tmp_path: Path) -> None:
    path = tmp_path / ".socket2.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(path))
    server.listen(2)
    scheduler = FakeScheduler()
    events: list[FocusEvent] = []
    watcher = FocusWatcher(
        scheduler,
        spawner=lambda: SocketEventStream(path),
        query=FakeQuery(BRAVE, FOOT),
        clock=scheduler.clock,
    )
    watcher.start(events.append)
    conn, _ = server.accept()
    conn.sendall(b"activewindowv2>>2\n")
    (fd,) = [fd for fd, _ in scheduler.watches.values()]
    scheduler.ready(fd)
    assert events[-1] == FOOT
    conn.close()  # Hyprland's side goes away
    scheduler.ready(fd)
    assert events[-1] == NO_FOCUS
    scheduler.advance(RECONNECT_INITIAL_S)
    conn2, _ = server.accept()
    assert watcher.connected
    conn2.close()
    server.close()
    watcher.stop()


# -- S1: no title anywhere ---------------------------------------------------------------------


def test_titles_never_reach_events_or_logs(tmp_path: Path) -> None:
    guard = TitleGuard([TITLE, "Secret, title", "Top secret, window", "Some title"])
    log = EventLog(state_dir=tmp_path, guard=guard)
    rig = Rig(FakeQuery(BRAVE, FOOT), log)
    rig.start()
    rig.deliver(
        f"activewindow>>foot,{TITLE}\nactivewindowv2>>2\n"
        f"windowtitlev2>>2,{TITLE}\nopenwindow>>2,5,foot,Top secret, window\n"
    )
    rig.stream.hang_up()
    rig.scheduler.ready(rig.stream.fd)  # logs a disconnect too
    log.close()
    text = log.human_path.read_text() + log.events_path.read_text()
    assert "focus" in text
    assert "foot" in text
    for title in (TITLE, "Secret, title", "Top secret, window"):
        assert title not in text
        assert all(title not in repr(e) for e in rig.events)


def test_errors_are_logged_once_per_distinct_failure(tmp_path: Path) -> None:
    log = EventLog(state_dir=tmp_path)
    rig = Rig(FakeQuery(BRAVE), log)
    rig.refuse = [OSError("no socket")] * 3
    rig.start()
    for _ in range(3):
        rig.scheduler.advance(RECONNECT_MAX_S)
    log.close()
    errors = [
        json.loads(line) for line in log.events_path.read_text().splitlines() if '"error"' in line
    ]
    assert len(errors) == 1
    assert "no socket" in errors[0]["reason"]
