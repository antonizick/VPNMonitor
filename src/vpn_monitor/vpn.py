"""VPN route probe, interface classifier and change watcher (spec A2, R3, R4, R5; ADR-0003/7/15).

How a reading is made (``docs/VPM_ARCHITECTURE.md`` has the full table):

1. **Probe** each address family with ``ip -4|-6 -j route get <destination>``. The kernel
   answers with the route the *current user's* traffic would take, honouring policy rules,
   fwmarks and per-uid rules (ProtonVPN, Tailscale). It is a lookup only: **no packet is sent**
   (spec S2), and this module never opens a network socket.
2. **Classify** the egress interface from the kernel's own link type (``ip -d -j link show``):
   ``wireguard`` or ``tun`` is a VPN; a ``dummy`` (a leak-guard / kill-switch interface, which
   discards everything sent to it) or a name in ``vpn.leak_guard_interfaces`` is *blocked*; a
   name matching ``vpn.interface_patterns`` is a VPN too. Everything else is an ordinary
   interface. Nothing here is specific to one VPN provider.
3. **Combine** (spec R3): any family routed through an ordinary interface → ``NO_VPN`` (a leak,
   named in the reason); any failed probe → ``UNKNOWN``; no family routed through a VPN (all
   blocked or unreachable: kill switch, no network) → ``NO_VPN``; otherwise ``VPN``.

Every failure (``ip`` missing, timeout, non-JSON output, a crash) resolves to ``UNKNOWN``, which the
engine renders red (spec R4/S6). :meth:`RouteProbe.read` never raises.

:class:`RouteWatcher` is the daemon's :class:`~vpn_monitor.model.VpnSource`: it re-probes on every
route, rule or link change reported by an ``ip monitor`` subprocess (debounced), every
``recheck_interval_s`` while a browser is focused, and restarts the monitor with back-off if it
dies. While the monitor has been down for longer than ``max_reading_age_s`` a positive reading is
downgraded to ``UNKNOWN``, because a VPN drop could no longer be seen in time.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatchcase
from typing import IO, TYPE_CHECKING, Literal, Protocol

from vpn_monitor.config import Config, ProbesConfig, VpnConfig
from vpn_monitor.engine import describe_routes
from vpn_monitor.model import FamilyRoute, RouteKind, VpnCallback, VpnReading, VpnState

if TYPE_CHECKING:
    from vpn_monitor.eventlog import EventLog
    from vpn_monitor.mainloop import Handle, Scheduler

Clock = Callable[[], float]
Family = Literal[4, 6]

VPN_LINK_KINDS = frozenset({"wireguard", "tun"})
"""Kernel link kinds (``linkinfo.info_kind``) that are VPN tunnels."""
BLOCKING_LINK_KINDS = frozenset({"dummy"})
"""Kernel link kinds that discard every packet: a route into one is blocked, not a leak."""

_UNREACHABLE_ERRORS = (
    "network is unreachable",
    "no route to host",
    "address family not supported",
)
"""Kernel answers meaning "this family has no route at all" (not a leak, not protected)."""
_BLOCKED_ERRORS = ("permission denied",)
"""Kernel answers meaning "routing forbids it" (an IPv4 ``prohibit`` route gives EACCES)."""
_BLOCKED_TYPES = frozenset({"blackhole", "prohibit"})
_UNREACHABLE_TYPES = frozenset({"unreachable"})
_MAX_DETAIL = 160


def _c_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Environment for ``ip``: untranslated error messages, so they can be matched.

    The daemon runs with ``LD_PRELOAD=libgtk4-layer-shell.so`` (needed for its own window only).
    A child ``ip`` that inherits it loads GTK first and takes ~200 ms instead of ~5 ms, which made
    every probe 300 to 400 ms, so any layer-shell entry is dropped (other preloads are kept).
    """
    env = dict(os.environ if environ is None else environ)
    preload = [p for p in env.get("LD_PRELOAD", "").split() if "gtk4-layer-shell" not in p]
    if preload:
        env["LD_PRELOAD"] = " ".join(preload)
    else:
        env.pop("LD_PRELOAD", None)
    env.update(LC_ALL="C", LANG="C")
    return env


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _MAX_DETAIL else text[: _MAX_DETAIL - 1] + "…"


