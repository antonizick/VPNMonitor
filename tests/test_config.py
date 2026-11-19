import dataclasses
import tomllib
from pathlib import Path

import pytest

from vpn_monitor.config import (
    _SCHEMA,
    Config,
    ConfigError,
    default_config_path,
    load_config,
    parse_config,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "config" / "config.example.toml"


def test_example_file_equals_defaults() -> None:
    loaded = load_config(EXAMPLE)
    assert loaded == Config()
    assert loaded.warnings == ()
    assert loaded.source == EXAMPLE


def test_example_file_documents_every_key() -> None:
    data = tomllib.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert set(data) == set(_SCHEMA)
    for section, (cls, _) in _SCHEMA.items():
        assert set(data[section]) == {f.name for f in dataclasses.fields(cls)}, section


def test_schema_covers_every_field() -> None:
    assert set(_SCHEMA) == {f.name for f in dataclasses.fields(Config)} - {"warnings", "source"}


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml")
    assert config == Config()
    assert config.source is None


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("")
    assert load_config(path) == Config()


def test_partial_override_keeps_other_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[indicator]\nshow_on_fullscreen = false\nblue_confirm_ms = 500\n"
        '[appearance]\nred = "#ff0000"\n'
    )
    config = load_config(path)
    assert config.indicator.show_on_fullscreen is False
    assert config.indicator.blue_confirm_ms == 500
    assert config.appearance.red == "#ff0000"
    assert config.appearance.blue == Config().appearance.blue
    assert config.vpn == Config().vpn


def test_int_accepted_for_seconds() -> None:
    config = parse_config({"vpn": {"max_reading_age_s": 20, "recheck_interval_s": 2}})
    assert config.vpn.max_reading_age_s == 20.0
    assert isinstance(config.vpn.max_reading_age_s, float)


def test_lists_become_tuples() -> None:
    config = parse_config({"browsers": {"classes": ["a"], "patterns": []}})
    assert config.browsers.classes == ("a",)
    assert config.browsers.patterns == ()


