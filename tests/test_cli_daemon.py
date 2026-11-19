"""CLI: run, pause/resume/toggle, status and log (the daemon itself is faked)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor import cli, control
from vpn_monitor.cli import format_status, main
from vpn_monitor.control import ControlError, DaemonNotRunning

STATUS: dict[str, Any] = {
    "version": "0.1.0",
    "pid": 123,
    "uptime_s": 3725.0,
    "paused": False,
    "pause_resumes_in_s": None,
    "indicator": "blue",
    "monitor": "HDMI-A-1",
    "reason": "browser focused, routed through a VPN",
    "focus": {
        "class": "brave-browser",
        "match": "class:brave-browser",
        "monitor": "HDMI-A-1",
        "fullscreen": False,
    },
    "reading": {
        "state": "vpn",
        "reason": "all via VPN",
        "age_s": 1.2,
        "routes": [
            {
                "family": 4,
                "destination": "192.0.2.1",
                "interface": "proton0",
                "kind": "routed",
                "vpn": True,
            },
            {
                "family": 6,
                "destination": "2001:db8::1",
                "interface": None,
                "kind": "unreachable",
                "vpn": False,
            },
        ],
    },
    "config": None,
    "focus_watcher": {"connected": True, "reconnects": 0},
    "vpn_watcher": {"watcher_up": True, "last_trigger": "route-change"},
}


class FakeDaemon:
    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self.reply = reply
        self.commands: list[str] = []

    def __call__(self, command: str) -> dict[str, Any]:
        self.commands.append(command)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(cli, "notify", sent.append)
    return sent


def talk(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any] | Exception) -> FakeDaemon:
    daemon = FakeDaemon(reply)
    monkeypatch.setattr(control, "send_command", daemon)
    return daemon


@pytest.mark.parametrize(
    ("command", "paused", "line", "note"),
    [
        ("pause", True, "vpn-monitor paused", "VPN Monitor paused"),
        ("resume", False, "vpn-monitor resumed", "VPN Monitor resumed"),
        ("toggle", True, "vpn-monitor paused", "VPN Monitor paused"),
        ("toggle", False, "vpn-monitor resumed", "VPN Monitor resumed"),
    ],
)
def test_pause_resume_toggle_notify(
    monkeypatch: pytest.MonkeyPatch,
    notes: list[str],
    capsys: pytest.CaptureFixture[str],
    command: str,
    paused: bool,
    line: str,
    note: str,
) -> None:
    daemon = talk(monkeypatch, {"ok": True, "paused": paused})
    assert main([command]) == 0
    assert daemon.commands == [command]
    assert capsys.readouterr().out.strip() == line
    assert notes == [note]


def test_not_running_exits_3_without_a_notification(
    monkeypatch: pytest.MonkeyPatch, notes: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    talk(monkeypatch, DaemonNotRunning("vpn-monitor is not running"))
    assert main(["pause"]) == 3
    assert "not running" in capsys.readouterr().err
    assert notes == []


def test_control_errors_and_refusals_exit_1(
    monkeypatch: pytest.MonkeyPatch, notes: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    talk(monkeypatch, ControlError("the daemon did not answer in time"))
    assert main(["resume"]) == 1
    assert "did not answer" in capsys.readouterr().err
    talk(monkeypatch, {"ok": False, "error": "command failed"})
    assert main(["toggle"]) == 1
    assert "refused" in capsys.readouterr().err
    assert notes == []


def test_status_human_and_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    talk(monkeypatch, {"ok": True, **STATUS})
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "BLUE on HDMI-A-1" in out
    assert "brave-browser" in out
    assert "IPv4  routed" in out
    assert main(["status", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["indicator"] == "blue"
    assert "ok" not in parsed


def test_status_when_not_running(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    talk(monkeypatch, DaemonNotRunning("x"))
    assert main(["status"]) == 3


def test_format_status_variants() -> None:
    paused = {
        **STATUS,
        "paused": True,
        "indicator": "hidden",
        "monitor": "",
        "reading": None,
        "focus": {"class": "", "match": "none", "monitor": "", "fullscreen": False},
        "focus_watcher": {},
        "vpn_watcher": {},
        "uptime_s": 42.0,
    }
    text = format_status(paused)
    assert "PAUSED until resumed" in text
    assert "no window focused" in text
    assert "no reading yet" in text
    assert "up 0m 42s" in text
    timed = {**paused, "pause_resumes_in_s": 90.0, "config": "/x/config.toml"}
    assert "resumes in 1m 30s" in format_status(timed)
    assert "/x/config.toml" in format_status(timed)
    other = {
        **STATUS,
        "focus": {"class": "foot", "match": "none", "monitor": "", "fullscreen": False},
    }
    assert "foot  not a browser" in format_status(other)
    assert "up 1h 02m" in format_status(STATUS)


def test_run_hands_over_to_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    import vpn_monitor.daemon as daemon

    seen: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> int:
        seen.update(kwargs)
        return 7

    monkeypatch.setattr(daemon, "run", fake_run)
    assert main(["run", "--foreground", "--config", "/tmp/c.toml"]) == 7
    assert seen["foreground"] is True
    assert seen["argv"] == ["run", "--foreground", "--config", "/tmp/c.toml"]
    assert seen["config_path"] == Path("/tmp/c.toml")


# -- log ------------------------------------------------------------------------------------


def test_log_prints_the_tail_of_either_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    state = tmp_path / "vpn-monitor"
    state.mkdir()
    (state / "vpn-monitor.log").write_text("".join(f"line {i}\n" for i in range(500)))
    (state / "events.jsonl").write_text('{"event":"x"}\n')
    assert main(["log"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "line 300"
    assert lines[-1] == "line 499"
    assert len(lines) == 200
    assert main(["log", "--events"]) == 0
    assert capsys.readouterr().out == '{"event":"x"}\n'


def test_log_without_a_log_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert main(["log"]) == 1
    assert "no log yet" in capsys.readouterr().err


# -- notify ---------------------------------------------------------------------------------


def test_notify_calls_notify_send(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> None:
        calls.append(argv)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cli.notify("VPN Monitor paused")
    assert calls[0][0] == "notify-send"
    assert calls[0][-1] == "VPN Monitor paused"


@pytest.mark.parametrize(
    "error", [FileNotFoundError("notify-send"), subprocess.TimeoutExpired("x", 5)]
)
def test_notify_never_raises(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise error

    monkeypatch.setattr(subprocess, "run", broken)
    cli.notify("anything")
