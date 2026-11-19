# VPM: Architecture Decision Log

Lightweight ADRs. Append new decisions at the bottom, and never rewrite history: to reverse a decision, add a new entry that supersedes the old one. Every phase that makes a non-trivial technical choice adds an entry here. Timestamps are `YYYY-MM-DD HH:MM TZ` from `date '+%Y-%m-%d %H:%M %Z'`; a status change (for example `Proposed` → `Accepted`, or `Superseded by ADR-00NN`) is noted in the entry with its own timestamp.

| ID | Timestamp | Decision | Status | Phase |
|---|---|---|---|---|
| ADR-0001 | 2026-11-18 21:53 CST | Project prefix `VPM`, repo `/home/nick/Work/VPNMonitor` | Accepted | 00 |
| ADR-0002 | 2026-11-18 21:53 CST | Fixed red/blue steady glow bar at the bottom edge while a browser is focused | Accepted | 00 |
| ADR-0003 | 2026-11-18 21:53 CST | "On a VPN" = internet routes leave via a VPN interface; fail-safe red | Accepted | 00 |
| ADR-0004 | 2026-11-18 21:53 CST | Browsers include Omarchy web apps; configurable matcher | Accepted | 00 |
| ADR-0005 | 2026-11-18 21:53 CST | Always-on systemd user service with a pause/resume keybinding | Accepted | 00 |
| ADR-0006 | 2026-11-18 21:53 CST | Python on the system interpreter + PyGObject/gtk4-layer-shell; uv for dev tools | Accepted (2026-11-18 22:19 CST) | 02 |
| ADR-0007 | 2026-11-18 21:53 CST | Event-driven VPN detection with a periodic re-check only while a browser is focused | Proposed | 04 |
| ADR-0008 | 2026-11-18 21:53 CST | MIT licence; private GitHub repo; going public is the owner's call | Accepted | 00 |
| ADR-0009 | 2026-11-18 21:53 CST | Pause keybinding SUPER+ALT+SHIFT+V (SUPER+ALT+V is taken) | Proposed | 07 |
| ADR-0010 | 2026-11-18 21:53 CST | Privacy: never read/log window titles; no external network calls | Accepted | 00 |
| ADR-0011 | 2026-11-18 22:19 CST | Sources and sinks use a callback-style Protocol (`start(callback)` / `stop()`), not async iterators | Accepted | 02 |
| ADR-0012 | 2026-11-18 22:19 CST | Single GLib main loop on the main thread; all callbacks run on it; no threads in the core | Accepted | 02 |

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

**Verification (2026-11-18 22:19 CST, Phase 02): Accepted.** On the reference machine (Python 3.14.8, `python-gobject` 3.58.1, `gtk4-layer-shell` 1.3.0), `uv venv --system-site-packages && uv sync` followed by `uv run python -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Gtk4LayerShell','1.0')"` works **without** `LD_PRELOAD`. Layer-shell library: `/usr/lib/libgtk4-layer-shell.so` (symlink to `libgtk4-layer-shell.so.1.3.0`). Phase 06 re-checks whether `LD_PRELOAD` is needed when a real window is created (gtk4-layer-shell must be linked before libwayland-client in some setups) and records it there. Two findings: (1) without a pin, `uv` picks a uv-managed Python (3.13) that cannot see the system `gi`, so `pyproject.toml` sets `[tool.uv] python-preference = "only-system"`; (2) CI has no PyGObject, so it overrides this with `UV_PYTHON_PREFERENCE=managed` and the `gi`/`wayland` tests skip.

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

## ADR-0011: Source and sink Protocol style
**Recorded.** 2026-11-18 22:19 CST (Phase 02). Status: Accepted.
**Context.** Phases 04, 05 and 06 are built in parallel against shared interfaces, so the interface must be fixed now. The daemon runs on a GLib main loop (ADR-0012).
**Options considered.** (a) Callback style: `FocusSource.start(callback)`, `stop()`; (b) `async for` over an async iterator, which needs an asyncio loop bridged to GLib; (c) a GLib signal-based GObject base class, which drags `gi` into the pure core and tests.
**Decision.** (a). `FocusSource` and `VpnSource` deliver `FocusEvent` / `VpnReading` to a callback on the main-loop thread, `start` also delivers the initial state, `VpnSource.set_active(bool)` switches the periodic re-check on only while a browser is focused (ADR-0007), and `IndicatorSink.apply(Decision)` / `close()` renders. The Protocols live in `model.py` and are `runtime_checkable`.
**Consequences.** Fakes are trivial and synchronous (`fakes.py`), so engine and wiring tests need no event loop. Real sources wrap `GLib.io_add_watch`, `GLib.timeout_add` or `Gio` signals themselves. Errors must not escape a source: a failure becomes an UNKNOWN `VpnReading` or a logged event.

## ADR-0012: Event-loop and threading model
**Recorded.** 2026-11-18 22:19 CST (Phase 02). Status: Accepted.
**Context.** GTK4 requires its widgets to be used from one thread; the sources (a Unix socket, route events, timers) are all I/O-bound and low-rate.
**Options considered.** (a) One GLib main loop on the main thread, sources integrated via `GLib.io_add_watch`, `GLib.timeout_add` and `Gio`; (b) asyncio with a GLib bridge (extra dependency or glue); (c) worker threads feeding the UI through `GLib.idle_add`.
**Decision.** (a). Everything, including the engine, runs on the main thread inside the GLib main loop. A subprocess (for example `ip monitor`) is read through `GLib.io_add_watch` on its pipe, never a blocking thread. If a probe ever must block, it runs in a short-lived thread that hands its result back with `GLib.idle_add`, and that is documented where it happens.
**Consequences.** No locks in the core, deterministic tests, ~0 % idle CPU (nothing runs between events). A slow call on the main thread would stall the bar, so every probe has a timeout and falls back to UNKNOWN (red).
