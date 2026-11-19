"""Route probe, classifier and combination rules (spec R3, R4, S2, S6; ADR-0015)."""

from __future__ import annotations

import ast
import ipaddress
import itertools
import json
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor import vpn
from vpn_monitor.config import Config, ProbesConfig, VpnConfig
from vpn_monitor.engine import reading_problem
from vpn_monitor.model import FamilyRoute, RouteKind, VpnState
from vpn_monitor.vpn import (
    CommandResult,
    FamilyResult,
    LinkClassifier,
    Role,
    RouteProbe,
    combine,
    probe_family,
)

FIXTURES = Path(__file__).parent / "fixtures" / "routes"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))
SRC = Path(__file__).resolve().parents[1] / "src" / "vpn_monitor"

V4, V6 = "192.0.2.1", "2001:db8::1111"
LINKS = json.dumps(
    [
        {"ifname": "lo"},
        {"ifname": "wlo1"},
        {"ifname": "proton0", "linkinfo": {"info_kind": "wireguard"}},
        {"ifname": "tailscale0", "linkinfo": {"info_kind": "tun"}},
        {"ifname": "ipv6leakintrf0", "linkinfo": {"info_kind": "dummy"}},
        {"ifname": "sit0", "linkinfo": {"info_kind": "sit"}},
        {"ifname": "corpvpn", "linkinfo": {"info_kind": "wireguard"}},
    ]
)


def ok(stdout: str) -> CommandResult:
    return CommandResult(0, stdout, "")


def route(dev: str, dst: str = V4, **extra: Any) -> CommandResult:
    return ok(json.dumps([{"dst": dst, "dev": dev, **extra}]))


class FakeRunner:
    """Answers ``ip`` commands from a table; records every argv."""

    def __init__(
        self,
        route4: CommandResult | BaseException,
        route6: CommandResult | BaseException,
        links: CommandResult | BaseException = ok(LINKS),  # noqa: B008
    ) -> None:
        self.answers = {"-4": route4, "-6": route6, "-d": links}
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    def __call__(self, argv: Sequence[str], timeout_s: float) -> CommandResult:
        self.calls.append(list(argv))
        self.timeouts.append(timeout_s)
        assert argv[0] == "ip"
        answer = self.answers[argv[1]]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def make_probe(runner: FakeRunner, **vpn_kwargs: Any) -> RouteProbe:
    return RouteProbe(
        VpnConfig(**vpn_kwargs), ProbesConfig(ipv4=V4, ipv6=V6), runner=runner, clock=lambda: 5.0
    )


def summary(routes: Sequence[FamilyRoute]) -> list[list[object]]:
    return [[r.family, r.egress_interface, r.kind.value, r.is_vpn] for r in routes]


# ---------------------------------------------------------------------------------------------
# Fixture scenarios
# ---------------------------------------------------------------------------------------------


def _command(spec: dict[str, Any]) -> CommandResult:
    return CommandResult(spec["returncode"], spec["stdout"], spec["stderr"])


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=[p.stem for p in FIXTURE_FILES])
def test_fixture_scenarios(path: Path) -> None:
    doc = json.loads(path.read_text())
    cmds = doc["commands"]
    runner = FakeRunner(_command(cmds["route4"]), _command(cmds["route6"]), _command(cmds["links"]))
    probes = ProbesConfig(**doc["probes"])
    reading = RouteProbe(VpnConfig(), probes, runner=runner, clock=lambda: 7.0).read()

    assert reading.state.value == doc["expect"]["state"], reading.reason
    assert summary(reading.routes) == doc["expect"]["routes"]
    assert reading.timestamp == 7.0
    # The engine's independent gate must agree with the detector's verdict (ADR-0013).
    problem = reading_problem(reading, now=7.0, max_age_s=10.0)
    assert (problem is None) == (reading.state is VpnState.VPN), problem


def test_fixtures_cover_the_prompt_scenarios() -> None:
    names = {p.stem for p in FIXTURE_FILES}
    for needed in (
        "proton_up",
        "proton_down",
        "proton_up_v6_leak_guard",
        "tailscale_mesh_only",
        "tailscale_exit_node",
        "split_v6_leak",
        "kill_switch_no_tunnel",
        "garbage_output",
    ):
        assert needed in names


_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_IPV6 = re.compile(
    r"(?<![0-9A-Za-z:])(?=[0-9A-Fa-f:]*:[0-9A-Fa-f:]*:)[0-9A-Fa-f:]{2,39}(?![0-9A-Za-z:])"
)
_MAC = re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.IGNORECASE)


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=[p.stem for p in FIXTURE_FILES])
def test_fixtures_hold_no_public_address_mac_or_ssid(path: Path) -> None:
    text = path.read_text()
    found = _IPV4.findall(text) + _IPV6.findall(text)
    assert found, "the address scan found nothing; the pattern is broken"
    for token in found:
        try:
            address = ipaddress.ip_address(token)
        except ValueError:
            continue
        assert not address.is_global, f"{path.name}: public address {token}"
    assert not _MAC.search(text), f"{path.name}: MAC address"
    assert "ssid" not in text.lower()
    assert "address" not in json.loads(text)["commands"]["links"]["stdout"]


