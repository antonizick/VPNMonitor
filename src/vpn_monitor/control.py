"""Unix control socket: daemon side and client (spec R10, S5).

Protocol: one request per connection, one JSON object terminated by a newline, one JSON reply
terminated by a newline. A request is ``{"cmd": "pause" | "resume" | "toggle" | "status"}``.
Anything else is rejected and logged (S5).

Hardening: the directory is ``0700``, the socket ``0600``, and every peer's uid is read with
``SO_PEERCRED`` and must equal the daemon's own uid. Requests are capped at ``MAX_REQUEST`` bytes
and a silent client is dropped after ``CLIENT_TIMEOUT_S``. The socket is a Unix socket: there is no
network listener (S2).

A single-instance guard (:class:`InstanceLock`, an ``flock`` on a lock file next to the socket)
makes a second ``vpn-monitor run`` exit with a clear message instead of stealing the socket.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import socket
import stat
import struct
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from vpn_monitor.eventlog import EventLog
from vpn_monitor.mainloop import Handle, Scheduler

COMMANDS = ("pause", "resume", "toggle", "status")
MAX_REQUEST = 4096
CLIENT_TIMEOUT_S = 0.5
"""How long the daemon waits for a connected client's request line."""
REPLY_TIMEOUT_S = 3.0
"""How long the client waits for the daemon's reply."""

Handler = Callable[[str], dict[str, Any]]
"""Runs a command (one of :data:`COMMANDS`) and returns the reply payload."""


class ControlError(Exception):
    """The control channel could not be used."""


class DaemonNotRunning(ControlError):
    """Nothing is listening on the control socket."""


class AlreadyRunning(ControlError):
    """Another daemon already holds the single-instance lock."""


def runtime_dir(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_RUNTIME_DIR/vpn-monitor`` (falls back to ``/run/user/<uid>``)."""
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or ""
    root = Path(base) if os.path.isabs(base) else Path(f"/run/user/{os.getuid()}")
    return root / "vpn-monitor"


def socket_path(env: Mapping[str, str] | None = None) -> Path:
    return runtime_dir(env) / "control.sock"


def lock_path(env: Mapping[str, str] | None = None) -> Path:
    return runtime_dir(env) / "daemon.lock"


def ensure_private_dir(path: Path) -> None:
    """Create ``path`` with mode ``0700`` and make sure it is ours and not group/world-able."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ControlError(f"{path} is not a directory owned by you")
    if stat.S_IMODE(info.st_mode) != 0o700:
        path.chmod(0o700)


class InstanceLock:
    """Exclusive, non-blocking ``flock``; released when the process exits or on :meth:`release`."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = lock_path() if path is None else path
        self._fd: int | None = None

    def acquire(self) -> None:
        ensure_private_dir(self.path.parent)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise AlreadyRunning("another instance is already running") from exc
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


def peer_uid(conn: socket.socket) -> int:
    """uid of the process on the other end of ``conn`` (``SO_PEERCRED``)."""
    raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", raw)
    return int(uid)


class ControlServer:
    """Accepts one-line JSON commands on the control socket and passes them to ``handler``."""

    def __init__(
        self,
        scheduler: Scheduler,
        handler: Handler,
        *,
        path: Path | None = None,
        log: EventLog | None = None,
        uid_of: Callable[[socket.socket], int] = peer_uid,
    ) -> None:
        self.path = socket_path() if path is None else path
        self._scheduler = scheduler
        self._handler = handler
        self._log = log
        self._uid_of = uid_of
        self._sock: socket.socket | None = None
        self._watch: Handle | None = None

    def start(self) -> None:
        ensure_private_dir(self.path.parent)
        old_umask = os.umask(0o177)  # the socket is created 0600, with no window of exposure
        try:
            self._unlink_stale()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self.path))
        finally:
            os.umask(old_umask)
        self.path.chmod(0o600)
        sock.listen(8)
        sock.setblocking(False)
        self._sock = sock
        self._watch = self._scheduler.watch_fd(sock.fileno(), self._on_readable)

    def stop(self) -> None:
        if self._watch is not None:
            self._scheduler.cancel(self._watch)
            self._watch = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def _unlink_stale(self) -> None:
        # The single-instance lock is held by the caller, so any leftover socket is stale.
        with contextlib.suppress(FileNotFoundError):
            if stat.S_ISSOCK(self.path.lstat().st_mode):
                self.path.unlink()

    def _event(self, event: str, reason: str, inputs: Mapping[str, str] | None = None) -> None:
        if self._log is not None:
            self._log.record(event, reason=reason, inputs=inputs)

    def _on_readable(self) -> bool:
        sock = self._sock
        if sock is None:
            return False
        try:
            conn, _ = sock.accept()
        except (BlockingIOError, InterruptedError):
            return True
        except OSError as exc:
            self._event("control_error", f"accept failed: {exc.strerror or exc}")
            return True
        with conn:
            self._serve(conn)
        return True

    def _serve(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(CLIENT_TIMEOUT_S)
            uid = self._uid_of(conn)
            if uid != os.getuid():
                self._event("control_rejected", "peer uid differs", {"peer_uid": str(uid)})
                return  # no reply: a stranger learns nothing
            reply = self._dispatch(_read_line(conn))
            conn.sendall(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
        except OSError as exc:  # includes timeouts
            self._event("control_error", f"client i/o failed: {type(exc).__name__}")

    def _dispatch(self, line: bytes | None) -> dict[str, Any]:
        if line is None:
            self._event("control_rejected", "request too long or unterminated")
            return {"ok": False, "error": "bad request"}
        try:
            request = json.loads(line)
        except ValueError:
            request = None
        command = request.get("cmd") if isinstance(request, dict) else None
        if not isinstance(command, str) or command not in COMMANDS:
            shown = command if isinstance(command, str) and command.isprintable() else "?"
            self._event("control_rejected", "unknown command", {"command": shown[:40]})
            return {"ok": False, "error": "unknown command"}
        try:
            payload = self._handler(command)
        except Exception as exc:  # a handler bug must not take the daemon down
            self._event("control_error", f"{command} failed: {type(exc).__name__}: {exc}")
            return {"ok": False, "error": "command failed"}
        return {"ok": True, **payload}


def _read_line(conn: socket.socket) -> bytes | None:
    """Read up to the first newline; ``None`` if it exceeds ``MAX_REQUEST`` or never ends."""
    data = b""
    while b"\n" not in data:
        chunk = conn.recv(MAX_REQUEST + 1 - len(data))
        if not chunk:
            return None
        data += chunk
        if len(data) > MAX_REQUEST:
            return None
    return data.split(b"\n", 1)[0]


def send_command(
    command: str, *, path: Path | None = None, timeout: float = REPLY_TIMEOUT_S
) -> dict[str, Any]:
    """Send ``command`` to the running daemon and return its reply.

    Raises :class:`DaemonNotRunning` if nothing is listening and :class:`ControlError` if the
    reply is unusable.
    """
    target = socket_path() if path is None else path
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        try:
            sock.connect(str(target))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            raise DaemonNotRunning("vpn-monitor is not running") from exc
        sock.sendall(json.dumps({"cmd": command}).encode() + b"\n")
        reply = _read_line(sock)
    except TimeoutError as exc:
        raise ControlError("the daemon did not answer in time") from exc
    except OSError as exc:
        raise ControlError(f"cannot talk to the daemon: {exc.strerror or exc}") from exc
    finally:
        sock.close()
    try:
        parsed = json.loads(reply) if reply is not None else None
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        raise ControlError("the daemon sent an unusable reply")
    return parsed
