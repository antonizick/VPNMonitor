# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [Semantic Versioning](https://semver.org/). Release headings carry a timestamp (`YYYY-MM-DD HH:MM TZ`).

## [Unreleased]

### Fixed
- CI: `mypy` failed on the GitHub runner (`Cannot find implementation or library stub for module named "cairo"`) because pycairo is a system package like PyGObject; `cairo` joins `gi` in the mypy `ignore_missing_imports` overrides, and the overlay tests use a stand-in `cairo` module when pycairo is absent (14 tests failed on the runner; the two real-surface tests skip). Found when CI first ran after the billing fix (2026-11-19 13:28 CST).

## [1.0.0] - 2026-11-19 13:15 CST

First release: the complete VPN Monitor (phases 01 to 09). Tagged `v1.0.0` on the private repository; no GitHub release. See `docs/VPM_FINAL-REPORT.md`.

### Added
- README close-up and full-width screenshots of the red and blue bar (`docs/screenshots/vpm-bar-zoom.png`, `vpm-bar-wide.png`); 2026-11-19 13:20 CST.
- `docs/VPM_FINAL-REPORT.md`: what was built, brainstorm trace, measured numbers, known limits, future work and the generated timeline.

### Security
- Staleness now counts time spent suspended (`CLOCK_BOOTTIME`): a VPN reading taken before a suspend is stale on resume, so the bar cannot stay blue across a sleep on stale data (ADR-0019).
- Log files are created mode 0600, and existing ones are tightened at start.
- ruff's bandit (`S`) rules are part of the lint gate; `assert`s in the package became explicit checks.
- `docs/VPM_THREAT_MODEL.md`: assets, false-blue failure modes, privacy and local attackers, each mapped to a test or mitigation; scanner results.

### Fixed
- An unwritable log directory or log file crashed the daemon at start (the service restart-looped with no bar); the log now falls back to stderr (the journal), logs `log_degraded` and the indicator keeps working. A failing write (disk full) is reported once instead of on every event.
- Idle CPU: a focused window whose title changes often (a terminal) made the focus watcher ask Hyprland for the active window on every title change; those repeats are now skipped (idle 0.21 % CPU and 2.3 wake-ups/s → 0.057 % and 0.73/s).
- Probes took 300 to 400 ms inside the daemon (a red bar for about 0.3 s every time a browser gained focus) because child `ip` processes inherited the daemon's `LD_PRELOAD=libgtk4-layer-shell.so`; the layer-shell preload is now dropped from their environment (20 ms probes, reading age at start 6 ms).

### Changed
- Default look approved at the Phase 06 review (owner question 2): `appearance.thickness = 2`, `glow = 10`, `red = "#FF3B30CC"`, `blue = "#0A84FFCC"` (was 3 / 12 / `#FF3B30` / `#0A84FF`).
- `vpn.leak_guard_interfaces` now defaults to ProtonVPN's kill-switch names `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*` (was `ipv6leakintrf0`).

### Added
- End-to-end fault-injection tests (`tests/test_fault_injection.py`): `ip` hangs or is missing, `ip monitor` dies, Hyprland's socket closes mid-line, surface creation fails, read-only log directory, disk full, suspend, wall-clock jumps; each ends red or hidden and is logged.
- README performance table (measured), future work, and more honest limits; THIRD_PARTY_NOTICES lists the programs run at runtime.
- The daemon (`daemon.py`): focus + VPN sources → engine → overlay on the GLib main loop, one deadline timer so a stuck VPN watcher turns blue into red, fail-safe to red on any callback or engine error, clean shutdown on SIGTERM/SIGINT, config reload on SIGHUP (ADR-0018).
- Control socket (`control.py`): `$XDG_RUNTIME_DIR/vpn-monitor/control.sock` (0700/0600, `SO_PEERCRED` uid check, one JSON line, fixed command set), single-instance `flock`, and the CLI `run`, `pause`, `resume`, `toggle` (desktop notifications), `status [--json]` and `log [-f] [--events]` (spec AM-3).
- `packaging/systemd/vpn-monitor.service`: sandboxed user unit (`RestrictAddressFamilies=AF_UNIX AF_NETLINK`, `ProtectSystem=strict`, … exposure 1.6 OK).
- `scripts/install.sh`, `scripts/uninstall.sh` and the `scripts/vpn-monitor` wrapper: symlink, user unit, the pause key SUPER+ALT+SHIFT+V in `bindings.lua` (backup, marked block, key-free check), all idempotent and reversible (ADR-0009 accepted).
- Soft audio feedback for pause (falling cue) and resume (rising cue), including the SUPER+ALT+SHIFT+V key: `sound.py` synthesises two short sine cues and plays them with `pw-play`/`paplay`/`aplay`; `pause.sound` and `pause.sound_volume` configure it.
- README install, usage, uninstall and troubleshooting sections; SECURITY control-socket and sandbox details.
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
- Glow-bar overlay (`overlay.py`): click-through GTK4 layer-shell bar per monitor (layer OVERLAY, no exclusive zone, no keyboard, empty input region), 150 ms fades and red ↔ blue cross-fade on the frame clock with no idle redraws, device-pixel-snapped core line and gradient glow, monitor hot-plug handling, toolkit faults logged not raised; re-execs once with `LD_PRELOAD` for gtk4-layer-shell and uses the cairo renderer (ADR-0017, spec AM-2).
- `vpn-monitor preview red|blue|cycle` (`--seconds`, `--monitor`, `--backdrop`, `--log`, `--config`) and `scripts/preview.sh` for screenshots; reviewed screenshots in `docs/screenshots/`.
