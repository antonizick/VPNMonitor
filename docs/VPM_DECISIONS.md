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
| ADR-0007 | 2026-11-18 21:53 CST | Event-driven VPN detection with a periodic re-check only while a browser is focused; event source `ip monitor route rule link` | Accepted (2026-11-18 22:55 CST) | 04 |
| ADR-0008 | 2026-11-18 21:53 CST | MIT licence; private GitHub repo; going public is the owner's call | Accepted | 00 |
| ADR-0009 | 2026-11-18 21:53 CST | Pause keybinding SUPER+ALT+SHIFT+V (SUPER+ALT+V is taken) | Proposed | 07 |
| ADR-0010 | 2026-11-18 21:53 CST | Privacy: never read/log window titles; no external network calls | Accepted | 00 |
| ADR-0011 | 2026-11-18 22:19 CST | Sources and sinks use a callback-style Protocol (`start(callback)` / `stop()`), not async iterators | Accepted | 02 |
| ADR-0012 | 2026-11-18 22:19 CST | Single GLib main loop on the main thread; all callbacks run on it; no threads in the core | Accepted | 02 |
| ADR-0013 | 2026-11-18 22:29 CST | Engine rules: blue gated by one check (fresh + route-consistent VPN reading), optional blue confirmation, red never delayed, deadline API | Accepted | 03 |
| ADR-0014 | 2026-11-18 22:29 CST | Event log: two size-rotated files, flat JSONL schema, `TitleGuard` for S1 tests | Accepted | 03 |
| ADR-0015 | 2026-11-18 22:55 CST | Classify interfaces by kernel link kind (`wireguard`/`tun` = VPN, `dummy` = blocked) plus name globs, not via `nmcli` | Accepted | 04 |
| ADR-0016 | 2026-11-19 08:37 CST | Focus watcher asks `j/activewindow` once per event batch instead of keeping an address → class cache; titles never leave the parser | Accepted | 05 |

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
**Status change (2026-11-18 22:55 CST, Phase 04): Accepted, event source chosen.** Options for the event source: (a) an `ip monitor` subprocess read line by line through `GLib` fd watches; (b) NetworkManager D-Bus `StateChanged` / `PropertiesChanged` via Gio; (c) both. Chosen: (a), as `ip monitor route rule link`. Reasons: the verdict is computed from the kernel routing table, so kernel route/rule/link changes are the events that matter, and they cover changes NetworkManager does not make (`wg-quick`, Tailscale's table 52 and its exit-node switch, the Proton kill-switch dummies). It works without NetworkManager; it costs one idle process blocked on netlink (no CPU between events); no D-Bus signal parsing or `gi` dependency in the detector. `rule` is added to the prompt's `route link` because ProtonVPN switches policy rules (fwmark rule, table 245447468). Lines are not parsed, only counted: a burst is coalesced into one probe 200 ms after its first line (leading-window debounce, so a continuous storm cannot postpone the probe), and the link-kind cache is dropped. The monitor is restarted with exponential back-off (0.5 s doubling to 30 s, reset after a 30 s run); while it has been down for more than `max_reading_age_s` a `VPN` reading is downgraded to `UNKNOWN` (red), since a drop could no longer be seen in time; negative readings pass through. Measured on the reference machine (2026-11-18 22:55 CST): ProtonVPN disconnect reported as NO_VPN 228 ms after the first route event, reconnect reported as VPN 222 ms after it (budget R13: < 2 s). Probes run synchronously on the main loop (≈ 12 ms for the three `ip` calls, 1 s timeout each), as ADR-0012 allows.

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

## ADR-0013: Engine decision rules and hysteresis
**Recorded.** 2026-11-18 22:29 CST (Phase 03). Status: Accepted.
**Context.** The engine is where a false blue (spec S6) would be born. The Phase 03 prompt asks for optional `blue_confirm_ms` and `red_confirm_ms` (both default 0) and says red is never delayed. A delay before red means the bar stays blue after a NO_VPN or UNKNOWN reading has arrived, which is exactly a false blue.
**Options considered.** (a) Implement both delays symmetrically; (b) implement `blue_confirm_ms` only and keep `red_confirm_ms` as a key that must be 0; (c) drop `red_confirm_ms` entirely.
**Decision.** (b). `blue_confirm_ms` (0–10 000, default 0) makes a positive reading hold continuously before blue; while it is pending the bar is red, so a flapping VPN shows red. The timer starts the first time a positive reading is observed and restarts whenever a non-positive state is observed, including a gap in which the previous reading silently went stale. `red_confirm_ms` is accepted only as 0; any other value is a `ConfigError` that names S6, so the rule is explicit in the config rather than silently missing. Further rules:
- **One gate for blue.** `engine.reading_problem()` is the only path to blue: state `VPN`, age ≤ `max_reading_age_s` (default 10 s), not dated more than 1 s in the future, not NaN, **and** the per-family routes agree (at least one family `ROUTED` via a VPN, none `ROUTED` outside one, none `ERROR`). The route check is defence in depth against a detector bug; it also makes "kill switch engaged, no tunnel" (everything blocked) red, as R4 requires.
- **Monitor.** The bar goes to the focused window's monitor; if that is empty or no longer in the monitor list, to the monitor flagged focused, else the first known monitor; with no monitor at all the decision is HIDDEN (nothing could be drawn).
- **Change detection.** A Decision is returned only when `(indicator, monitor, reason)` changes; `inputs` (reading age, routes) do not count, so re-checks every 5 s do not flood the overlay or the log.
- **Time.** The clock is injected (`time.monotonic` in the daemon). `next_deadline()` gives the one moment the decision can change without new input (confirmation complete, or the reading going stale); it is `None` while no bar is shown, so nothing is scheduled while idle (R13). `active` tells the daemon when VPN re-checks are wanted (ADR-0007).
**Consequences.** Blue can lag by up to `blue_confirm_ms`; red never lags. Phase 07 must schedule a GLib timeout at `next_deadline()` after every input, or a stuck VPN watcher would leave blue on screen until the next event. Phase 04's `VpnReading` must fill `routes` consistently with `state`, or the engine shows red with "VPN reading contradicts its routes".

## ADR-0014: Event-log format and title guard
**Recorded.** 2026-11-18 22:29 CST (Phase 03). Status: Accepted.
**Context.** Spec R11 asks for a human log and a JSONL event log of every change with its inputs and reason; S1 forbids titles in either.
**Options considered.** (a) Two stdlib `RotatingFileHandler` files with a flat schema; (b) one JSONL file and render the human view on demand (`vpn-monitor log`); (c) the systemd journal only.
**Decision.** (a). `$XDG_STATE_HOME/vpn-monitor/` (default `~/.local/state/vpn-monitor/`, directory forced to 0700) holds `vpn-monitor.log` and `events.jsonl`, each rotated by size (`[log] max_bytes`, default 1 MB, `backup_count` 3). One JSON object per line with the fixed keys `ts` (wall clock, ISO 8601 with UTC offset, milliseconds), `event`, `level`, `decision` (`hidden`/`red`/`blue` or null), `monitor`, `reason` and `inputs`, a flat `str -> str` map (engine inputs: `class`, `match`, `monitor`, `fullscreen`, `paused`, `vpn_state`, `reading_age_s`, `routes`, `reading_reason`). Each `EventLog` uses its own uniquely named, non-propagating loggers, so nothing leaks to the root logger or between instances. `TitleGuard` holds titles that must never be logged and raises `TitleLeakError` (before the write) if any string in a record, keys included, contains one; tests and later phases (05: focus parser) pass it to `EventLog(guard=…)`.
**Consequences.** Log files are created with the process umask (only the directory is 0700); that is enough since they hold only classes, interface names and reasons. The window class of a web app contains its host (`brave-<host>__-Default`); that is the class, not the title, and is logged (S1 permits classes). `vpn-monitor log --events` (Phase 07) can tail `events.jsonl` directly.

## ADR-0015: Interface classification by kernel link kind
**Recorded.** 2026-11-18 22:55 CST (Phase 04). Status: Accepted.
**Context.** Spec R3 and the Phase 04 prompt classify the egress interface as VPN if NetworkManager reports its device type as `wireguard`, `tun` or `vpn` (via `nmcli`), or if its name matches a configured glob; leak guards are named in config. The owner wants the tool to be a generic VPN detector, not a ProtonVPN one. On the reference machine `nmcli` and the kernel agree: `proton0` wireguard, `tailscale0` tun, `ipv6leakintrf0` dummy.
**Options considered.** (a) `nmcli -t -f DEVICE,TYPE device` as the prompt says; (b) the kernel's own link kind from `ip -d -j link show` (`linkinfo.info_kind`); (c) both.
**Decision.** (b), plus the name globs. `wireguard` and `tun` (which covers tap) count as a VPN whatever the interface is called; any `dummy` device counts as *blocked*, because the dummy driver discards every packet, so a route into one is a kill switch or leak guard and cannot leak; names in `vpn.leak_guard_interfaces` (defaults: ProtonVPN's `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*`, read from the installed client's source) count as blocked too. Unencrypted tunnels (`sit`, `gre`, `ipip`) and everything else are ordinary interfaces. NetworkManager's `vpn` type names a connection, not a device (an NM OpenVPN connection's device is `tun`), so nothing is lost. The kinds are cached and reloaded on every change burst and for any interface not in the cache. If they cannot be read, only the name globs apply. An unclassified VPN can then show red, but a non-VPN can never show blue.
**Consequences.** Works with WireGuard (`wg-quick`, NM, Mullvad, Proton), OpenVPN, Tailscale/Headscale exit nodes and any tun-based client, with or without NetworkManager, and without per-provider config. Policy-based IPsec without its own interface (classic strongSwan/libreswan) routes through the physical interface and therefore shows red (documented in the README limits; a user can add a glob for an `xfrm`/`ipsec` interface). A tun device used by a non-VPN tool (a tun2socks proxy) would count as a VPN; that is a user choice of software, noted in the README.

