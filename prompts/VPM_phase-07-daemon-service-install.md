# VPM Phase 07: Daemon wiring, control socket, systemd service, keybinding and install

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 04, 05, 06 · **Branch:** `phase-07-daemon-service-install` · **Gate:** review

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 A4, §2.2 R10, R11, R12, §2.3 S3, S5. Phase Log entries for Phases 04, 05 and 06. ADR-0005, ADR-0009. **Owner questions 1 (keybinding) and 4 (pause duration): ask Nick if still open (hands-off: block-with-question).** Read `/home/nick/Documents/04 Resources/OSMods/OSMODs README.md` and the Cursor Highlight write-up there before changing the host. The Brainstorm trace rows this phase fulfils or changes: B1.

## Goal
`vpn-monitor` runs at login as a systemd user service that wires focus + VPN into the engine and overlay, can be paused/resumed from a keybinding and the CLI, and installs and uninstalls cleanly, documented in the OSMods log.

## Tasks
> **Notes from Phase 05:** build the focus side with `FocusWatcher(GLibScheduler(), log=log)` and `start(callback)`; it delivers `FocusEvent("", "", "")` first (hide), then the initial state, and again "no focus" while Hyprland's socket is down. It never raises when Hyprland is not up yet (it retries with back-off and logs once). `vpn-monitor status` can show `watcher.last_focus`, `watcher.connected` and `watcher.reconnects`. The `vpn-monitor focus` CLI (`focus_row`, `format_focus` in `cli.py`) is the model for the "focused class + match" line.

1. `daemon.py`: build config → eventlog → engine → overlay; start focus watcher and VPN watcher on the GLib main loop; feed engine; tell the VPN watcher when a browser is focused (periodic re-check only then); apply decisions to the overlay; SIGTERM/SIGINT shut down cleanly (bar hidden); config reload on SIGHUP.
2. `control.py`: Unix socket `$XDG_RUNTIME_DIR/vpn-monitor/control.sock` (dir 0700, socket 0600, `SO_PEERCRED` uid check), line-based JSON commands `pause`, `resume`, `toggle`, `status`; anything else rejected and logged (S5). Single-instance guard (a second `run` exits with a clear message).
3. CLI: `run [--foreground]`, `pause`, `resume`, `toggle`, `status [--json]` (paused?, focused class + match, current reading with per-family reasons, indicator, uptime), `log [-f] [--events]`. `pause`/`resume` send a `notify-send` notification ("VPN Monitor paused" / "resumed").
4. Pause semantics per owner question 4 (default: until resume or next login, not persisted).
5. `packaging/systemd/vpn-monitor.service`: `PartOf=graphical-session.target`, `After=graphical-session.target`, `Restart=on-failure`, `RestartSec=2`; sandboxing that keeps Wayland/D-Bus working (e.g. `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ReadWritePaths=%S/vpn-monitor %t/vpn-monitor`, `PrivateTmp=yes`); check each option actually works with `systemd-analyze --user security` and record the score.
6. `scripts/install.sh` / `uninstall.sh`: symlink `~/.local/bin/vpn-monitor` (a wrapper that sets `LD_PRELOAD` if needed and runs the package from the repo with system python), install and `enable --now` the user unit, add the keybinding to `~/.config/hypr/bindings.lua` (re-check it is still free with `hyprctl binds -j`; back up to `bindings.lua.bak.vpn-monitor`; idempotent marker comments), `hyprctl reload`. Uninstall reverses every step and leaves the backup. Never touch `/usr/share/omarchy/`.
7. Live check with Nick: install, then switch between Brave, a web app and foot (expect blue/blue/none), then **ask Nick** to disconnect ProtonVPN (expect red within 2 s) and reconnect (expect blue), press the pause key (bar gone, notification), resume. Record timings from the JSONL log.
8. OSMods: create `/home/nick/Documents/04 Resources/OSMods/VPN Monitor.md` (what, why, exact paths, keybinding, how it survives Omarchy updates, undo = `scripts/uninstall.sh`, verified results) and update `OSMODs README.md` (at-a-glance table, section, "Where things live", "Last updated").

