import pytest

from vpn_monitor import __version__
from vpn_monitor.cli import main


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