# ---------------------------------------------------------------------------------------------
# Running commands
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of one finished command."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], float], CommandResult]
"""Runs a fixed argv with a timeout. May raise ``OSError`` or ``subprocess.TimeoutExpired``."""


def run_command(argv: Sequence[str], timeout_s: float) -> CommandResult:
    """Run ``argv`` (no shell) with a timeout and the C locale."""
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
        env=_c_env(),
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


# ---------------------------------------------------------------------------------------------
# Interface classification
# ---------------------------------------------------------------------------------------------


class Role(Enum):
    """What an egress interface means for the reading."""

    VPN = "vpn"
    BLOCKER = "blocker"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class LinkInfo:
    """Classification of one interface, with the reason (for the log)."""

    role: Role
    why: str


class LinkClassifier:
    """Classifies interfaces by kernel link kind and configured name globs (ADR-0015).

    Link kinds are read with ``ip -d -j link show`` and cached; the cache is dropped by
    :meth:`invalidate` (the watcher calls it on every change burst) and reloaded on demand, also
    whenever an interface is not in it. If the kinds cannot be read, only the name globs apply.
    """

    def __init__(
        self,
        interface_patterns: Iterable[str],
        leak_guard_interfaces: Iterable[str],
        *,
        runner: Runner = run_command,
        timeout_s: float = 1.0,
    ) -> None:
        self._patterns = tuple(interface_patterns)
        self._leak_guards = tuple(leak_guard_interfaces)
        self._runner = runner
        self._timeout_s = timeout_s
        self._kinds: dict[str, str] | None = None
        self.last_error: str | None = None

    def invalidate(self) -> None:
        """Forget the cached link kinds; the next :meth:`classify` reloads them."""
        self._kinds = None

    def refresh(self) -> dict[str, str] | None:
        """Reload link kinds. Returns them, or ``None`` (and sets ``last_error``) on failure."""
        try:
            result = self._runner(["ip", "-d", "-j", "link", "show"], self._timeout_s)
            if result.returncode != 0:
                raise ValueError(f"exit {result.returncode}: {_short(result.stderr)}")
            data = json.loads(result.stdout)
            if not isinstance(data, list):
                raise ValueError("not a JSON list")
            kinds: dict[str, str] = {}
            for link in data:
                if not isinstance(link, dict) or not isinstance(link.get("ifname"), str):
                    continue
                info = link.get("linkinfo")
                kind = info.get("info_kind") if isinstance(info, dict) else None
                kinds[link["ifname"]] = kind if isinstance(kind, str) else ""
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.last_error = f"cannot read link kinds: {_short(str(exc)) or type(exc).__name__}"
            self._kinds = None
            return None
        self.last_error = None
        self._kinds = kinds
        return kinds

    def classify(self, ifname: str) -> LinkInfo:
        """Classify ``ifname`` (reloading the link kinds if it is not cached)."""
        kinds = self._kinds
        if kinds is None or ifname not in kinds:
            kinds = self.refresh()
        kind = kinds.get(ifname, "") if kinds is not None else ""
        for glob in self._leak_guards:
            if fnmatchcase(ifname, glob):
                return LinkInfo(Role.BLOCKER, f"leak guard, name matches {glob!r}")
        if kind in BLOCKING_LINK_KINDS:
            return LinkInfo(Role.BLOCKER, f"{kind} device, discards traffic")
        if kind in VPN_LINK_KINDS:
            return LinkInfo(Role.VPN, f"{kind} device")
        for glob in self._patterns:
            if fnmatchcase(ifname, glob):
                return LinkInfo(Role.VPN, f"name matches {glob!r}")
        if kinds is None:
            return LinkInfo(Role.OTHER, f"not a VPN by name; {self.last_error}")
        return LinkInfo(Role.OTHER, f"{kind + ' device' if kind else 'ordinary device'}, not a VPN")