## ADR-0016: Focus watcher resolves focus with `j/activewindow`, not an address cache
**Recorded.** 2026-11-19 08:37 CST (Phase 05). Status: Accepted.
**Context.** The Phase 05 prompt suggests mapping address → class/monitor through a small cache refreshed from `j/clients` when an address is unknown. Hyprland's focus events carry only the class (v1, with the title attached) or the address (v2). The monitor and fullscreen state, which the engine needs, are in neither, and both can change without a focus event (a window moved to another monitor, `fullscreen>>`).
**Options considered.** (a) Address cache refreshed from `j/clients`, with the event's class and monitor events patched in; (b) ask `j/activewindow` once after each batch of relevant events and keep only a monitor id → name table (`j/monitors`, refreshed when a monitor event arrives or an id is unknown); (c) trust the `activewindow>>class,title` line alone.
**Decision.** (b). Events say *that* focus may have changed; the request says *to what*. A burst of lines read together costs one request (measured 2 to 7 ms from receipt to delivery on the reference machine, against the 150 ms budget), and a `FocusEvent` is delivered only when it differs from the last. (a) has to keep window state in step with a stream that does not describe every change; (c) cannot tell the monitor. If a request fails, the bar is hidden (`FocusEvent("", "", "")`) and the stream is reopened, so a failure can never leave a stale browser focus on screen. Privacy: `parse_event_line` keeps only the class (v1), address or monitor name; every title-bearing event (`windowtitle`, `windowtitlev2`, `openwindow`) is reduced to its name; JSON replies are read field by field, so `title` and `initialTitle` are never copied, and parse errors never quote the reply (spec S1). The event socket is found through `$HYPRLAND_INSTANCE_SIGNATURE`, falling back to the newest live instance, so a Hyprland restart is survived without restarting the daemon.
**Consequences.** One small blocking request (0.5 s timeout) on the main loop per focus change; acceptable because the socket is local and the answer is immediate. `j/clients` is used only by `HyprlandClient.all_windows()` (diagnostics, class fixtures). Reconnect back-off is 0.1 s doubling to 5 s, reset after a connection that lasted 10 s. Phase 07 only has to construct `FocusWatcher(GLibScheduler(), log=log)`.
