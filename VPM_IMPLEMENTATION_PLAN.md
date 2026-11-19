# VPM: VPN Monitor Implementation Plan

**Spec:** [`docs/VPM_SPECIFICATION.md`](docs/VPM_SPECIFICATION.md). **Decisions:** [`docs/VPM_DECISIONS.md`](docs/VPM_DECISIONS.md). **Agent rules:** [`CLAUDE.md`](CLAUDE.md). **Shared phase instructions:** [`prompts/VPM_shared-instructions.md`](prompts/VPM_shared-instructions.md)
**Last updated:** 2026-11-19 08:38 CST (Phase 05, Hyprland focus watcher)
**Brainstorm:** VPM_Brainstorming.md
The brainstorm is traced in the spec's Amendments ("Brainstorm trace") and drawn in the timeline's Planning lane.

> ⚠️ **Mandatory:** every agent that works on this project keeps this file accurate. **Before doing any other work, set your phase to `🔄 In progress` and commit that change to `main`** (claim protocol: `prompts/VPM_shared-instructions.md` §1a). Other agents read this table from `main`. At the end, set it to `✅ Complete` or `⛔ Blocked` and add a Phase Log entry. See `CLAUDE.md`.

## How to run a phase
Open Claude Code in `/home/nick/Work/VPNMonitor` and type one of:
- `/phase`: run the next eligible phase. It checks dependencies, tells you if you're on the wrong model, resumes an `In progress` phase, and asks about any open questions it needs.
- `/phase NN`: run a specific phase.
- `/phase status`: show progress and what's next, without doing any work.
- `/phase-add [after NN] <request or file>`: plan a new lettered phase (`07a`) from a change request. No product work, no claim.

**Optional hands-off runs (PhaseHypervisor):** `phx preflight /home/nick/Work/VPNMonitor` asks the foreseeable questions once, then `phx run /home/nick/Work/VPNMonitor` runs the remaining phases unattended through `/phase NN --auto`, honouring the Gate column. Manual `/phase` stays the standard way; you can switch between the two at any phase boundary, and `/phase` stops if a `phx` supervisor is running this plan.