# ---------------------------------------------------------------------------------------------
# One family
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamilyResult:
    """A probed family: the route plus a human explanation for the reason string."""

    route: FamilyRoute
    detail: str


def probe_family(
    family: Family,
    destination: str,
    *,
    classifier: LinkClassifier,
    runner: Runner = run_command,
    timeout_s: float = 1.0,
) -> FamilyResult:
    """Look up the route to ``destination`` for one family. Never raises for I/O problems."""

    def result(
        kind: RouteKind, detail: str, dev: str | None = None, vpn: bool = False
    ) -> FamilyResult:
        return FamilyResult(FamilyRoute(family, destination, dev, kind, vpn), detail)

    argv = ["ip", f"-{family}", "-j", "route", "get", destination]
    try:
        out = runner(argv, timeout_s)
    except FileNotFoundError:
        return result(RouteKind.ERROR, "probe failed: the `ip` command was not found")
    except subprocess.TimeoutExpired:
        return result(RouteKind.ERROR, f"probe failed: `ip route get` timed out ({timeout_s:g} s)")
    except (OSError, subprocess.SubprocessError) as exc:
        return result(RouteKind.ERROR, f"probe failed: {_short(str(exc)) or type(exc).__name__}")

    if out.returncode != 0:
        message = _short(out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "")
        lowered = message.lower()
        if any(text in lowered for text in _UNREACHABLE_ERRORS):
            return result(RouteKind.UNREACHABLE, f"unreachable (kernel: {message})")
        if any(text in lowered for text in _BLOCKED_ERRORS):
            return result(RouteKind.BLOCKED, f"blocked by a prohibit route (kernel: {message})")
        return result(
            RouteKind.ERROR, f"probe failed: `ip route get` exit {out.returncode}: {message or '?'}"
        )

    try:
        data = json.loads(out.stdout)
    except ValueError:
        return result(RouteKind.ERROR, "probe failed: `ip route get` did not print JSON")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return result(RouteKind.ERROR, "probe failed: `ip route get` printed no route")
    entry = data[0]
    route_type = entry.get("type", "unicast")
    if route_type in _UNREACHABLE_TYPES:
        return result(RouteKind.UNREACHABLE, "unreachable (unreachable route)")
    if route_type in _BLOCKED_TYPES:
        return result(RouteKind.BLOCKED, f"blocked ({route_type} route)")
    if route_type != "unicast":
        return result(RouteKind.ERROR, f"probe failed: unexpected route type {route_type!r}")
    dev = entry.get("dev")
    if not isinstance(dev, str) or not dev:
        return result(RouteKind.ERROR, "probe failed: the route names no interface")

    info = classifier.classify(dev)
    table = entry.get("table")
    where = f"{dev} ({info.why}" + (f", table {table})" if isinstance(table, str) else ")")
    if info.role is Role.BLOCKER:
        return result(RouteKind.BLOCKED, f"blocked by {where}", dev)
    if info.role is Role.VPN:
        return result(RouteKind.ROUTED, f"via VPN {where}", dev, vpn=True)
    return result(RouteKind.ROUTED, f"via {where}", dev)


# ---------------------------------------------------------------------------------------------
# Combining families (spec R3)
# ---------------------------------------------------------------------------------------------


def combine(results: Sequence[FamilyResult], timestamp: float) -> VpnReading:
    """Turn per-family results into one reading. ``routes`` always agrees with ``state``."""
    routes = tuple(r.route for r in results)
    if not results:
        return VpnReading(VpnState.UNKNOWN, (), "no address family was probed", timestamp)

    def reading(state: VpnState, headline: str) -> VpnReading:
        details = "; ".join(f"IPv{r.route.family} {r.detail}" for r in results)
        return VpnReading(state, routes, f"{headline}: {details}", timestamp)

    leaks = [r.route for r in results if r.route.kind is RouteKind.ROUTED and not r.route.is_vpn]
    if leaks:
        names = ", ".join(f"IPv{r.family} via {r.egress_interface}" for r in leaks)
        return reading(VpnState.NO_VPN, f"not through a VPN ({names})")
    if any(r.route.kind is RouteKind.ERROR for r in results):
        return reading(VpnState.UNKNOWN, "VPN state unknown")
    if not any(r.route.kind is RouteKind.ROUTED for r in results):
        return reading(VpnState.NO_VPN, "no route through a VPN (kill switch or no network)")
    return reading(VpnState.VPN, "all internet routes go through a VPN")