# ---------------------------------------------------------------------------------------------
# One family: kernel answers and failures
# ---------------------------------------------------------------------------------------------


def family(answer: CommandResult | BaseException, fam: int = 4) -> FamilyResult:
    runner = FakeRunner(answer, answer)
    classifier = LinkClassifier(VpnConfig().interface_patterns, (), runner=runner)
    return probe_family(4 if fam == 4 else 6, V4, classifier=classifier, runner=runner)


@pytest.mark.parametrize(
    ("answer", "kind", "text"),
    [
        (CommandResult(2, "", "RTNETLINK answers: Network is unreachable\n"), "unreachable", ""),
        (CommandResult(2, "", "RTNETLINK answers: No route to host\n"), "unreachable", ""),
        (
            CommandResult(2, "", "RTNETLINK answers: Address family not supported by protocol"),
            "unreachable",
            "",
        ),
        (CommandResult(2, "", "RTNETLINK answers: Permission denied\n"), "blocked", "prohibit"),
        (CommandResult(2, "", "RTNETLINK answers: Invalid argument\n"), "error", "exit 2"),
        (CommandResult(1, "", ""), "error", "exit 1: ?"),
        (ok(json.dumps([{"type": "unreachable", "dst": V4, "dev": "lo"}])), "unreachable", ""),
        (ok(json.dumps([{"type": "prohibit", "dst": V4, "dev": "lo"}])), "blocked", "prohibit"),
        (ok(json.dumps([{"type": "blackhole", "dst": V4, "dev": "lo"}])), "blocked", "blackhole"),
        (ok(json.dumps([{"type": "local", "dst": V4, "dev": "lo"}])), "error", "'local'"),
        (ok("not json"), "error", "did not print JSON"),
        (ok("[]"), "error", "printed no route"),
        (ok("{}"), "error", "printed no route"),
        (ok("[1]"), "error", "printed no route"),
        (ok(json.dumps([{"dst": V4}])), "error", "names no interface"),
        (ok(json.dumps([{"dst": V4, "dev": ""}])), "error", "names no interface"),
        (FileNotFoundError("ip"), "error", "`ip` command was not found"),
        (subprocess.TimeoutExpired(["ip"], 1.0), "error", "timed out"),
        (PermissionError("denied"), "error", "denied"),
        (OSError(), "error", "OSError"),
    ],
)
def test_family_outcomes(answer: CommandResult | BaseException, kind: str, text: str) -> None:
    result = family(answer)
    assert result.route.kind.value == kind
    assert text in result.detail
    assert not result.route.is_vpn


def test_probe_argv_is_fixed_and_per_family() -> None:
    runner = FakeRunner(route("proton0"), route("proton0", V6))
    make_probe(runner, probe_timeout_s=0.5).read()
    assert ["ip", "-4", "-j", "route", "get", V4] in runner.calls
    assert ["ip", "-6", "-j", "route", "get", V6] in runner.calls
    assert ["ip", "-d", "-j", "link", "show"] in runner.calls
    assert set(runner.timeouts) == {0.5}


def test_table_is_named_in_the_detail() -> None:
    reading = make_probe(
        FakeRunner(route("proton0", table="245447468"), route("proton0", V6))
    ).read()
    assert "proton0 (wireguard device, table 245447468)" in reading.reason


# ---------------------------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------------------------


def classifier(links: CommandResult | BaseException = ok(LINKS), **kw: Any) -> LinkClassifier:  # noqa: B008
    runner = FakeRunner(ok("[]"), ok("[]"), links)
    cfg = VpnConfig(**kw)
    return LinkClassifier(cfg.interface_patterns, cfg.leak_guard_interfaces, runner=runner)


@pytest.mark.parametrize(
    ("ifname", "role", "why"),
    [
        ("proton0", Role.VPN, "wireguard device"),
        ("corpvpn", Role.VPN, "wireguard device"),  # any name: kind decides (generic)
        ("tailscale0", Role.VPN, "tun device"),
        ("ipv6leakintrf0", Role.BLOCKER, "leak guard"),
        ("wlo1", Role.OTHER, "ordinary device, not a VPN"),
        ("sit0", Role.OTHER, "sit device, not a VPN"),  # 6in4 tunnel is not encrypted
        ("wg7", Role.VPN, "name matches 'wg*'"),  # not in the link list: falls to the name
        ("pvpnksintrf1", Role.BLOCKER, "leak guard"),
    ],
)
def test_classify(ifname: str, role: Role, why: str) -> None:
    info = classifier().classify(ifname)
    assert info.role is role
    assert why in info.why


def test_any_dummy_device_blocks() -> None:
    links = ok(json.dumps([{"ifname": "killsw", "linkinfo": {"info_kind": "dummy"}}]))
    info = classifier(links, leak_guard_interfaces=()).classify("killsw")
    assert info.role is Role.BLOCKER
    assert "dummy device" in info.why


