"""install.sh / uninstall.sh against a temporary HOME with systemctl and hyprctl stubbed."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "scripts" / "install.sh"
UNINSTALL = REPO / "scripts" / "uninstall.sh"

BINDINGS = """-- user bindings
o.bind("SUPER + ALT + V", "Prometheus: cycle verbosity", "prometheus verbosity cycle")
"""

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


class Home:
    """A throw-away HOME with stub ``systemctl`` and ``hyprctl`` that record their calls."""

    def __init__(self, root: Path, binds: list[dict[str, object]] | None = None) -> None:
        self.root = root
        self.home = root / "home"
        self.stubs = root / "stubs"
        self.calls = root / "calls.log"
        self.home.mkdir()
        self.stubs.mkdir()
        (self.home / ".config" / "hypr").mkdir(parents=True)
        self.bindings.write_text(BINDINGS)
        self._stub("systemctl", 'echo "systemctl $*" >> "$CALLS"')
        self._stub(
            "hyprctl",
            'echo "hyprctl $*" >> "$CALLS"\n[ "$1" = binds ] && cat "$BINDS_JSON"\nexit 0',
        )
        self.binds_json = root / "binds.json"
        self.binds_json.write_text(json.dumps(binds if binds is not None else []))

    @property
    def bindings(self) -> Path:
        return self.home / ".config" / "hypr" / "bindings.lua"

    @property
    def backup(self) -> Path:
        return self.bindings.with_name("bindings.lua.bak.vpn-monitor")

    @property
    def link(self) -> Path:
        return self.home / ".local" / "bin" / "vpn-monitor"

    @property
    def unit(self) -> Path:
        return self.home / ".config" / "systemd" / "user" / "vpn-monitor.service"

    def _stub(self, name: str, body: str) -> None:
        path = self.stubs / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.stubs}:{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "BINDS_JSON": str(self.binds_json),
            "VPM_SKIP_CHECKS": "1",
        }
        return subprocess.run(
            ["bash", str(script), *args], env=env, capture_output=True, text=True, check=False
        )

    def called(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []


@pytest.fixture
def home(tmp_path: Path) -> Home:
    return Home(tmp_path)


def test_install_creates_everything(home: Home) -> None:
    result = home.run(INSTALL)
    assert result.returncode == 0, result.stderr
    assert home.link.is_symlink()
    assert home.link.resolve() == REPO / "scripts" / "vpn-monitor"
    assert home.unit.read_text() == (REPO / "packaging/systemd/vpn-monitor.service").read_text()
    text = home.bindings.read_text()
    assert text.startswith(BINDINGS)
    assert (
        'o.bind("SUPER + ALT + SHIFT + V", "VPN Monitor: pause/resume", "vpn-monitor toggle")'
        in text
    )
    assert home.backup.read_text() == BINDINGS
    calls = home.called()
    assert "systemctl --user daemon-reload" in calls
    assert "systemctl --user enable vpn-monitor.service" in calls
    assert "systemctl --user restart vpn-monitor.service" in calls
    assert "hyprctl reload" in calls


def test_install_twice_is_idempotent(home: Home) -> None:
    home.run(INSTALL)
    once = home.bindings.read_text()
    assert home.run(INSTALL).returncode == 0
    assert home.bindings.read_text() == once
    assert once.count("-- >>> vpn-monitor") == 1
    assert home.backup.read_text() == BINDINGS  # the backup is the pre-install original


def test_uninstall_restores_the_original_exactly(home: Home) -> None:
    home.run(INSTALL)
    result = home.run(UNINSTALL)
    assert result.returncode == 0, result.stderr
    assert not home.link.exists()
    assert not home.link.is_symlink()
    assert not home.unit.exists()
    assert home.bindings.read_text() == BINDINGS
    assert home.backup.exists()  # left on purpose
    assert "identical to the backup" in result.stdout
    assert "systemctl --user disable --now vpn-monitor.service" in home.called()


def test_uninstall_is_idempotent_and_safe_on_a_clean_home(home: Home) -> None:
    assert home.run(UNINSTALL).returncode == 0
    assert home.run(UNINSTALL).returncode == 0
    assert home.bindings.read_text() == BINDINGS


def test_uninstall_keeps_the_users_own_later_edits(home: Home) -> None:
    home.run(INSTALL)
    with home.bindings.open("a") as handle:
        handle.write('o.bind("SUPER + X", "mine", "true")\n')
    result = home.run(UNINSTALL)
    assert 'o.bind("SUPER + X", "mine", "true")' in home.bindings.read_text()
    assert "-- >>> vpn-monitor" not in home.bindings.read_text()
    assert "differs from the backup" in result.stdout


def test_install_refuses_a_taken_key_and_changes_nothing(tmp_path: Path) -> None:
    taken = [{"modmask": 73, "key": "V", "description": "Something else"}]
    home = Home(tmp_path, taken)
    result = home.run(INSTALL)
    assert result.returncode == 1
    assert "already bound (Something else)" in result.stderr
    assert not home.link.exists()
    assert not home.unit.exists()
    assert home.bindings.read_text() == BINDINGS
    assert not home.backup.exists()


def test_our_own_binding_does_not_count_as_taken(tmp_path: Path) -> None:
    ours = [{"modmask": 73, "key": "v", "description": "VPN Monitor: pause/resume"}]
    home = Home(tmp_path, ours)
    assert home.run(INSTALL).returncode == 0


def test_other_modifiers_on_the_same_key_are_fine(tmp_path: Path) -> None:
    others = [{"modmask": 72, "key": "V", "description": "Prometheus: cycle verbosity"}]
    assert Home(tmp_path, others).run(INSTALL).returncode == 0


def test_unparsable_hyprctl_output_does_not_block(home: Home) -> None:
    home.binds_json.write_text("not json")
    assert home.run(INSTALL).returncode == 0


def test_no_keybinding_option(home: Home) -> None:
    assert home.run(INSTALL, "--no-keybinding").returncode == 0
    assert home.bindings.read_text() == BINDINGS
    assert not home.backup.exists()
    assert "hyprctl reload" not in home.called()
    assert home.unit.exists()


def test_no_start_option(home: Home) -> None:
    assert home.run(INSTALL, "--no-start").returncode == 0
    calls = home.called()
    assert "systemctl --user restart vpn-monitor.service" not in calls
    assert "systemctl --user enable vpn-monitor.service" in calls


def test_missing_bindings_file_is_an_error_unless_skipped(home: Home) -> None:
    home.bindings.unlink()
    result = home.run(INSTALL)
    assert result.returncode == 1
    assert "not found" in result.stderr
    assert home.run(INSTALL, "--no-keybinding").returncode == 0


def test_a_foreign_file_at_the_command_path_is_not_overwritten(home: Home) -> None:
    home.link.parent.mkdir(parents=True)
    home.link.write_text("#!/bin/sh\necho mine\n")
    result = home.run(INSTALL)
    assert result.returncode == 1
    assert "not a symlink" in result.stderr
    assert home.link.read_text().endswith("echo mine\n")
    home.run(UNINSTALL)
    assert home.link.exists()  # uninstall does not delete it either


def test_unknown_option_and_help(home: Home) -> None:
    assert home.run(INSTALL, "--bogus").returncode == 2
    helped = home.run(INSTALL, "--help")
    assert helped.returncode == 0
    assert "Install VPN Monitor" in helped.stdout


def test_a_failed_reload_is_reported_but_not_fatal(home: Home) -> None:
    home._stub(
        "hyprctl",
        'echo "hyprctl $*" >> "$CALLS"\n'
        '[ "$1" = binds ] && cat "$BINDS_JSON"\n'
        '[ "$1" = reload ] && exit 1\nexit 0',
    )
    result = home.run(INSTALL)
    assert result.returncode == 0
    assert "hyprctl reload failed" in result.stdout


def test_the_wrapper_runs_the_package(tmp_path: Path) -> None:
    result = subprocess.run(
        [str(REPO / "scripts" / "vpn-monitor"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
    )
    if result.returncode != 0 and "No such file" in result.stderr:
        pytest.skip("no /usr/bin/python3")
    assert result.returncode == 0
    assert result.stdout.startswith("vpn-monitor ")


def test_the_unit_file_has_the_required_shape() -> None:
    text = (REPO / "packaging/systemd/vpn-monitor.service").read_text()
    for line in (
        "PartOf=graphical-session.target",
        "After=graphical-session.target",
        "Restart=on-failure",
        "RestartSec=2",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "PrivateTmp=yes",
        "RestrictAddressFamilies=AF_UNIX AF_NETLINK",
        "WantedBy=graphical-session.target",
        "Environment=GSK_RENDERER=cairo",
    ):
        assert line in text
    assert "AF_INET" not in text.replace("AF_NETLINK", "")  # S2: no network sockets at all