class RouteProbe:
    """Makes one complete :class:`VpnReading` on demand."""

    def __init__(
        self,
        vpn: VpnConfig,
        probes: ProbesConfig,
        *,
        runner: Runner = run_command,
        clock: Clock = time.monotonic,
        classifier: LinkClassifier | None = None,
    ) -> None:
        self._families: tuple[tuple[Family, str], ...] = ((4, probes.ipv4), (6, probes.ipv6))
        self._runner = runner
        self._clock = clock
        self._timeout_s = vpn.probe_timeout_s
        self.classifier = classifier or LinkClassifier(
            vpn.interface_patterns,
            vpn.leak_guard_interfaces,
            runner=runner,
            timeout_s=vpn.probe_timeout_s,
        )

    @classmethod
    def from_config(
        cls, config: Config, *, runner: Runner = run_command, clock: Clock = time.monotonic
    ) -> RouteProbe:
        return cls(config.vpn, config.probes, runner=runner, clock=clock)

    def read(self) -> VpnReading:
        """Probe every family. Never raises: anything unexpected is an UNKNOWN reading."""
        timestamp = self._clock()  # start of the probe: the conservative (older) time
        try:
            results = [
                probe_family(
                    family,
                    destination,
                    classifier=self.classifier,
                    runner=self._runner,
                    timeout_s=self._timeout_s,
                )
                for family, destination in self._families
            ]
            return combine(results, timestamp)
        except Exception as exc:  # fail-safe (R4): a bug must never become blue
            return VpnReading(
                VpnState.UNKNOWN, (), f"probe crashed: {type(exc).__name__}: {exc}", timestamp
            )


def read_vpn_state(config: Config | None = None) -> VpnReading:
    """Probe the kernel routing table once; any failure gives an UNKNOWN reading."""
    return RouteProbe.from_config(config or Config()).read()


# ---------------------------------------------------------------------------------------------
# Change watcher (ADR-0007)
# ---------------------------------------------------------------------------------------------


class ChangeStream(Protocol):
    """A running source of change notifications (one line per change)."""

    @property
    def fd(self) -> int:
        """File descriptor to watch for readability."""
        ...

    def read_available(self) -> bytes | None:
        """Read what is available: data, ``b""`` at end of stream, ``None`` if nothing yet."""
        ...

    def close(self) -> None:
        """Stop the source. Safe to call twice."""
        ...


Spawner = Callable[[], ChangeStream]
"""Starts a :class:`ChangeStream`; raises ``OSError`` if it cannot."""


class IpMonitorStream:
    """``ip monitor route rule link`` as a :class:`ChangeStream` (non-blocking pipe)."""

    ARGV = ("ip", "monitor", "route", "rule", "link")

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            self.ARGV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_c_env(),
        )
        stdout: IO[bytes] | None = self._proc.stdout
        assert stdout is not None
        self._stdout = stdout
        os.set_blocking(stdout.fileno(), False)
        self._closed = False

    @property
    def fd(self) -> int:
        return self._stdout.fileno()

    def read_available(self) -> bytes | None:
        try:
            return os.read(self.fd, 65536)
        except BlockingIOError:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._stdout.close()


DEBOUNCE_S = 0.2
"""Coalesce a burst of route/link events into one probe this long after its first event."""
RESTART_INITIAL_S = 0.5
RESTART_MAX_S = 30.0
HEALTHY_AFTER_S = 1.0
"""A (re)started monitor counts as up once it has run this long or delivered an event."""
BACKOFF_RESET_S = 30.0
"""A monitor that ran at least this long before dying restarts with the initial back-off."""