@pytest.mark.parametrize(
    "links",
    [
        CommandResult(1, "", "boom"),
        ok("nope"),
        ok("{}"),
        FileNotFoundError("ip"),
        subprocess.TimeoutExpired(["ip"], 1.0),
    ],
)
def test_classifier_falls_back_to_names(links: CommandResult | BaseException) -> None:
    c = classifier(links)
    assert c.classify("proton0").role is Role.VPN  # by name
    other = c.classify("wlo1")
    assert other.role is Role.OTHER
    assert "cannot read link kinds" in other.why
    assert c.last_error is not None


def test_classifier_skips_malformed_links() -> None:
    links = ok(json.dumps([{"ifname": "a", "linkinfo": "x"}, {"no": "name"}, 3, {"ifname": "b"}]))
    c = classifier(links)
    assert c.refresh() == {"a": "", "b": ""}


def test_classifier_caches_and_reloads() -> None:
    runner = FakeRunner(ok("[]"), ok("[]"))
    c = LinkClassifier(("wg*",), (), runner=runner)
    c.classify("proton0")
    c.classify("proton0")
    assert runner.calls.count(["ip", "-d", "-j", "link", "show"]) == 1
    c.classify("newdev")  # unknown name → reload once
    assert runner.calls.count(["ip", "-d", "-j", "link", "show"]) == 2
    c.invalidate()
    c.classify("proton0")
    assert runner.calls.count(["ip", "-d", "-j", "link", "show"]) == 3


# ---------------------------------------------------------------------------------------------
# Combination (spec R3) and consistency with the engine (S6)
# ---------------------------------------------------------------------------------------------

_KINDS: dict[str, tuple[RouteKind, str | None, bool]] = {
    "vpn": (RouteKind.ROUTED, "proton0", True),
    "plain": (RouteKind.ROUTED, "wlo1", False),
    "blocked": (RouteKind.BLOCKED, "ipv6leakintrf0", False),
    "unreachable": (RouteKind.UNREACHABLE, None, False),
    "error": (RouteKind.ERROR, None, False),
}


@pytest.mark.parametrize(("k4", "k6"), list(itertools.product(_KINDS, repeat=2)))
def test_combine_table(k4: str, k6: str) -> None:
    results = []
    for fam, key in ((4, k4), (6, k6)):
        kind, dev, is_vpn = _KINDS[key]
        results.append(FamilyResult(FamilyRoute(fam, V4, dev, kind, is_vpn), key))  # type: ignore[arg-type]
    reading = combine(results, 1.0)
    keys = {k4, k6}
    if "plain" in keys:
        expected = VpnState.NO_VPN
        assert "via wlo1" in reading.reason
    elif "error" in keys:
        expected = VpnState.UNKNOWN
    elif "vpn" in keys:
        expected = VpnState.VPN
    else:
        expected = VpnState.NO_VPN
        assert "kill switch or no network" in reading.reason
    assert reading.state is expected
    # S6: VPN exactly when the engine's own route check would allow blue.
    assert (reading_problem(reading, 1.0, 10.0) is None) == (expected is VpnState.VPN)


def test_combine_nothing_is_unknown() -> None:
    reading = combine([], 3.0)
    assert reading.state is VpnState.UNKNOWN
    assert reading.routes == ()


def test_probe_crash_is_unknown() -> None:
    runner = FakeRunner(RuntimeError("bug"), route("proton0", V6))
    reading = make_probe(runner).read()
    assert reading.state is VpnState.UNKNOWN
    assert reading.reason == "probe crashed: RuntimeError: bug"
    assert reading_problem(reading, 5.0, 10.0) is not None


def test_timestamp_is_taken_before_probing() -> None:
    times = iter([1.0, 99.0])
    probe = RouteProbe(
        VpnConfig(),
        ProbesConfig(),
        runner=FakeRunner(route("proton0"), route("proton0")),
        clock=lambda: next(times),
    )
    assert probe.read().timestamp == 1.0


def test_read_vpn_state_uses_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append({"argv": argv, **kwargs})
        if argv[1] == "-d":
            return subprocess.CompletedProcess(argv, 0, LINKS, "")
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([{"dst": "x", "dev": "proton0"}]), ""
        )

    monkeypatch.setattr(vpn.subprocess, "run", fake_run)
    reading = vpn.read_vpn_state(Config())
    assert reading.state is VpnState.VPN
    first = seen[0]
    assert first["argv"] == ["ip", "-4", "-j", "route", "get", "1.1.1.1"]
    assert first["env"]["LC_ALL"] == "C"
    assert first["timeout"] == Config().vpn.probe_timeout_s
    assert first["check"] is False
    assert "shell" not in first


def test_long_messages_are_shortened() -> None:
    result = family(CommandResult(2, "", "x" * 500))
    assert len(result.detail) < 260
    assert result.detail.endswith("…")


# ---------------------------------------------------------------------------------------------
# S2: no network code
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["vpn.py", "mainloop.py"])
def test_no_network_imports(module: str) -> None:
    tree = ast.parse((SRC / module).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"socket", "ssl", "http", "urllib", "requests", "asyncio", "selectors"}
