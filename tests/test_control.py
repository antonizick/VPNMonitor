"""Control socket: permissions, peer uid, protocol, single instance, client."""

from __future__ import annotations

import contextlib
import json
import os
import select
import shutil
import socket
import stat
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor import control
from vpn_monitor.control import (
    AlreadyRunning,
    ControlError,
    ControlServer,
    DaemonNotRunning,
    InstanceLock,
    send_command,
)
from vpn_monitor.eventlog import EventLog
from vpn_monitor.fakes import FakeScheduler


@pytest.fixture
def rundir() -> Iterator[Path]:
    # AF_UNIX paths are limited to ~107 bytes, so do not use pytest's long tmp_path
    path = Path(tempfile.mkdtemp(prefix="vpm-"))
    yield path / "vpn-monitor"
    shutil.rmtree(path, ignore_errors=True)


class Pump:
    """Runs the fake scheduler's fd watch in a thread so blocking clients can be answered."""

    def __init__(self, scheduler: FakeScheduler, server: ControlServer) -> None:
        self._scheduler = scheduler
        self._fd = server._sock.fileno()  # type: ignore[union-attr]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], 0.05)
            if ready:
                self._scheduler.ready(self._fd)

    def __enter__(self) -> Pump:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()


def make_server(
    rundir: Path, log: EventLog | None = None, handler: Any = None
) -> tuple[ControlServer, FakeScheduler, list[str]]:
    seen: list[str] = []

    def default(command: str) -> dict[str, Any]:
        seen.append(command)
        return {"paused": command == "pause"}

    scheduler = FakeScheduler()
    server = ControlServer(scheduler, handler or default, path=rundir / "control.sock", log=log)
    server.start()
    return server, scheduler, seen


def raw(path: Path, payload: bytes) -> bytes:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(2)
        s.connect(str(path))
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        try:
            return s.recv(65536)
        except ConnectionResetError:  # the daemon dropped us without a reply
            return b""


def test_directory_and_socket_permissions(rundir: Path) -> None:
    server, _, _ = make_server(rundir)
    try:
        assert stat.S_IMODE(rundir.stat().st_mode) == 0o700
        assert stat.S_IMODE(server.path.stat().st_mode) == 0o600
        assert stat.S_ISSOCK(server.path.stat().st_mode)
    finally:
        server.stop()
    assert not server.path.exists()


def test_a_loose_directory_is_tightened(rundir: Path) -> None:
    rundir.mkdir(parents=True)
    rundir.chmod(0o755)
    server, _, _ = make_server(rundir)
    try:
        assert stat.S_IMODE(rundir.stat().st_mode) == 0o700
    finally:
        server.stop()


def test_a_file_where_the_directory_should_be_is_refused(rundir: Path) -> None:
    rundir.parent.mkdir(parents=True, exist_ok=True)
    rundir.write_text("x")
    with pytest.raises((ControlError, FileExistsError, NotADirectoryError)):
        control.ensure_private_dir(rundir)


@pytest.mark.parametrize("command", control.COMMANDS)
def test_known_commands_reach_the_handler(rundir: Path, command: str) -> None:
    server, scheduler, seen = make_server(rundir)
    try:
        with Pump(scheduler, server):
            reply = send_command(command, path=server.path)
        assert reply == {"ok": True, "paused": command == "pause"}
        assert seen == [command]
    finally:
        server.stop()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"cmd":"rm -rf /"}\n',
        b'{"cmd":""}\n',
        b'{"cmd":5}\n',
        b'{"cmd":null}\n',
        b'{"other":"pause"}\n',
        b"[1,2]\n",
        b"pause\n",
        b"not json\n",
        b'{"cmd":"pause\x1b[31m"}\n',
        b'{"cmd":"Pause"}\n',
    ],
)
def test_anything_else_is_rejected_and_logged(rundir: Path, payload: bytes) -> None:
    log = EventLog(rundir.parent / "state")
    server, scheduler, seen = make_server(rundir, log)
    try:
        with Pump(scheduler, server):
            reply = json.loads(raw(server.path, payload))
        assert reply["ok"] is False
        assert seen == []
        events = [json.loads(x) for x in log.events_path.read_text().splitlines()]
        assert events[-1]["event"] == "control_rejected"
        assert "\x1b" not in json.dumps(events)  # hostile bytes never reach the log raw
    finally:
        server.stop()
        log.close()


def test_oversized_and_unterminated_requests_are_rejected(rundir: Path) -> None:
    server, scheduler, seen = make_server(rundir)
    try:
        with Pump(scheduler, server):
            big = raw(server.path, b'{"cmd":"' + b"a" * 10_000 + b'"}\n')
            unterminated = raw(server.path, b'{"cmd":"pause"}')
        assert json.loads(big)["ok"] is False
        assert json.loads(unterminated)["ok"] is False
        assert seen == []
    finally:
        server.stop()


def test_a_peer_with_another_uid_is_dropped_without_a_reply(rundir: Path) -> None:
    log = EventLog(rundir.parent / "state")
    scheduler = FakeScheduler()
    seen: list[str] = []
    server = ControlServer(
        scheduler,
        lambda c: seen.append(c) or {},
        path=rundir / "control.sock",
        log=log,
        uid_of=lambda _conn: os.getuid() + 1,
    )
    server.start()
    try:
        with Pump(scheduler, server):
            assert raw(server.path, b'{"cmd":"pause"}\n') == b""
        assert seen == []
        events = [json.loads(x) for x in log.events_path.read_text().splitlines()]
        assert events[-1]["event"] == "control_rejected"
        assert events[-1]["inputs"]["peer_uid"] == str(os.getuid() + 1)
    finally:
        server.stop()
        log.close()


