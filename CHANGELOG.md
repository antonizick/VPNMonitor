# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/). Release headings carry a timestamp (`YYYY-MM-DD HH:MM TZ`).

## [Unreleased]

### Changed
- `vpn.leak_guard_interfaces` now defaults to ProtonVPN's kill-switch names `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*` (was `ipv6leakintrf0`).

### Added
- Governance files: `LICENSE` (MIT), `NOTICE`, `THIRD_PARTY_NOTICES.md`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- `.gitignore`, `.dockerignore`, `.editorconfig`.
- `.github/` issue templates, pull request template and Dependabot config for GitHub Actions.
- Docs skeleton (`docs/README.md`, `docs/screenshots/`).
- Pre-commit configuration with a `gitleaks` secret scan and basic hygiene hooks.
- Python package `vpn_monitor` (`pyproject.toml`, hatchling, no runtime dependencies, `uv.lock`) with a `vpn-monitor` console script stub (`--version`; subcommands exit 2 "not implemented yet").
- Shared types and the `FocusSource` / `VpnSource` / `IndicatorSink` Protocols in `model.py`; module stubs for every later phase; scripted fakes in `fakes.py`.
- Tests for the types, CLI and fakes; `gi` and `wayland` pytest markers that skip automatically.
- GitHub Actions CI (ruff, mypy, pytest on Python 3.12 and 3.14, actions pinned by commit SHA) and a Dependabot `uv` entry.
- `docs/VPM_ARCHITECTURE.md`; ADR-0011 (callback-style Protocols) and ADR-0012 (GLib main-loop model); ADR-0006 accepted.
- Pure decision engine (`engine.py`): HIDDEN / RED / BLUE for the focused browser's monitor; blue only from a fresh `VPN` reading whose per-family routes agree (spec S6); stale, future-dated, unknown or missing readings are red; optional `blue_confirm_ms` hysteresis (red is never delayed); `next_deadline()` and `active` for the daemon (ADR-0013).
- Browser matcher (`browsers.py`): exact classes plus full-match regexes, with the matching rule reported; defaults cover full browsers and Omarchy web apps.
- Configuration (`config.py`, `config/config.example.toml`): optional TOML file, defaults in code, strict validation with errors naming the key, warnings for unknown keys.
- Event log (`eventlog.py`): human log and JSONL events in `~/.local/state/vpn-monitor/`, size-rotated, fixed schema, and a `TitleGuard` that fails tests if a window title would be logged (ADR-0014).
- VPN detector (`vpn.py`): per-family `ip route get` probes, interfaces classified by kernel link kind (WireGuard/tun = VPN, `dummy` = blocked) plus name globs, so it works for any WireGuard or tun VPN; leaks, errors and kill-switch states resolved per spec R3, every failure `UNKNOWN` (red) (ADR-0015, spec AM-1).
- Route-change watcher `RouteWatcher` (the daemon's `VpnSource`): `ip monitor route rule link`, 200 ms debounce, re-check only while a browser is focused, restart with back-off, red if the watcher stays down (ADR-0007 Accepted). Measured VPN-drop reaction: 228 ms.
- `vpn-monitor probe` (`--json`, `--watch`, `--log`, `--config`): check and explain the VPN routes from the command line.
- `mainloop.py` (`Scheduler` Protocol, `GLibScheduler`) and `fakes.FakeScheduler` for timer/fd-driven modules.
- Route fixtures in `tests/fixtures/routes/` (recorded on the reference machine and synthesised, sanitised; a test rejects public addresses, MACs and SSIDs).
- Hyprland focus watcher (`focus.py`): `FocusWatcher` (the daemon's `FocusSource`) reads socket2 events, resolves focus with one `j/activewindow` per event batch, delivers only changes, shows "no focus" while disconnected and reconnects with 0.1 s to 5 s back-off, re-reading the initial state (ADR-0016). Window titles are dropped in the parser (spec S1).
- `vpn-monitor focus [--watch] [--json] [--log]`: print the focused window's class, matched browser rule, monitor and the event-to-delivery latency (never titles).
- Focus fixtures `tests/fixtures/focus/` (observed window classes, a synthetic socket2 stream with hostile titles); observed latency 2 to 7 ms.
- Tests: matcher, config validation, engine truth table, staleness, hysteresis, monitors, exhaustive and randomised S6 invariant checks, event-log schema and rotation (510 tests, 100 % coverage of engine, matcher, config and event log).