def test_unknown_keys_and_sections_warn() -> None:
    config = parse_config({"vpn": {"bogus": 1}, "extra": {"x": 1}})
    assert config.warnings == ("unknown key vpn.bogus ignored", "unknown section [extra] ignored")
    assert config == Config()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"vpn": 3}, "vpn: expected a table"),
        ({"browsers": {"classes": "brave"}}, "browsers.classes: expected a list"),
        ({"browsers": {"classes": [1]}}, r"browsers.classes\[0\]: expected a non-empty string"),
        ({"browsers": {"classes": [""]}}, r"browsers.classes\[0\]"),
        ({"browsers": {"patterns": ["("]}}, r"browsers.patterns\[0\]: invalid regular expression"),
        ({"probes": {"ipv4": "2606:4700::1"}}, "probes.ipv4: .* is not an IPv4 address"),
        ({"probes": {"ipv6": "1.1.1.1"}}, "probes.ipv6: .* is not an IPv6 address"),
        ({"probes": {"ipv4": "example.com"}}, "probes.ipv4: .* is not an IP address"),
        ({"probes": {"ipv4": 1}}, "probes.ipv4: expected an IPv4 address"),
        ({"vpn": {"interface_patterns": []}}, "vpn.interface_patterns: must not be empty"),
        ({"vpn": {"interface_patterns": ["a b"]}}, r"vpn.interface_patterns\[0\]: .* not an"),
        ({"vpn": {"leak_guard_interfaces": ["x/y"]}}, r"vpn.leak_guard_interfaces\[0\]"),
        ({"vpn": {"max_reading_age_s": "10"}}, "vpn.max_reading_age_s: expected a number"),
        ({"vpn": {"max_reading_age_s": True}}, "vpn.max_reading_age_s: expected a number"),
        ({"vpn": {"max_reading_age_s": 0}}, "vpn.max_reading_age_s: must be greater than 0"),
        ({"vpn": {"max_reading_age_s": -1}}, "vpn.max_reading_age_s: must be greater"),
        ({"vpn": {"max_reading_age_s": float("nan")}}, "vpn.max_reading_age_s: must be"),
        ({"vpn": {"max_reading_age_s": float("inf")}}, "vpn.max_reading_age_s: must be"),
        ({"vpn": {"probe_timeout_s": 61}}, "vpn.probe_timeout_s: must be"),
        ({"vpn": {"recheck_interval_s": 10}}, "vpn.recheck_interval_s: must be shorter than"),
        ({"vpn": {"probe_timeout_s": 5}}, "vpn.probe_timeout_s: must be shorter than"),
        ({"indicator": {"show_on_fullscreen": "yes"}}, "indicator.show_on_fullscreen: expected"),
        ({"indicator": {"show_on_fullscreen": 1}}, "indicator.show_on_fullscreen: expected"),
        ({"indicator": {"blue_confirm_ms": 1.5}}, "indicator.blue_confirm_ms: expected an int"),
        ({"indicator": {"blue_confirm_ms": True}}, "indicator.blue_confirm_ms: expected an int"),
        ({"indicator": {"blue_confirm_ms": -1}}, "indicator.blue_confirm_ms: must be between"),
        ({"indicator": {"blue_confirm_ms": 10_001}}, "indicator.blue_confirm_ms: must be between"),
        ({"indicator": {"red_confirm_ms": 100}}, "indicator.red_confirm_ms: must be 0"),
        ({"indicator": {"red_confirm_ms": False}}, "indicator.red_confirm_ms: must be 0"),
        ({"appearance": {"red": "red"}}, "appearance.red: expected a colour"),
        ({"appearance": {"blue": "#12345"}}, "appearance.blue: expected a colour"),
        ({"appearance": {"blue": 0x0A84FF}}, "appearance.blue: expected a colour"),
        ({"appearance": {"thickness": 0}}, "appearance.thickness: must be between 1"),
        ({"appearance": {"glow": 129}}, "appearance.glow: must be between"),
        ({"appearance": {"fade_ms": 2001}}, "appearance.fade_ms: must be between"),
        ({"pause": {"auto_resume_minutes": -5}}, "pause.auto_resume_minutes: must be between"),
        ({"log": {"max_bytes": 10}}, "log.max_bytes: must be between"),
        ({"log": {"backup_count": 0}}, "log.backup_count: must be between"),
    ],
)
def test_invalid_values_raise_naming_the_key(data: dict[str, object], message: str) -> None:
    with pytest.raises(ConfigError, match=f"^{message}"):
        parse_config(data)


def test_valid_edge_values() -> None:
    config = parse_config(
        {
            "appearance": {"red": "#FF3B30CC", "glow": 0},
            "vpn": {"leak_guard_interfaces": [], "interface_patterns": ["wg[0-9]"]},
            "probes": {"ipv6": "::1"},
        }
    )
    assert config.appearance.red == "#FF3B30CC"
    assert config.vpn.leak_guard_interfaces == ()


def test_invalid_toml_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[vpn\n")
    with pytest.raises(ConfigError, match="invalid TOML"):
        load_config(path)


def test_unreadable_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path)  # a directory


def test_default_config_path_honours_xdg(tmp_path: Path) -> None:
    assert default_config_path({"XDG_CONFIG_HOME": str(tmp_path)}) == (
        tmp_path / "vpn-monitor" / "config.toml"
    )


def test_default_config_path_falls_back_to_home() -> None:
    expected = Path.home() / ".config" / "vpn-monitor" / "config.toml"
    assert default_config_path({}) == expected
    assert default_config_path({"XDG_CONFIG_HOME": "relative/dir"}) == expected


def test_load_config_without_path_uses_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "vpn-monitor").mkdir()
    (tmp_path / "vpn-monitor" / "config.toml").write_text("[pause]\nauto_resume_minutes = 30\n")
    assert load_config().pause.auto_resume_minutes == 30