The agent merges a completed phase into `main` and pushes it without asking (Nick's standing git authority); review its close-out summary.

Each phase is claimed by a `chore(plan): start phase NN` commit on `main` and runs in its own worktree, `../VPNMonitor-phase-NN`, so parallel sessions never share a checkout. `/phase status` flags any branch or worktree whose row is not `🔄 In progress`.

**Parallelism:** after Phase 03, Phases **04, 05 and 06** are independent (each builds against the Phase 02 interfaces and fakes) and can run in parallel sessions. Everything else is sequential. Phases 04 and 07 need Nick at the keyboard briefly (he toggles the VPN himself); Phase 06 needs his approval of the screenshots.

**Gate column** (read only by PhaseHypervisor; manual `/phase` ignores it): `auto` = may run unattended; `review` = pause for Nick after it; `owner` = Nick starts it. Empty means `auto`.

**Status values:** ⬜ Not started · 🔄 In progress · ⛔ Blocked · ✅ Complete. Always write the icon **and** the word.

## Phases

| Phase | Phase Name | Phase Purpose | AI Model to Use | Depends on | Status | Prompt to Initiate This Phase | Gate |
|---|---|---|---|---|---|---|---|
| 00 | Planning & spec refinement | Review source docs, resolve decisions, write the spec, plan and prompts | Claude Opus 5.5 | none | ✅ Complete | n/a (planning session) | owner |
| 01 | Repository foundation & governance | Governance files, docs skeleton, gitleaks, private GitHub repo | Claude Sonnet 5.5 (`/model sonnet`) | 00 | ✅ Complete | [`prompts/VPM_phase-01-repo-foundation.md`](prompts/VPM_phase-01-repo-foundation.md) | auto |
| 02 | Python scaffold, CI & quality gates | Package, shared types, Protocols, fakes, CLI stub, CI, architecture doc | Claude Sonnet 5.5 (`/model sonnet`) | 01 | ✅ Complete | [`prompts/VPM_phase-02-python-scaffold-ci.md`](prompts/VPM_phase-02-python-scaffold-ci.md) | auto |
| 03 | Core state engine | Pure decision engine (no false blue), browser matcher, config, event log | Claude Opus 5.5 (`/model opus`) | 02 | ✅ Complete | [`prompts/VPM_phase-03-core-state-engine.md`](prompts/VPM_phase-03-core-state-engine.md) | auto |
| 04 | VPN route detector | Route probes per family, interface classifier, leak/fail-safe rules, change watcher | Claude Opus 5.5 (`/model opus`) | 03 | ✅ Complete | [`prompts/VPM_phase-04-vpn-detector.md`](prompts/VPM_phase-04-vpn-detector.md) | auto |
| 05 | Hyprland focus watcher | socket2 events → FocusEvent (no titles), initial state, reconnect, real classes | Claude Sonnet 5.5 (`/model sonnet`) | 03 | ✅ Complete | [`prompts/VPM_phase-05-hyprland-focus-watcher.md`](prompts/VPM_phase-05-hyprland-focus-watcher.md) | auto |
| 06 | Glow bar overlay | Click-through layer-shell red/blue glow bar, fades, multi-monitor, screenshots approved by Nick | Claude Opus 5.5 (`/model opus`) | 03 | 🔄 In progress | [`prompts/VPM_phase-06-glow-bar-overlay.md`](prompts/VPM_phase-06-glow-bar-overlay.md) | review |
| 07 | Daemon, service & install | Wiring, control socket, CLI, systemd user unit, pause keybinding, install/uninstall, OSMods | Claude Sonnet 5.5 (`/model sonnet`) | 04, 05, 06 | ⬜ Not started | [`prompts/VPM_phase-07-daemon-service-install.md`](prompts/VPM_phase-07-daemon-service-install.md) | review |
| 08 | Hardening, security & QA | Threat model, fault injection, scanners, measured performance, log hygiene, follow-ups | Claude Opus 5.5 (`/model opus`) | 07 | ⬜ Not started | [`prompts/VPM_phase-08-hardening-security-qa.md`](prompts/VPM_phase-08-hardening-security-qa.md) | auto |
| 09 | Release & publication | v1.0.0 tag, final report with timeline, publish only on Nick's yes | Claude Sonnet 5.5 (`/model sonnet`) | 08 | ⬜ Not started | [`prompts/VPM_phase-09-release-publication.md`](prompts/VPM_phase-09-release-publication.md) | review |

## Timeline
Generated by `scripts/phase_timeline.py` from the Phase Log and git; refreshed on `main` at every close-out, block, resume and `/phase-add`. Do not edit between the markers.

<!-- phase-timeline:start (generated by scripts/phase_timeline.py; do not edit) -->
![VPM timeline](docs/VPM_TIMELINE.svg)

*Generated from the Phase Log Timeline bullets and git, as of 2026-11-19 08:42 CST. ≈ marks a time inferred from git or a heading. Idle gaps over 60 min start a new chart below and are collapsed in the image. Regenerate with `python3 scripts/phase_timeline.py --write`; do not edit by hand.*

```mermaid
gantt
    title VPM session 1, 2026-11-18 21:30 to 22:57 CST
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %H:%M
    section Planning
    Brainstorming (1 entry) :milestone, bs1, 2026-11-18 21:30, 0m
    Planning & spec refinement :done, p00, 2026-11-18 21:51, 2026-11-18 21:59
    section Phases
    01 Repository foundation & governance :done, p01s1, 2026-11-18 22:09, 2026-11-18 22:10
    02 Python scaffold, CI & quality gates :done, p02s1, 2026-11-18 22:11, 2026-11-18 22:19
    03 Core state engine :done, p03s1, 2026-11-18 22:20, 2026-11-18 22:30
    04 VPN route detector :done, p04s1, 2026-11-18 22:40, 2026-11-18 22:57
```

```mermaid
gantt
    title VPM session 2, 2026-11-19 08:31 to 08:42 CST
    dateFormat YYYY-MM-DD HH:mm
    axisFormat %H:%M
    section Phases
    05 Hyprland focus watcher :done, p05s2, 2026-11-19 08:31, 2026-11-19 08:38
    06 Glow bar overlay :active, p06s2, 2026-11-19 08:42, 2026-11-19 08:43
```

| Phase | Name | Started | Finished | Merged | Active | Blocked | Claim |
|---|---|---|---|---|---:|---:|---|
| brainstorm | Brainstorming (1 entry) | 2026-11-18 21:30 CST |  |  |  |  | n/a |
| 00 | Planning & spec refinement | 2026-11-18 21:51 CST | 21:59 |  | 8 m |  | n/a |
| 01 | Repository foundation & governance | 2026-11-18 22:09 CST | 22:10 | 22:10 | 1 m |  | `d547144` |
| 02 | Python scaffold, CI & quality gates | 2026-11-18 22:11 CST | 22:19 | 22:19 | 8 m |  | `fb6aca4` |
| 03 | Core state engine | 2026-11-18 22:20 CST | 22:30 | 22:30 | 10 m |  | `38929c7` |
| 04 | VPN route detector | 2026-11-18 22:40 CST | 22:57 | 22:57 | 17 m |  | `ac402ee` |
| 05 | Hyprland focus watcher | 2026-11-19 08:31 CST | 08:38 | 08:38 | 7 m |  | `0f2c09f` |
| 06 | Glow bar overlay | 2026-11-19 08:42 CST | (in progress) |  | < 1 m so far |  | `80167dc` |

**Totals:** elapsed 11 h 12 m (first recorded start to 2026-11-19 08:42 CST) · active phase time 43 m (sum over phases) · blocked or paused 0 m · idle 9 h 34 m in 1 gap(s) over 60 min.

**Not started:** 07, 08, 09.
<!-- phase-timeline:end -->

### Model rationale
- **Opus 5.5** where a subtle mistake would make the indicator lie or the desktop misbehave: **03** (the decision engine and its "never a false blue" invariant), **04** (route/policy-routing parsing and leak classification, security-critical), **06** (GTK4 layer-shell drawing, scaling, animation without idle redraws, click-through; complex interactive UI), **08** (security review and fault injection).
- **Sonnet 5.5** for well-specified work: **01** (governance files), **02** (scaffolding and CI), **05** (Hyprland's line protocol is simple and documented; the risky part, title stripping, is spelled out and tested), **07** (wiring against finished components, systemd unit, install scripts), **09** (release paperwork).
- Fable 5.2 is not needed for any phase: no phase needs deeper reasoning than Opus gives, and it costs more.

### Dependency graph
```
00 ─► 01 ─► 02 ─► 03 ─┬─► 04 (VPN detector) ──────┐
                      ├─► 05 (focus watcher) ─────┼─► 07 (daemon + install) ─► 08 (hardening) ─► 09 (release)
                      └─► 06 (overlay, review) ───┘
```
Parallel: 04 ∥ 05 ∥ 06.

### Definition of done (checked in the final phase)
- [ ] With a browser or Omarchy web app focused, the bottom edge of its monitor glows **blue** when internet routes leave via a VPN and **red** otherwise; no bar when a non-browser is focused.
- [ ] A VPN drop shows red within 2 s; a focus change updates the bar within 150 ms (measured).
- [ ] No false blue in any tested fault (unknown, stale, split-tunnel leak, watcher crash, suspend).
- [ ] Window titles never appear in logs or state; no external network calls (tests + log audit).
- [ ] Idle cost ~0 % CPU with no browser focused (measured).
- [ ] Runs at login as a systemd user service; pause/resume keybinding and CLI work; install/uninstall are clean and documented in OSMods.
- [ ] Nick approved the look (Phase 06 screenshots).
- [ ] All governance files present; CI green; tag `v1.0.0`; final report with generated timeline.
- [ ] Every brainstorm trace row is fulfilled or has a recorded disposition.
- [ ] Repo visibility and release state match Nick's recorded answer.

## Owner questions
| # | Question | Status / proposed default | Needed by |
|---|---|---|---|
| 1 | Pause/resume keybinding (SUPER+ALT+V is taken by Prometheus) | Open (asked 2026-11-18 21:58 CST, Phase 00). Proposed default: SUPER+ALT+SHIFT+V | Phase 07 |
| 2 | Exact look: thickness, glow, red and blue shades | Open (asked 2026-11-18 21:58 CST, Phase 00). Proposed default: 3 px core + 12 px glow, `#FF3B30` / `#0A84FF`; decided at the Phase 06 screenshot review | Phase 06 |
| 3 | Show the bar over a fullscreen browser (videos)? | Open (asked 2026-11-18 21:58 CST, Phase 00). Proposed default: yes | Phase 06 |
| 4 | How long does a pause last? | Open (asked 2026-11-18 21:58 CST, Phase 00). Proposed default: until resumed or next login | Phase 07 |
| 5 | Add DNS-leak detection? | Deferred (2026-11-18 21:58 CST): out of this plan; add later with `/phase-add` if wanted | none |
| 6 | Make the GitHub repo public and/or publish a release? | Open (asked 2026-11-18 21:58 CST, Phase 00). Proposed default: stays private, no release | Phase 09 |

## Phase Log
Newest entries at the bottom. Format: `### YYYY-MM-DD HH:MM TZ: Phase NN: <title> (<status>)` (timestamp from `date '+%Y-%m-%d %H:%M %Z'`, never a bare date). **The first bullet is always the Timeline:** `- **Timeline:** started <TS> (claim commit <hash>) · finished <TS> · merged <TS | not merged yet>` (add ` · blocked <TS> to <TS>` per `⛔` interval; *started* is the claim commit's time). Then bullets: built, deviations, follow-ups, tests.

### 2026-11-18 21:59 CST: Phase 00: Planning & spec refinement (✅ Complete)
- **Timeline:** started 2026-11-18 21:51 CST · finished 2026-11-18 21:59 CST
- **Brainstorm:** `VPM_Brainstorming.md`, 1 entry from 2026-11-18 21:30 CST to 2026-11-18 21:30 CST; 6 adopted, 0 deferred, 0 dropped (spec Amendments, "Brainstorm trace"); covered through 2026-11-18 21:30 CST.
- Read the brainstorm in full and inspected the machine (Hyprland 0.56.2 Lua config, ProtonVPN WireGuard `proton0` with policy routing and IPv6 leak guard, Tailscale, Brave/Chromium, gtk4-layer-shell, Python 3.14.8, existing keybindings). Feasibility confirmed: yes (spec R1).
- Owner decisions (one round): red/blue steady glow while a browser is focused; VPN = traffic actually routed via a VPN; browsers include Omarchy web apps; always-on user service with a pause key. Prefix `VPM` taken from the brainstorm file name.
- Refinements: pure engine with fail-safe red (R2, R4), per-family route probes with leak detection (R3), event-driven detection with re-check only while a browser is focused (R5), privacy baseline (no titles, no network calls), performance budget (R13).
- Found: SUPER+ALT+V is already bound (Prometheus), so the pause key default is SUPER+ALT+SHIFT+V (owner question 1).
- Wrote: spec with Amendments and brainstorm trace, ADR-0001…0010, this plan with 9 phases, shared instructions, phase prompts, `CLAUDE.md`, `/phase` and `/phase-add`, change-request template, vault note `02 Projects/VPM Implementation Plan.md`, timeline generator.
- Timeline tooling workarounds (skill bugs, reported to Nick, not fixed in PhaseHypervisor): the plan template's `**Brainstorm:**` line had trailing text that `phase_timeline.py` read as part of the file name, so the description moved to its own line; the brainstorm stamp had no zone and was read as UTC, so ` CST` was added to its single header line in `VPM_Brainstorming.md`.
- Tests: none (planning only).

### 2026-11-18 22:10 CST: Phase 01: Repository foundation & governance (✅ Complete)
- **Timeline:** started 2026-11-18 22:09 CST (claim commit d547144) · finished 2026-11-18 22:10 CST · merged 2026-11-18 22:10 CST
- **Model:** ran as Claude Sonnet 5.5 (plan lists Sonnet 5.5)
- **Built:** `LICENSE` (MIT), `NOTICE`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md` (licences read from `pacman -Qi`: gtk4 LGPL-2.1-or-later, gtk4-layer-shell MIT, python-gobject LGPL-2.1-or-later), `.gitignore` (extended the existing file), `.dockerignore`, `.editorconfig`, `.github/` (bug and feature templates, PR template, Dependabot for github-actions), `docs/README.md`, `docs/screenshots/.gitkeep`, `.pre-commit-config.yaml` (gitleaks v8.30.1, pre-commit-hooks v6.0.0, both verified as latest releases).
- **Deviations:** the Phase 01 prompt named the copyright holder "Nick Antoncic"; the git identity and GitHub account say "Nick Antonizick", so the licence and notice use that spelling (treated as a typo in the prompt). The `end-of-file-fixer` hook excludes `VPM_Brainstorming.md` (owner's source file, left byte-for-byte unchanged); it added a final newline to `prompts/VPM_shared-instructions.md`.
- **Follow-ups:** Phase 02 adds the pip/uv Dependabot entry, CI, and dev-tool licences in THIRD_PARTY_NOTICES; CONTRIBUTING setup commands are placeholders until then.
- **Tests:** `pre-commit run --all-files` passes (gitleaks finds nothing); no `{{` template markers in governance files. No code, so no pytest.

### 2026-11-18 22:19 CST: Phase 02: Python scaffold, CI & quality gates (✅ Complete)
- **Timeline:** started 2026-11-18 22:11 CST (claim commit fb6aca4) · finished 2026-11-18 22:19 CST · merged 2026-11-18 22:19 CST
- **Model:** ran as Claude Sonnet 5.5 (plan lists Sonnet 5.5)
- **Built:** `pyproject.toml` (hatchling, no runtime deps, dev group pytest/pytest-cov/ruff/mypy locked in `uv.lock`, ruff + `mypy --strict` on `src/`, `gi`/`wayland` markers); `src/vpn_monitor/` with `model.py` (frozen types, no title field anywhere, `FocusSource`/`VpnSource`/`IndicatorSink` Protocols), stubs for engine (shaped as the Phase 03 `Engine` class), browsers, config, eventlog, vpn, focus, overlay, control, daemon, `fakes.py`, `cli.py` (spec R10 subcommands, stubs exit 2) and `__main__.py`; tests (20 pass: model immutability and no-title, CLI, fakes, Protocol conformance) with a `conftest.py` that skips `gi`/`wayland` tests; `.github/workflows/ci.yml` (Python 3.12 + 3.14, actions pinned by SHA) and a Dependabot `uv` entry; `docs/VPM_ARCHITECTURE.md`; CONTRIBUTING setup, README, CHANGELOG, THIRD_PARTY_NOTICES (dev licences), CLAUDE.md test line confirmed.
- **ADRs:** ADR-0006 verified and Accepted (`gi` + `Gtk4LayerShell` import without `LD_PRELOAD`; library `/usr/lib/libgtk4-layer-shell.so`); new ADR-0011 (callback-style Protocols) and ADR-0012 (single GLib main loop).
- **Findings:** `uv` picks a uv-managed Python 3.13 that cannot import the system `gi`, so `[tool.uv] python-preference = "only-system"` is set; CI overrides it with `UV_PYTHON_PREFERENCE=managed`. `ruff format` would rewrite `scripts/phase_timeline.py` (copied from the skill), so it is excluded from ruff. `pre-commit` is not run in CI (documented in CONTRIBUTING).
- **Deviations:** acceptance item "CI run green on GitHub" is **not met**: GitHub Actions refuses to start jobs ("recent account payments have failed or your spending limit needs to be increased", run https://github.com/antonizick/VPNMonitor/actions/runs/44457085826). Nick chose to close the phase with CI deferred. The CI recipe was verified locally instead: `uv sync --frozen --python 3.12` on a managed interpreter, then mypy and pytest pass (3.12.15 and system 3.14.8). The workflow also triggers on `phase-*` branches.
- **Follow-ups:** fix GitHub billing, then re-run the CI workflow on `main` and record the result; adding a Phase 08 check that CI is green before release.
- **Tests:** `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` all pass locally (20 passed); `pre-commit run --all-files` passes.

### 2026-11-18 22:30 CST: Phase 03: Core state engine (✅ Complete)
- **Timeline:** started 2026-11-18 22:20 CST (claim commit 38929c7) · finished 2026-11-18 22:30 CST · merged 2026-11-18 22:30 CST
- **Model:** ran as Claude Opus 5.5 (plan lists Opus 5.5)
- **Built:** `engine.py` (`Engine` with `on_focus/on_vpn/on_pause/on_monitors/tick`, returns a Decision only when indicator, monitor or reason changes; `reading_problem()` as the single gate for blue; `next_deadline()` and `active` for the daemon; `from_config`), `browsers.py` (`BrowserMatcher`, exact classes + `re.fullmatch` regexes, reports the matching rule), `config.py` (frozen `Config` with sections browsers/probes/vpn/indicator/appearance/pause/log, defaults in code, strict validation naming the key, unknown keys as warnings, cross-field timing rules), `eventlog.py` (`EventLog`: human log + JSONL in `$XDG_STATE_HOME/vpn-monitor/`, 0700, size rotation, fixed schema; `TitleGuard`), `config/config.example.toml` (every key, equal to the defaults). Docs: architecture (engine rules table, matcher, config, event schema), README configuration section, SECURITY S1 note, CHANGELOG, ADR-0013 (engine rules and hysteresis), ADR-0014 (event-log format), brainstorm trace B2, notes for the Phase 04–07 prompts.
- **Deviations:** `red_confirm_ms` exists but must be 0 (anything else is a `ConfigError`): a red delay would keep a false blue on screen, which S6 forbids (ADR-0013). Beyond the prompt, the engine cross-checks a `VPN` reading against its routes (defence in depth; also makes "everything blocked, no tunnel" red as R4 requires) and rejects NaN or future-dated readings. The clock is injected in the constructor (`clock()`), and `tick(now)` also accepts an explicit time. With no resolvable monitor the decision is HIDDEN. New config keys not named in the prompt: `appearance.fade_ms`, `pause.auto_resume_minutes` (owner question 4; 0 = until resume or next login), `vpn.probe_timeout_s`, `[log]` rotation. `browsers.is_browser()` stub removed (unused). No `hypothesis` dependency: the S6 property tests are an exhaustive `itertools.product` table plus 200 seeded random event sequences.
- **Owner questions:** none needed. Q3 (fullscreen) is a config key defaulting to `true` as proposed and stays open for the Phase 06 review; Q4 is the `pause.auto_resume_minutes` key (default 0) for Phase 07.
- **Follow-ups:** Phase 07 must schedule a timer at `engine.next_deadline()` after each input (recorded in its prompt). GitHub CI is still blocked by account billing (Phase 02 follow-up).
- **Tests:** 510 passed (490 new); coverage 100 % for `engine.py`, `browsers.py`, `config.py` and `eventlog.py`. Mutation checks: removing the staleness check, the leak check or the pause rule each fails the suite. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` pass; `pre-commit run --all-files` passes. `load_config(config/config.example.toml) == Config()` is True.

### 2026-11-18 22:57 CST: Phase 04: VPN route detector (✅ Complete)
- **Timeline:** started 2026-11-18 22:40 CST (claim commit ac402ee) · finished 2026-11-18 22:57 CST · merged 2026-11-18 22:57 CST
- **Model:** ran as Claude Opus 5.5 (plan lists Opus 5.5)
- **Built:** `vpn.py`: `RouteProbe` (`ip -4|-6 -j route get`, fixed argv, `LC_ALL=C`, 1 s timeout; timestamp taken before probing), `LinkClassifier` (kernel link kind from `ip -d -j link show`: `wireguard`/`tun` = VPN, `dummy` = blocked; plus `vpn.interface_patterns` / `vpn.leak_guard_interfaces` globs; cached, reloaded per change burst), `combine()` (spec R3: leak → NO_VPN, error → UNKNOWN, nothing via VPN → NO_VPN, else VPN; a crash → UNKNOWN), `RouteWatcher` (the `VpnSource`: `ip monitor route rule link` through fd watches, 200 ms leading-window debounce, re-check every 5 s only while active, restart with back-off 0.5→30 s, `VPN` downgraded to `UNKNOWN` while the monitor is down > `max_reading_age_s`, `reading`/`vpn_watcher` log events with trigger and latency). `mainloop.py` (`Scheduler` Protocol, `GLibScheduler` using `GLibUnix.fd_add_full`), `fakes.FakeScheduler`, `vpn-monitor probe [--json] [--watch [--log]] [--config]` (exit 0 VPN / 1 NO_VPN / 3 UNKNOWN / 2 config error). Fixtures in `tests/fixtures/routes/` (4 recorded, 6 synthesised, sanitised).
- **Live verification (Nick toggled ProtonVPN, 22:53–22:54 CST):** VPN up: both families via `proton0` (wireguard, table 245447468); Proton now gives IPv6, so `ipv6leakintrf0` is only used during teardown. Disconnected: IPv4 via `wlo1` (leak) and IPv6 unreachable → NO_VPN **228 ms** after the first route event. Reconnecting: both families into the kill-switch dummy `pvpnksintrf0` → NO_VPN (red), then VPN 222 ms after the route event. Probe cost ≈ 12 ms. `vpn-monitor probe` with Proton up reports VPN with both families explained. All three acceptance criteria met.
- **Deviations:** (1) Classification uses the kernel link kind instead of `nmcli` (ADR-0015, spec AM-1), so it is generic, as Nick asked mid-phase ("I'm hoping this tool is a generic VPN detector"); any `dummy` device counts as blocked. (2) The monitor also watches `rule` (Proton switches policy rules). (3) `vpn.leak_guard_interfaces` defaults changed to `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*` (names read from the installed Proton client; config example and README updated). (4) Fixture destinations are documentation addresses (`192.0.2.1`, `2001:db8::1111`) so no fixture holds a public IP. (5) The kernel error "Invalid argument" (possibly an IPv4 blackhole) stays `ERROR` (red) rather than guessing `BLOCKED`. ADR-0007 Accepted with the event-source choice and measurements.
- **Findings:** the phase worktree's venv must be made with `uv venv --system-site-packages` (as CONTRIBUTING says); a plain `uv sync` venv silently skips the `gi` tests. Noted in the Phase 05 prompt.
- **Follow-ups:** Phase 07 wires `RouteWatcher` (notes added to its prompt); Phase 08 measures end-to-end drop → red through the daemon (note added). Policy-based IPsec without an interface shows red (README limits). GitHub CI still blocked by account billing (Phase 02 follow-up).
- **Tests:** 634 passed (124 new: fixture scenarios, every kernel answer and failure, classifier fallbacks and caching, all 25 per-family combinations cross-checked against `engine.reading_problem`, watcher debounce/re-check/back-off/restart/blind downgrade/logging/stop, real subprocess stream, GLib scheduler, CLI `probe`, fixture privacy scan, no network imports). Coverage: `vpn.py` 99 %, `mainloop.py` 100 %. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` pass; `pre-commit run --all-files` passes.

### 2026-11-19 08:38 CST: Phase 05: Hyprland focus watcher (✅ Complete)
- **Timeline:** started 2026-11-19 08:31 CST (claim commit 0f2c09f) · finished 2026-11-19 08:38 CST · merged 2026-11-19 08:38 CST
- **Model:** ran as Claude Sonnet 5.5 (plan lists Sonnet 5.5)
- **Built:** `focus.py`: pure parser (`parse_event_line`, `parse_active_window`, `parse_monitors`, `parse_clients`; titles dropped there: `activewindow>>class,title` keeps only the class, title-bearing events are reduced to their name, JSON replies are read field by field, parse errors never quote the reply), `locate_sockets` (signature, else newest live instance; `HyprlandNotRunning`), `SocketEventStream`, `HyprlandClient` (`j/activewindow`, `j/monitors` id → name table, `j/clients` for diagnostics), `FocusWatcher` (the `FocusSource`: "no focus" first, initial state, one request per event batch, deliver only changes, "no focus" while disconnected or when a request fails, reconnect 0.1 s doubling to 5 s reset after 10 s, one log line per distinct error, `focus` events logged with class/monitor/fullscreen/trigger, `last_latency_s`). `vpn-monitor focus [--watch] [--json] [--log] [--config]` (exit 0 browser / 1 other / 2 no Hyprland or bad config). Fixtures `tests/fixtures/focus/` (`classes.json`, `socket2.txt` with hostile titles).
- **Live verification (reference machine, 2026-11-19 08:35 CST):** `vpn-monitor focus --watch` while focus was switched between foot and Brave (via `hl.dsp.focus`): each change printed with 5 to 6 ms from receipt to delivery (earlier run 2 to 7 ms), correct class, rule and monitor (`HDMI-A-1`); acceptance limit is 150 ms. Observed classes: `brave-browser`, `brave-maps.google.com__-Default` (an Omarchy web app launched with `omarchy-launch-webapp`; matches the default regex), `foot`, `md.obsidian.Obsidian`, `proton.vpn.app.gtk`, `Lucent-desktop`. Chromium and KeePassXC were not running; their classes follow Chromium's documented naming and are marked "expected" in the fixture. The default matcher needed no change.
- **Deviations:** (1) Focus is resolved by `j/activewindow` per event batch instead of an address → class cache (ADR-0016), because monitor and fullscreen are not in the events. (2) Reconnect after a Hyprland restart also works when `$HYPRLAND_INSTANCE_SIGNATURE` is stale (falls back to the newest live instance). (3) `focusedmon`, `fullscreen`, `movewindow*` also trigger a refresh. (4) I launched one Omarchy web app (Google Maps) on Nick's desktop to observe its class; my first attempt to close it used the old `hyprctl dispatch` syntax and was rejected, and the window was gone by my next check (I do not know whether Nick closed it). During the live test I also moved focus between Nick's existing foot and Brave windows with `hl.dsp.focus`; nothing was closed, moved or typed into. (5) Hyprland's request socket was not restarted, as required; the reconnect is tested with a real Unix socket server and a socketpair double.
- **Follow-ups:** Phase 07 wires `FocusWatcher` (notes added to its prompt). Phase 06 does not depend on this. `hyprctl dispatch` uses Lua syntax on this machine (`hl.dsp.focus({ window = "address:0x…" })`), noted for scripted tests in Phase 08.
- **Tests:** 692 passed (58 new: parser incl. commas and `>>` in titles, fixture stream, fullscreen modes, socket location and fallback, real-socket request, watcher coalescing, partial and oversized lines, hang-up and read-error reconnect, back-off 0.1 → 5 s and reset, not-running at start, request failure, stop, real Unix-socket reconnect, S1 `TitleGuard` over events and logs, error de-duplication, CLI `focus`). `focus.py` coverage 97 %. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` pass.
