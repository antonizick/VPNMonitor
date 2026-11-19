# VPM: Architecture Decision Log

Lightweight ADRs. Append new decisions at the bottom, and never rewrite history: to reverse a decision, add a new entry that supersedes the old one. Every phase that makes a non-trivial technical choice adds an entry here. Timestamps are `YYYY-MM-DD HH:MM TZ` from `date '+%Y-%m-%d %H:%M %Z'`; a status change (for example `Proposed` → `Accepted`, or `Superseded by ADR-00NN`) is noted in the entry with its own timestamp.

| ID | Timestamp | Decision | Status | Phase |
|---|---|---|---|---|
| ADR-0001 | 2026-11-18 21:53 CST | Project prefix `VPM`, repo `/home/nick/Work/VPNMonitor` | Accepted | 00 |
| ADR-0002 | 2026-11-18 21:53 CST | Fixed red/blue steady glow bar at the bottom edge while a browser is focused | Accepted | 00 |
| ADR-0003 | 2026-11-18 21:53 CST | "On a VPN" = internet routes leave via a VPN interface; fail-safe red | Accepted | 00 |
| ADR-0004 | 2026-11-18 21:53 CST | Browsers include Omarchy web apps; configurable matcher | Accepted | 00 |
| ADR-0005 | 2026-11-18 21:53 CST | Always-on systemd user service with a pause/resume keybinding | Accepted | 00 |
| ADR-0006 | 2026-11-18 21:53 CST | Python on the system interpreter + PyGObject/gtk4-layer-shell; uv for dev tools | Proposed | 02 |
| ADR-0007 | 2026-11-18 21:53 CST | Event-driven VPN detection with a periodic re-check only while a browser is focused | Proposed | 04 |
| ADR-0008 | 2026-11-18 21:53 CST | MIT licence; private GitHub repo; going public is the owner's call | Accepted | 00 |
| ADR-0009 | 2026-11-18 21:53 CST | Pause keybinding SUPER+ALT+SHIFT+V (SUPER+ALT+V is taken) | Proposed | 07 |
| ADR-0010 | 2026-11-18 21:53 CST | Privacy: never read/log window titles; no external network calls | Accepted | 00 |

---

## ADR-0001: Project prefix and repository
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** The method needs a 2–4 character project code; the owner's brainstorm file was already named `VPM_Brainstorming.md`.
**Options considered.** `VPM` (from the file name), `VPN`, `VM`.
**Decision.** `VPM`. Repo `/home/nick/Work/VPNMonitor` (the folder holding the brainstorm), branch `main`. Checked unique against the work root and `02 Projects` (existing: MM3, CL, OCC, LU2, NUN, OWH, P11, PHX, TDB, YTPL2).
**Consequences.** Project documents are `VPM_*`; the vault note is `VPM Implementation Plan.md`.

## ADR-0002: Indicator look and behaviour
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** The brainstorm asks for a glowing red line (no VPN) and a glowing blue bar (VPN) at the bottom of the screen while a browser has focus.
**Options considered.** (a) red/blue steady glow while focused; (b) red steady, blue only briefly on focus then fade; (c) red only.
**Decision.** (a), owner's choice. Fixed colours independent of the Omarchy theme, so the meaning never changes. Shown on the monitor of the focused browser for as long as it has focus. Exact thickness, glow and colours are tuned at the Phase 06 review (owner question 2).
**Consequences.** The blue bar is visible whenever browsing safely; the overlay must be thin and cheap. No continuous animation.

## ADR-0003: Definition of "on a VPN"
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** The machine has ProtonVPN (`proton0`) and Tailscale (`tailscale0`) up at once; an "interface is up" test would show blue while traffic might leave unprotected.
**Options considered.** (a) the internet route leaves via a VPN interface; (b) ProtonVPN connection active; (c) any VPN interface up.
**Decision.** (a), owner's choice. Route probes for IPv4 and IPv6 (spec R3); blue only if every family is routed via VPN or blocked; anything unknown is red (R4).
**Consequences.** Tailscale mesh alone is red; a Tailscale exit node is blue. DNS leaks are not detected (owner question 5, deferred). Phase 04 verifies the leak-guard and policy-routing behaviour on the machine.

