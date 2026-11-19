# VPM Phase 05: Hyprland focus watcher

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 03 · **Branch:** `phase-05-hyprland-focus-watcher` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 A3, §2.2 R6, R7, R13 and §2.3 S1. Phase Log entries for Phases 02 and 03. ADR-0004, ADR-0010. The Brainstorm trace rows this phase fulfils or changes: B2.

## Goal
`focus.py` turns Hyprland's event stream into `FocusEvent`s (class, address, monitor, fullscreen; never the title) quickly and reliably, including at start-up and across Hyprland restarts.

## Tasks
1. Locate sockets from `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/` (`.socket.sock` for requests, `.socket2.sock` for events); exit with a clear "Hyprland not running" error if they are unset or missing.
2. Request client: `j/activewindow`, `j/monitors`, `j/clients` over `.socket.sock` (stdlib `socket`, local Unix only). Strip the `title` and `initialTitle` fields **at the parser** so they never reach a `FocusEvent` or a log (S1).
3. Event reader on `.socket2.sock`: handle `activewindow>>`, `activewindowv2>>`, `focusedmon>>`, `fullscreen>>`, `closewindow>>`, `monitoradded>>`/`monitoraddedv2>>`, `monitorremoved>>`. Map address → class/monitor via a small cache refreshed with `j/clients` when an address is unknown. Note `activewindow>>class,title`: split on the first comma only and discard the title.
4. Initial state on start and after reconnect; reconnect with exponential back-off (max 5 s) when the socket closes; emit "no focus" (engine hides the bar) while disconnected.
5. Integrate with the GLib main loop chosen in Phase 02 (e.g. `GLib.io_add_watch` on the socket fd) without busy-waiting.
6. Observe real classes on the machine: Brave, Chromium, a couple of Omarchy web apps (`omarchy-launch-webapp`), and non-browsers (foot, Obsidian, KeePassXC). Record them (class only) in `tests/fixtures/focus/` and adjust the Phase 03 matcher defaults if needed (ADR if they change).
7. A `vpn-monitor focus --watch` debug subcommand printing class, matched rule and monitor per event (no titles).

## Out of scope
VPN detection, overlay drawing, daemon wiring.

## Tests
Parser tests over recorded event lines (including titles with commas and `>>` in them, which must be discarded safely), cache refresh, reconnect with a fake socket server in a temp dir, the S1 assertion (no title text in any emitted object or log line).

## Acceptance criteria
- On the reference machine, switching between Brave, a web app and foot prints the right matches within 150 ms (measured from event receipt).
- Restarting the watcher's socket (simulated) reconnects without a crash; Hyprland itself is not restarted.

## Phase-specific docs
`docs/VPM_ARCHITECTURE.md` (focus section, event table), README (supported browsers, how to add a class), CHANGELOG. Brainstorm trace B2 updated. Then the standard close-out checklist.

## Notes from Phase 03 (built interfaces you rely on)
- "No focus" is `FocusEvent("", "", "")`: the engine hides the bar for an empty class.
- The matcher is `vpn_monitor.browsers.BrowserMatcher` (`DEFAULT_CLASSES`, `DEFAULT_PATTERNS`, `match(cls) -> MatchResult(matched, rule)`; regexes use `re.fullmatch`). Record the real classes you observe and adjust the defaults there and in `config/config.example.toml` (a test checks the two agree).
- For the title test, register the titles of your fake socket2 lines in `vpn_monitor.eventlog.TitleGuard` and pass it to `EventLog(guard=…)`; it raises `TitleLeakError` if a title reaches a record.
- If the monitor name is unknown, send `monitor=""`: the engine falls back to the focused monitor from `on_monitors`, else the first known one.