def test_peer_uid_reads_our_own_uid(rundir: Path) -> None:
    a, b = socket.socketpair()
    try:
        assert control.peer_uid(a) == os.getuid()
    finally:
        a.close()
        b.close()


def test_a_handler_exception_is_contained(rundir: Path) -> None:
    def boom(_: str) -> dict[str, Any]:
        raise RuntimeError("bug")

    log = EventLog(rundir.parent / "state")
    server, scheduler, _ = make_server(rundir, log, boom)
    try:
        with Pump(scheduler, server):
            reply = send_command("pause", path=server.path)
            assert reply["ok"] is False
            assert send_command("status", path=server.path)["ok"] is False  # still serving
        events = [json.loads(x) for x in log.events_path.read_text().splitlines()]
        assert events[-1]["event"] == "control_error"
    finally:
        server.stop()
        log.close()


def test_a_silent_client_is_dropped(rundir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control, "CLIENT_TIMEOUT_S", 0.1)
    server, scheduler, seen = make_server(rundir)
    try:
        with Pump(scheduler, server):
            silent = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            silent.connect(str(server.path))
            reply = send_command("pause", path=server.path, timeout=3)  # queued behind it
            silent.close()
        assert reply["ok"] is True
        assert seen == ["pause"]
    finally:
        server.stop()


def test_a_stale_socket_file_is_replaced(rundir: Path) -> None:
    rundir.mkdir(parents=True, mode=0o700)
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(rundir / "control.sock"))
    stale.close()  # file stays behind, nobody listens
    server, scheduler, _ = make_server(rundir)
    try:
        with Pump(scheduler, server):
            assert send_command("status", path=server.path)["ok"] is True
    finally:
        server.stop()


def test_a_regular_file_at_the_socket_path_is_not_deleted(rundir: Path) -> None:
    rundir.mkdir(parents=True, mode=0o700)
    (rundir / "control.sock").write_text("precious")
    with pytest.raises(OSError, match=r"in use|exists"):
        make_server(rundir)
    assert (rundir / "control.sock").read_text() == "precious"


def test_stop_twice_and_spurious_wakeup(rundir: Path) -> None:
    server, scheduler, _ = make_server(rundir)
    scheduler.ready(server._sock.fileno())  # type: ignore[union-attr]  # nobody connected
    server.stop()
    server.stop()
    assert server._on_readable() is False


# -- client -----------------------------------------------------------------------------------


def test_client_reports_no_daemon(rundir: Path) -> None:
    with pytest.raises(DaemonNotRunning):
        send_command("status", path=rundir / "control.sock")


def test_client_refused_connection_is_not_running(rundir: Path) -> None:
    rundir.mkdir(parents=True)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dead.bind(str(rundir / "control.sock"))
    dead.close()
    with pytest.raises(DaemonNotRunning):
        send_command("status", path=rundir / "control.sock")


def serve_once(path: Path, reply: bytes, wait: float = 0.0) -> threading.Thread:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)

    def run() -> None:
        conn, _ = listener.accept()
        conn.recv(100)
        if wait:
            threading.Event().wait(wait)
        with contextlib.suppress(OSError):  # the client may have given up already
            conn.sendall(reply)
        conn.close()
        listener.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("reply", [b"", b"garbage\n", b"[1]\n", b"no newline"])
def test_client_rejects_unusable_replies(rundir: Path, reply: bytes) -> None:
    rundir.mkdir(parents=True)
    thread = serve_once(rundir / "control.sock", reply)
    with pytest.raises(ControlError):
        send_command("status", path=rundir / "control.sock")
    thread.join()


def test_client_times_out(rundir: Path) -> None:
    rundir.mkdir(parents=True)
    thread = serve_once(rundir / "control.sock", b'{"ok":true}\n', wait=1.0)
    with pytest.raises(ControlError, match="in time"):
        send_command("status", path=rundir / "control.sock", timeout=0.1)
    thread.join()


# -- single instance ----------------------------------------------------------------------------


def test_second_instance_is_refused_and_lock_is_reusable(rundir: Path) -> None:
    first = InstanceLock(rundir / "daemon.lock")
    first.acquire()
    try:
        assert stat.S_IMODE((rundir / "daemon.lock").stat().st_mode) == 0o600
        assert (rundir / "daemon.lock").read_text().strip() == str(os.getpid())
        second = InstanceLock(rundir / "daemon.lock")
        with pytest.raises(AlreadyRunning, match="already running"):
            second.acquire()
    finally:
        first.release()
    third = InstanceLock(rundir / "daemon.lock")
    third.acquire()
    third.release()
    third.release()  # twice is fine


def test_lock_open_error_other_than_busy_propagates(
    rundir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any) -> None:
        raise OSError(5, "I/O error")

    monkeypatch.setattr(control.fcntl, "flock", broken)
    with pytest.raises(OSError, match="I/O"):
        InstanceLock(rundir / "daemon.lock").acquire()


def test_default_paths_follow_xdg_runtime_dir() -> None:
    env = {"XDG_RUNTIME_DIR": "/run/user/4242"}
    assert control.socket_path(env) == Path("/run/user/4242/vpn-monitor/control.sock")
    assert control.lock_path(env) == Path("/run/user/4242/vpn-monitor/daemon.lock")
    fallback = control.runtime_dir({})
    assert fallback == Path(f"/run/user/{os.getuid()}/vpn-monitor")
    assert control.runtime_dir({"XDG_RUNTIME_DIR": "relative"}) == fallback