## ADR-0004: What counts as a browser
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** Omarchy web apps are Chromium/Brave `--app` windows with their own window classes.
**Options considered.** (a) browsers plus web apps; (b) full browsers only; (c) Brave only.
**Decision.** (a), owner's choice. A configurable matcher: exact classes and regexes, defaults covering Brave, Chromium, Chrome, Firefox family, Vivaldi, Zen and Omarchy web-app classes.
**Consequences.** Phase 05 records the real classes observed and tunes the defaults.

## ADR-0005: Run mode
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** A safety indicator only helps if it is running; the owner's other overlays are off-by-default toggles.
**Options considered.** (a) always-on user service + pause key; (b) off by default, toggle key.
**Decision.** (a), owner's choice. systemd user unit `vpn-monitor.service` started with the graphical session; event-driven, near-zero idle cost.
**Consequences.** Needs a control socket and a keybinding (ADR-0009); install/uninstall scripts and an OSMods write-up.

## ADR-0006: Language and toolkit
**Recorded.** 2026-11-18 21:53 CST (Phase 00). Status: Proposed, Phase 02 verifies.
**Context.** The overlay needs `wlr-layer-shell`; the owner's Cursor Highlight already proves Python + GTK4 + gtk4-layer-shell works here.
**Options considered.** Python + PyGObject (pacman); Quickshell (QML); Go/Rust with layer-shell bindings.
**Decision.** Python ≥ 3.12 on the system interpreter, PyGObject and gtk4-layer-shell from pacman, no runtime pip dependencies; dev tools via `uv` in a `--system-site-packages` venv.
**Consequences.** Dependency on pacman packages is documented in README; CI skips GI tests where `gi` is missing.

## ADR-0007: Detection trigger strategy
**Recorded.** 2026-11-18 21:53 CST (Phase 00). Status: Proposed, Phase 04 picks the event source.
**Context.** A VPN drop must show within 2 s, but idle cost must be near zero.
**Options considered.** Pure polling; `ip -j monitor route link` subprocess; NetworkManager D-Bus signals; a combination.
**Decision.** Event-driven re-evaluation (event source chosen in Phase 04) plus a periodic re-check (default 5 s) only while a browser is focused.
**Consequences.** Missed events are bounded by the re-check; no work at all while no browser is focused.

## ADR-0008: Licence and repository visibility
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** The owner's other repos are MIT; the method requires a GitHub-ready repo.
**Options considered.** MIT; Apache-2.0; no licence.
**Decision.** MIT. Phase 01 creates `antonizick/VPNMonitor` as a **private** GitHub repo (standing git authority). Making it public or releasing is the owner's call in Phase 09 (owner question 6).
**Consequences.** THIRD_PARTY_NOTICES lists GTK4, gtk4-layer-shell and PyGObject as system dependencies (not bundled).

## ADR-0009: Pause/resume keybinding
**Recorded.** 2026-11-18 21:53 CST (Phase 00). Status: Proposed, owner question 1, confirmed in Phase 07.
**Context.** SUPER+ALT+V is already bound (Prometheus: cycle verbosity).
**Options considered.** SUPER+ALT+SHIFT+V (free); another free SUPER+ALT letter (E, Q, R, U, Y, Z).
**Decision.** SUPER+ALT+SHIFT+V, unless the owner picks another.
**Consequences.** Phase 07 re-checks it is still free before binding.

## ADR-0010: Privacy baseline
**Recorded.** 2026-11-18 21:53 CST (Phase 00)
**Context.** Hyprland focus events carry window titles (page titles, URLs); some VPN checks call external IP services.
**Options considered.** Log everything for debugging; log class only.
**Decision.** Read and log only window class/address, never titles; never contact external hosts (spec S1, S2).
**Consequences.** Debugging relies on class names and route data; tests assert titles never reach logs.
