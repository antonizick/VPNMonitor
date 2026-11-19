# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/). Release headings carry a timestamp (`YYYY-MM-DD HH:MM TZ`).

## [Unreleased]

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
- Tests: matcher, config validation, engine truth table, staleness, hysteresis, monitors, exhaustive and randomised S6 invariant checks, event-log schema and rotation (510 tests, 100 % coverage of engine, matcher, config and event log).