class RouteWatcher:
    """:class:`~vpn_monitor.model.VpnSource` driven by route changes and a focused re-check.

    * ``start`` spawns the change stream and probes at once.
    * Every burst of change lines → one probe :data:`DEBOUNCE_S` after the burst's first line.
    * ``set_active(True)`` probes at once and then every ``recheck_interval_s``; ``False``
      cancels the re-check (no polling while no browser is focused, spec R5/R13). Change
      events are still handled while inactive (they cost nothing between events).
    * If the stream dies or cannot start, it is restarted with exponential back-off.
    """

    def __init__(
        self,
        config: Config,
        scheduler: Scheduler,
        *,
        probe: RouteProbe | None = None,
        spawner: Spawner = IpMonitorStream,
        clock: Clock = time.monotonic,
        log: EventLog | None = None,
    ) -> None:
        self._config = config
        self._scheduler = scheduler
        self._clock = clock
        self._probe = probe or RouteProbe.from_config(config, clock=clock)
        self._spawner = spawner
        self._log = log

        self._callback: VpnCallback | None = None
        self._active = False
        self._stream: ChangeStream | None = None
        self._watch: Handle | None = None
        self._debounce: Handle | None = None
        self._recheck: Handle | None = None
        self._restart: Handle | None = None
        self._healthy_timer: Handle | None = None
        self._backoff_s = RESTART_INITIAL_S
        self._spawned_at = 0.0
        self._down_since: float | None = None
        self._was_up = False
        self._burst_started: float | None = None
        self._logged: tuple[VpnState, str] | None = None

        self.last_reading: VpnReading | None = None
        self.last_trigger = ""
        """Why the last probe ran: ``start``, ``activate``, ``recheck``, ``route-change``…"""
        self.last_latency_s: float | None = None
        """For a ``route-change`` probe: seconds from the burst's first event to the reading."""
        self.events_seen = 0

    # -- VpnSource ----------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._callback is not None

    @property
    def watcher_up(self) -> bool:
        """True while the change stream runs and has proved itself."""
        return self._stream is not None and self._down_since is None

    def start(self, callback: VpnCallback) -> None:
        if self._callback is not None:
            raise RuntimeError("RouteWatcher already started")
        self._callback = callback
        self._down_since = self._clock()  # not up until the stream proves itself
        self._spawn()
        self.probe_now("start")

    def stop(self) -> None:
        self._callback = None
        for handle in (self._debounce, self._recheck, self._restart):
            if handle is not None:
                self._scheduler.cancel(handle)
        self._debounce = self._recheck = self._restart = None
        self._close_stream()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        if not active:
            if self._recheck is not None:
                self._scheduler.cancel(self._recheck)
                self._recheck = None
        elif self._callback is not None:
            self.probe_now("activate")

    # -- probing ------------------------------------------------------------------------------

    def probe_now(self, trigger: str) -> VpnReading | None:
        """Probe immediately, deliver the reading and reschedule the re-check."""
        callback = self._callback
        if callback is None:
            return None
        reading = self._downgrade_if_blind(self._probe.read())
        latency: float | None = None
        if trigger == "route-change" and self._burst_started is not None:
            latency = max(0.0, self._clock() - self._burst_started)
        self._burst_started = None
        self.last_reading, self.last_trigger, self.last_latency_s = reading, trigger, latency
        self._log_reading(reading, trigger, latency)

        if self._recheck is not None:
            self._scheduler.cancel(self._recheck)
            self._recheck = None
        if self._active:
            self._recheck = self._scheduler.call_later(
                self._config.vpn.recheck_interval_s, self._on_recheck
            )
        callback(reading)
        return reading

    def _on_recheck(self) -> None:
        self._recheck = None
        self.probe_now("recheck")

    def _downgrade_if_blind(self, reading: VpnReading) -> VpnReading:
        if reading.state is not VpnState.VPN or self._down_since is None:
            return reading
        down_for = self._clock() - self._down_since
        if down_for <= self._config.vpn.max_reading_age_s:
            return reading
        return VpnReading(
            VpnState.UNKNOWN,
            reading.routes,
            f"route-change watcher down for {down_for:.0f} s, a VPN drop would be missed; "
            f"last probe: {reading.reason}",
            reading.timestamp,
        )

    def _log_reading(self, reading: VpnReading, trigger: str, latency: float | None) -> None:
        key = (reading.state, reading.reason)
        if self._log is None or key == self._logged:
            return
        self._logged = key
        inputs = {
            "vpn_state": reading.state.value,
            "routes": describe_routes(reading),
            "trigger": trigger,
        }
        if latency is not None:
            inputs["latency_ms"] = f"{latency * 1000:.0f}"
        self._log.record("reading", reason=reading.reason, inputs=inputs)

    def _error(self, reason: str) -> None:
        if self._log is not None:
            self._log.error("vpn_watcher", reason, {"restart_in_s": f"{self._backoff_s:g}"})

    # -- change stream ------------------------------------------------------------------------

    def _spawn(self) -> None:
        self._restart = None
        if self._callback is None:
            return
        try:
            stream = self._spawner()
        except (OSError, subprocess.SubprocessError) as exc:
            self._error(f"cannot start the route monitor: {_short(str(exc))}")
            self._schedule_restart()
            return
        self._stream = stream
        self._spawned_at = self._clock()
        self._watch = self._scheduler.watch_fd(stream.fd, self._on_readable)
        self._healthy_timer = self._scheduler.call_later(HEALTHY_AFTER_S, self._mark_healthy)

    def _mark_healthy(self) -> None:
        self._healthy_timer = None
        if self._stream is None or self._down_since is None:
            return
        down_s = self._clock() - self._down_since
        self._down_since = None
        if not self._was_up:
            self._was_up = True
            return
        if self._log is not None:
            self._log.record(
                "vpn_watcher",
                reason="route monitor running again",
                inputs={"down_s": f"{down_s:.1f}"},
            )
        self.probe_now("watcher-restart")  # changes may have been missed while down

    def _on_readable(self) -> bool:
        stream = self._stream
        if stream is None:
            return False
        try:
            data = stream.read_available()
        except OSError as exc:
            self._watch = None  # returning False removes the watch
            self._on_death(f"route monitor read failed: {_short(str(exc))}")
            return False
        if data is None:
            return True
        if not data:
            self._watch = None
            self._on_death("route monitor exited")
            return False
        self.events_seen += max(1, data.count(b"\n"))
        if self._down_since is not None and self._healthy_timer is not None:
            self._scheduler.cancel(self._healthy_timer)
            self._mark_healthy()
        self._on_change()
        return True

    def _on_change(self) -> None:
        self._probe.classifier.invalidate()  # a link may have appeared or changed kind
        if self._debounce is None:
            self._burst_started = self._clock()
            self._debounce = self._scheduler.call_later(DEBOUNCE_S, self._on_debounced)

    def _on_debounced(self) -> None:
        self._debounce = None
        self.probe_now("route-change")

    def _on_death(self, reason: str) -> None:
        ran_for = self._clock() - self._spawned_at
        self._close_stream()
        if self._down_since is None:
            self._down_since = self._clock()
        if ran_for >= BACKOFF_RESET_S:
            self._backoff_s = RESTART_INITIAL_S
        self._error(reason)
        self._schedule_restart()

    def _schedule_restart(self) -> None:
        if self._callback is None or self._restart is not None:
            return
        delay = self._backoff_s
        self._backoff_s = min(self._backoff_s * 2, RESTART_MAX_S)
        self._restart = self._scheduler.call_later(delay, self._spawn)

    def _close_stream(self) -> None:
        if self._watch is not None:
            self._scheduler.cancel(self._watch)
            self._watch = None
        if self._healthy_timer is not None:
            self._scheduler.cancel(self._healthy_timer)
            self._healthy_timer = None
        if self._stream is not None:
            stream, self._stream = self._stream, None
            stream.close()
