"""TOML configuration loading and strict validation. Every default lives here, in code.

The file is optional (``$XDG_CONFIG_HOME/vpn-monitor/config.toml``, default
``~/.config/vpn-monitor/config.toml``) and every key in it is optional. Validation is strict:

* an unknown section or key is **ignored with a warning** (``Config.warnings``), so a typo never
  stops the daemon but is visible in the log;
* a wrong type, an out-of-range value, an invalid regex, colour or address **raises**
  :class:`ConfigError`, whose message starts with the dotted key (``vpn.max_reading_age_s: …``).

``config/config.example.toml`` documents every key and holds exactly these defaults (a test checks
that). Pure apart from reading the one file: no clock, sockets or subprocesses.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from vpn_monitor.browsers import DEFAULT_CLASSES, DEFAULT_PATTERNS


class ConfigError(ValueError):
    """The configuration is invalid. The message names the offending key."""


# ---------------------------------------------------------------------------------------------
# Typed configuration
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrowsersConfig:
    """``[browsers]``: which window classes count as a browser (ADR-0004)."""

    classes: tuple[str, ...] = DEFAULT_CLASSES
    patterns: tuple[str, ...] = DEFAULT_PATTERNS


@dataclass(frozen=True, slots=True)
class ProbesConfig:
    """``[probes]``: destinations whose *route* is looked up. No packet is ever sent (S2)."""

    ipv4: str = "1.1.1.1"
    ipv6: str = "2606:4700:4700::1111"


@dataclass(frozen=True, slots=True)
class VpnConfig:
    """``[vpn]``: interface classification and timing (spec R3, R4, R5)."""

    interface_patterns: tuple[str, ...] = (
        "proton*",
        "wg*",
        "tun*",
        "tailscale*",
        "nordlynx",
        "mullvad*",
    )
    leak_guard_interfaces: tuple[str, ...] = ("ipv6leakintrf*", "pvpnksintrf*", "pvpnrouteintrf*")
    """Kill-switch / leak-guard names (ProtonVPN's). Any kernel ``dummy`` device counts too."""
    recheck_interval_s: float = 5.0
    max_reading_age_s: float = 10.0
    probe_timeout_s: float = 1.0


@dataclass(frozen=True, slots=True)
class IndicatorConfig:
    """``[indicator]``: engine behaviour (ADR-0013)."""

    show_on_fullscreen: bool = True
    blue_confirm_ms: int = 0
    red_confirm_ms: int = 0
    """Must be 0: red is never delayed (S6, ADR-0013). Kept so the rule is explicit."""


@dataclass(frozen=True, slots=True)
class AppearanceConfig:
    """``[appearance]``: the bar's look (owner question 2, tuned in Phase 06)."""

    red: str = "#FF3B30"
    blue: str = "#0A84FF"
    thickness: int = 3
    glow: int = 12
    fade_ms: int = 150


@dataclass(frozen=True, slots=True)
class PauseConfig:
    """``[pause]``: how long a pause lasts (owner question 4)."""

    auto_resume_minutes: int = 0
    """0 = until resumed or the next login."""


@dataclass(frozen=True, slots=True)
class LogConfig:
    """``[log]``: rotation of both log files (spec R11)."""

    max_bytes: int = 1_000_000
    backup_count: int = 3


@dataclass(frozen=True, slots=True)
class Config:
    """The whole validated configuration."""

    browsers: BrowsersConfig = field(default_factory=BrowsersConfig)
    probes: ProbesConfig = field(default_factory=ProbesConfig)
    vpn: VpnConfig = field(default_factory=VpnConfig)
    indicator: IndicatorConfig = field(default_factory=IndicatorConfig)
    appearance: AppearanceConfig = field(default_factory=AppearanceConfig)
    pause: PauseConfig = field(default_factory=PauseConfig)
    log: LogConfig = field(default_factory=LogConfig)
    warnings: tuple[str, ...] = field(default=(), compare=False)
    """Non-fatal problems found while loading (unknown keys). The daemon logs them."""
    source: Path | None = field(default=None, compare=False)
    """The file that was loaded, or ``None`` for built-in defaults."""


# ---------------------------------------------------------------------------------------------
# Validators: each takes (dotted key, raw value) and returns the typed value or raises
# ---------------------------------------------------------------------------------------------

Validator = Callable[[str, object], object]


def _type_name(value: object) -> str:
    return type(value).__name__


def _boolean(key: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{key}: expected true or false, got {_type_name(value)}")
    return value


def _integer(lo: int, hi: int) -> Validator:
    def check(key: str, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{key}: expected an integer, got {_type_name(value)}")
        if not lo <= value <= hi:
            raise ConfigError(f"{key}: must be between {lo} and {hi}, got {value}")
        return value

    return check


def _seconds(lo: float, hi: float) -> Validator:
    """A positive number of seconds; ``lo`` is exclusive."""

    def check(key: str, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{key}: expected a number of seconds, got {_type_name(value)}")
        number = float(value)
        if not math.isfinite(number) or not lo < number <= hi:
            raise ConfigError(f"{key}: must be greater than {lo:g} and at most {hi:g}, got {value}")
        return number

    return check


def _string_list(item: Callable[[str, str], None], *, allow_empty: bool) -> Validator:
    def check(key: str, value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise ConfigError(f"{key}: expected a list of strings, got {_type_name(value)}")
        out: list[str] = []
        for index, entry in enumerate(value):
            if not isinstance(entry, str) or not entry:
                raise ConfigError(f"{key}[{index}]: expected a non-empty string")
            item(f"{key}[{index}]", entry)
            out.append(entry)
        if not out and not allow_empty:
            raise ConfigError(f"{key}: must not be empty")
        return tuple(out)

    return check


def _any_text(key: str, entry: str) -> None:
    """Any non-empty string is fine."""


def _regex(key: str, entry: str) -> None:
    try:
        re.compile(entry)
    except re.error as exc:
        raise ConfigError(f"{key}: invalid regular expression {entry!r}: {exc}") from None


_IFNAME_GLOB = re.compile(r"[A-Za-z0-9_.:*?\[\]-]{1,32}")


def _interface_glob(key: str, entry: str) -> None:
    if not _IFNAME_GLOB.fullmatch(entry):
        raise ConfigError(f"{key}: {entry!r} is not an interface name or glob")


def _address(version: int) -> Validator:
    def check(key: str, value: object) -> str:
        if not isinstance(value, str):
            raise ConfigError(f"{key}: expected an IPv{version} address, got {_type_name(value)}")
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise ConfigError(f"{key}: {value!r} is not an IP address") from None
        if address.version != version:
            raise ConfigError(f"{key}: {value!r} is not an IPv{version} address")
        return value

    return check


_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?")


def _colour(key: str, value: object) -> str:
    if not isinstance(value, str) or not _COLOUR.fullmatch(value):
        raise ConfigError(f'{key}: expected a colour like "#RRGGBB" or "#RRGGBBAA"')
    return value


def _must_be_zero(key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ConfigError(
            f"{key}: must be 0; red is never delayed, since a delay could keep a false blue on "
            "screen (spec S6, ADR-0013)"
        )
    return 0


_SCHEMA: dict[str, tuple[type[Any], dict[str, Validator]]] = {
    "browsers": (
        BrowsersConfig,
        {
            "classes": _string_list(_any_text, allow_empty=True),
            "patterns": _string_list(_regex, allow_empty=True),
        },
    ),
    "probes": (ProbesConfig, {"ipv4": _address(4), "ipv6": _address(6)}),
    "vpn": (
        VpnConfig,
        {
            "interface_patterns": _string_list(_interface_glob, allow_empty=False),
            "leak_guard_interfaces": _string_list(_interface_glob, allow_empty=True),
            "recheck_interval_s": _seconds(0.0, 3600.0),
            "max_reading_age_s": _seconds(0.0, 3600.0),
            "probe_timeout_s": _seconds(0.0, 60.0),
        },
    ),
    "indicator": (
        IndicatorConfig,
        {
            "show_on_fullscreen": _boolean,
            "blue_confirm_ms": _integer(0, 10_000),
            "red_confirm_ms": _must_be_zero,
        },
    ),
    "appearance": (
        AppearanceConfig,
        {
            "red": _colour,
            "blue": _colour,
            "thickness": _integer(1, 32),
            "glow": _integer(0, 128),
            "fade_ms": _integer(0, 2_000),
        },
    ),
    "pause": (PauseConfig, {"auto_resume_minutes": _integer(0, 24 * 60)}),
    "log": (
        LogConfig,
        {"max_bytes": _integer(10_000, 100_000_000), "backup_count": _integer(1, 20)},
    ),
}

# Every dataclass field must have a validator, and vice versa (checked once at import).
for _name, (_cls, _validators) in _SCHEMA.items():
    assert {f.name for f in fields(_cls)} == set(_validators), _name


# ---------------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------------


def parse_config(data: Mapping[str, object], source: Path | None = None) -> Config:
    """Validate an already-parsed TOML document and return a :class:`Config`."""
    warnings: list[str] = []
    sections: dict[str, Any] = {}
    for section, raw in data.items():
        if section not in _SCHEMA:
            warnings.append(f"unknown section [{section}] ignored")
            continue
        if not isinstance(raw, dict):
            raise ConfigError(f"{section}: expected a table ([{section}])")
        cls, validators = _SCHEMA[section]
        values: dict[str, object] = {}
        for key, value in raw.items():
            dotted = f"{section}.{key}"
            if key not in validators:
                warnings.append(f"unknown key {dotted} ignored")
                continue
            values[key] = validators[key](dotted, value)
        sections[section] = replace(cls(), **values)

    config = replace(Config(), **sections, warnings=tuple(warnings), source=source)
    _check_cross_field(config)
    return config


def _check_cross_field(config: Config) -> None:
    vpn = config.vpn
    if vpn.recheck_interval_s >= vpn.max_reading_age_s:
        raise ConfigError(
            "vpn.recheck_interval_s: must be shorter than vpn.max_reading_age_s "
            f"({vpn.recheck_interval_s:g} >= {vpn.max_reading_age_s:g}), or every reading "
            "would go stale before the next re-check"
        )
    if vpn.probe_timeout_s >= vpn.recheck_interval_s:
        raise ConfigError(
            "vpn.probe_timeout_s: must be shorter than vpn.recheck_interval_s "
            f"({vpn.probe_timeout_s:g} >= {vpn.recheck_interval_s:g})"
        )


def default_config_path(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_CONFIG_HOME/vpn-monitor/config.toml``, default ``~/.config/vpn-monitor/…``."""
    env = os.environ if env is None else env
    base = env.get("XDG_CONFIG_HOME") or ""
    root = Path(base) if os.path.isabs(base) else Path.home() / ".config"
    return root / "vpn-monitor" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load ``path`` (default :func:`default_config_path`); a missing file gives the defaults.

    Raises :class:`ConfigError` for unreadable TOML or invalid values.
    """
    path = default_config_path() if path is None else path
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read: {exc.strerror}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None
    return parse_config(data, source=path)