## Out of scope
Threat model, performance measurement campaign, licence audit (Phase 08); publication (Phase 09).

## Tests
Integration tests with fakes: full daemon pipeline (fake focus + fake VPN + recording sink) for focus switches, VPN drop, pause/resume, watcher crash → red; control-socket tests (permissions, peer uid, unknown command rejected); install/uninstall scripts run against a temp `HOME` (`HOME=$(mktemp -d)`) with `systemctl`/`hyprctl` stubbed.

## Acceptance criteria
- After `install.sh`, a fresh login (or `systemctl --user restart vpn-monitor`) shows the bar correctly in the live check; timings logged.
- `uninstall.sh` leaves no unit, symlink or keybinding behind (diff `bindings.lua` against the backup).
- OSMods write-up and README updated.

## Phase-specific docs
README (install, usage, uninstall, troubleshooting), SECURITY (control socket), `docs/VPM_ARCHITECTURE.md`, CHANGELOG, ADR-0009 Accepted (or superseded), OSMods write-up + `OSMODs README.md`. Owner questions 1 and 4 updated. Brainstorm trace B1 updated. Then the standard close-out checklist.

## Notes from Phase 03 (built interfaces you rely on)
- Build with `config = load_config()` (raises `ConfigError` naming the key; log `config.warnings`), `engine = Engine.from_config(config, time.monotonic)`, `log = EventLog(max_bytes=config.log.max_bytes, backup_count=config.log.backup_count)`.
- Every `on_*` / `tick` returns a `Decision` only when it changed: apply it to the overlay and `log.decision(d)`.
- After every input, (re)schedule **one** `GLib.timeout_add` at `engine.next_deadline()` (monotonic seconds; `None` = cancel) and call `engine.tick()` when it fires. Without it a stuck VPN watcher would leave blue on screen (ADR-0013). Call `vpn_source.set_active(engine.active)` whenever `active` changes.
- Pause: `engine.on_pause(True/False)`; `config.pause.auto_resume_minutes` (0 = until resume or next login, owner question 4).
- Status output can use `engine.decision` (indicator, monitor, reason, inputs) and `engine.paused`.

## Notes from Phase 04 (VPN source)
- Build the VPN source with `RouteWatcher(config, GLibScheduler(), log=log)` (`vpn_monitor.vpn`, `vpn_monitor.mainloop`); `start(cb)` with a callback that feeds `engine.on_vpn(reading)` and applies the result, `set_active(engine.active)` on every change of `active`, `stop()` at shutdown (terminates its `ip monitor` child). It logs `reading` and `vpn_watcher` events itself; the daemon only logs decisions.
- `vpn-monitor probe` already exists in `cli.py` (exit 0/1/3, 2 = config error); keep it when filling in the other subcommands. `status` can show `watcher.last_reading`, `last_trigger`, `watcher_up`.
- Probes run synchronously on the main loop (~12 ms, 1 s timeout per `ip` call, ADR-0007/0012).

## Notes from Phase 06 (overlay; 2026-11-19 09:18 CST)
- Call `vpn_monitor.overlay.ensure_layer_shell(argv)` at the top of `run`, **before anything imports Gtk** (it re-execs once with `LD_PRELOAD=libgtk4-layer-shell.so`; without it there is no layer surface). In the systemd unit you may instead set `Environment=LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`; the re-exec then does nothing.
- Build the sink with `GlowOverlay(config.appearance, log=log)`; it raises `RuntimeError` if layer shell is unavailable (log it and exit non-zero; do not fall back to a normal window). `apply(decision)` is idempotent and never raises; `close()` on shutdown removes the bars.
- `GtkBackend` sets `GSK_RENDERER=cairo` unless the environment sets it (ADR-0017); keep that in the unit.
- On SIGHUP, appearance changes need a new `GlowOverlay` (close the old one first); the look is read once.
- `vpn-monitor preview` already exists in `cli.py`; keep it.
