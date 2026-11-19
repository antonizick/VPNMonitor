# VPM Phase 07: Daemon wiring, control socket, systemd service, keybinding and install

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 04, 05, 06 · **Branch:** `phase-07-daemon-service-install` · **Gate:** review

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 A4, §2.2 R10, R11, R12, §2.3 S3, S5. Phase Log entries for Phases 04, 05 and 06. ADR-0005, ADR-0009. **Owner questions 1 (keybinding) and 4 (pause duration): ask Nick if still open (hands-off: block-with-question).** Read `/home/nick/Documents/04 Resources/OSMods/OSMODs README.md` and the Cursor Highlight write-up there before changing the host. The Brainstorm trace rows this phase fulfils or changes: B1.

## Goal
`vpn-monitor` runs at login as a systemd user service that wires focus + VPN into the engine and overlay, can be paused/resumed from a keybinding and the CLI, and installs and uninstalls cleanly, documented in the OSMods log.

## Tasks
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
