# VPM Phase 03: Core state engine, browser matcher, config and event log

**Model:** Claude Opus 5.5 (`/model opus`) · **Depends on:** 02 · **Branch:** `phase-03-core-state-engine` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 (A1–A4), §2.2 R2, R4, R5, R7, R11, R13 and §2.3 S1, S6. Phase Log entry for Phase 02. ADR-0002, ADR-0003, ADR-0004, ADR-0010. The Brainstorm trace rows this phase fulfils or changes: B2 (trigger only while a browser is focused).

## Goal
A pure, exhaustively tested decision core: given the latest focus event, VPN reading, pause state and clock, it returns exactly one `Decision` per monitor, never shows blue on anything but a fresh positive reading, and logs every change with its inputs and reason.

## Tasks
1. `browsers.py`: `BrowserMatcher` built from config: exact classes (default `brave-browser`, `chromium`, `google-chrome`, `firefox`, `librewolf`, `zen`, `vivaldi-stable`, `org.mozilla.firefox`) and regexes (default `^(brave|chrome|chromium|msedge)-.+__.*$` for Omarchy/Chromium `--app` windows). Case-sensitive exact match, compiled regexes, a `match(cls) -> MatchResult(matched, rule)` that says which rule matched.
2. `engine.py`: `Engine` with `on_focus(FocusEvent)`, `on_vpn(VpnReading)`, `on_pause(bool)`, `on_monitors(list[MonitorInfo])`, `tick(now)` returning the new `Decision` only when it changed. Rules: no browser focused → HIDDEN; paused → HIDDEN; browser focused + reading `VPN` and not older than `max_reading_age` (default 10 s) → BLUE; everything else (NO_VPN, UNKNOWN, stale, no reading yet) → RED. Fullscreen honours `show_on_fullscreen` (owner question 3, default true). Monitor = focused window's monitor.
3. Hysteresis: optional `blue_confirm_ms` (default 0) and `red_confirm_ms` (default 0, i.e. red is immediate); state the rationale in an ADR (red is never delayed, a flapping VPN shows red).
4. `config.py`: load `~/.config/vpn-monitor/config.toml` with `tomllib`; every key optional with defaults in code; strict validation (unknown keys warn, bad types/regexes/colours raise a clear error naming the key); keys for matcher, probes (`ipv4`, `ipv6` destinations), VPN interface patterns, re-check interval, max reading age, colours, thickness/glow, fullscreen, pause behaviour. `config/config.example.toml` documents every key.
5. `eventlog.py`: human log + JSONL events under `$XDG_STATE_HOME/vpn-monitor/` (default `~/.local/state/vpn-monitor/`), size-based rotation (stdlib `RotatingFileHandler`), schema: `ts`, `event`, `decision`, `reason`, `inputs` (class, matched rule, per-family routes, reading age, paused). A guard that raises in tests if any string field equals a title passed in a fake event (S1).
6. Property-style tests (plain pytest with parametrised tables or `hypothesis` if you add it as a pinned dev dependency, with a licence check): over all combinations of inputs, BLUE implies browser focused ∧ not paused ∧ fresh VPN reading.

## Out of scope
Real focus/VPN sources (04, 05), drawing (06), daemon wiring and control socket (07).

## Tests
Unit tests for matcher (real classes from spec Appendix A plus web-app samples), engine truth table, staleness, hysteresis, config validation errors, eventlog schema and rotation. Coverage ≥ 95 % for `engine.py`, `browsers.py`, `config.py`.

## Acceptance criteria
- The S6 invariant test passes; no test or code path yields BLUE from UNKNOWN, stale or missing readings.
- `uv run python -c` loading `config/config.example.toml` gives the same values as the defaults.
- All quality gates pass.

## Phase-specific docs
`docs/VPM_ARCHITECTURE.md` (engine rules table, event schema), `config/config.example.toml`, README (configuration section), CHANGELOG, ADRs (hysteresis, schema). Brainstorm trace B2 updated. Then the standard close-out checklist.
