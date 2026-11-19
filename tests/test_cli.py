import json
from pathlib import Path

import pytest

from vpn_monitor import __version__, vpn
from vpn_monitor.cli import main
from vpn_monitor.model import FamilyRoute, RouteKind, VpnReading, VpnState


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["run", "--foreground"],
        ["pause"],
        ["resume"],
        ["toggle"],
        ["status"],
        ["status", "--json"],
        ["log"],
        ["log", "-f", "--events"],
    ],
)
def test_subcommands_are_stubs(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(argv) == 2
    assert "not implemented yet" in capsys.readouterr().err


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage:" in capsys.readouterr().out


def _reading(state: VpnState) -> VpnReading:
    route = FamilyRoute(4, "192.0.2.1", "proton0", RouteKind.ROUTED, state is VpnState.VPN)
    return VpnReading(state, (route,), f"because {state.value}", 1.0)


@pytest.mark.parametrize(
    ("state", "code", "headline"),
    [(VpnState.VPN, 0, "VPN:"), (VpnState.NO_VPN, 1, "NO VPN:"), (VpnState.UNKNOWN, 3, "UNKNOWN:")],
)
def test_probe_prints_reading_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    state: VpnState,
    code: int,
    headline: str,
) -> None:
    monkeypatch.setattr(vpn, "read_vpn_state", lambda config: _reading(state))
    assert main(["probe", "--config", str(tmp_path / "none.toml")]) == code
    out = capsys.readouterr().out
    assert out.startswith(headline)
    assert "IPv4  routed      proton0" in out
    assert f"why: because {state.value}" in out


def test_probe_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(vpn, "read_vpn_state", lambda config: _reading(VpnState.VPN))
    assert main(["probe", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "vpn"
    assert data["routes"] == [
        {
            "family": 4,
            "destination": "192.0.2.1",
            "interface": "proton0",
            "kind": "routed",
            "vpn": True,
        }
    ]


def test_probe_config_error(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("[vpn]\nrecheck_interval_s = -1\n")
    assert main(["probe", "--config", str(bad)]) == 2
    assert "config error: vpn.recheck_interval_s" in capsys.readouterr().err


def test_focus_row_and_format() -> None:
    from vpn_monitor.browsers import BrowserMatcher
    from vpn_monitor.cli import focus_row, format_focus
    from vpn_monitor.model import FocusEvent

    matcher = BrowserMatcher()
    row = focus_row(FocusEvent("brave-browser", "0x1", "HDMI-A-1", fullscreen=True), matcher)
    assert row["browser"] is True
    assert row["rule"] == "exact:brave-browser"
    assert (
        format_focus(row)
        == "brave-browser  BROWSER (exact:brave-browser)  monitor=HDMI-A-1  fullscreen"
    )
    other = focus_row(FocusEvent("foot", "0x2", ""), matcher)
    assert format_focus(other) == "foot  not a browser  monitor=?"
    assert format_focus(focus_row(FocusEvent("", "", ""), matcher)) == "no window focused"


@pytest.mark.parametrize(("cls", "code"), [("brave-maps.google.com__-Default", 0), ("foot", 1)])
def test_focus_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    cls: str,
    code: int,
) -> None:
    from vpn_monitor import focus
    from vpn_monitor.model import FocusEvent

    monkeypatch.setattr(focus, "locate_sockets", lambda env=None: None)
    monkeypatch.setattr(
        focus.HyprlandClient, "active_focus", lambda self: FocusEvent(cls, "0x1", "eDP-1")
    )
    assert main(["focus", "--json", "--config", str(tmp_path / "none.toml")]) == code
    row = json.loads(capsys.readouterr().out)
    assert row["class"] == cls
    assert row["browser"] is (code == 0)


def test_focus_without_hyprland(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    assert main(["focus"]) == 2
    assert "Hyprland not running" in capsys.readouterr().err


def test_focus_query_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from vpn_monitor import focus

    monkeypatch.setattr(focus, "locate_sockets", lambda env=None: None)

    def boom(self: object) -> None:
        raise OSError("refused")

    monkeypatch.setattr(focus.HyprlandClient, "active_focus", boom)
    assert main(["focus"]) == 2
    assert "cannot read the focused window" in capsys.readouterr().err


def test_focus_config_error(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text("[vpn]\nrecheck_interval_s = -1\n")
    assert main(["focus", "--config", str(bad)]) == 2
    assert "config error" in capsys.readouterr().err
