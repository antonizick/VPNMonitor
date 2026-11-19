# VPM: VPN Monitor Specification

> **Amendments override earlier sections.** Section 2 (Amendments) is authoritative wherever it conflicts with section 1.

**Source:** `VPM_Brainstorming.md` (repo root; also visible in the vault as `02 Projects/Work/VPNMonitor/VPM_Brainstorming.md`). **Planning session:** Phase 00, 2026-11-18 21:53 CST.

## 1. Original brainstorm (verbatim, formatting fixed only)

**2026-11-18 21:30 CST**

> It would be technically feasible too Add functionality to the operating system where when I have a browser with focus, if the operating system is not on a VPN, then there will be a visual cue, probably a glowing lid line at the bottom of the screen to indicate that there is no VPN active. Likewise, when the browser has to focus, if there is a VPN active, there should be a glowing blue bar at the bottom of the screen. Would this be technically feasible?

(Dictation reading confirmed by the owner: "glowing lid line" means a glowing **red** line; "has to focus" means "has focus".)

---

## 2. Amendments (v1, 2026-11-18 21:53 CST)

These amendments supersede conflicting text in the earlier sections. Each amendment that records a decision has an entry in `docs/VPM_DECISIONS.md`.

### 2.1 Decisions confirmed by the project owner
| ID | Topic | Decision |
|---|---|---|
| A1 | Indicator look and behaviour | A thin glowing bar along the **bottom edge** of the monitor that shows the focused browser. **Red = no VPN, blue = VPN.** Fixed colours (not the Omarchy theme), so the meaning never changes with a theme switch. Steady glow, shown for as long as a browser window has focus; hidden otherwise. (ADR-0002) |
| A2 | What "on a VPN" means | **Traffic actually routed through a VPN.** Blue only if the route to the public internet leaves through a VPN interface (ProtonVPN `proton0`, any NetworkManager VPN/WireGuard connection, a Tailscale *exit node*). Tailscale mesh alone does **not** count. (ADR-0003) |
| A3 | What counts as a browser | Full browsers (Brave, Chromium, Chrome, Firefox family, Vivaldi, Zen…) **plus Omarchy web-app windows** (`--app` windows of Brave/Chromium), since they are browser traffic too. The list is configurable. (ADR-0004) |
| A4 | Run mode | **Always on:** a systemd user service started at login, event-driven (near-zero idle CPU), plus a keybinding to pause and resume it. (ADR-0005) |
| A5 | Project prefix | `VPM` (taken from the brainstorm file name `VPM_Brainstorming.md`). Repo `/home/nick/Work/VPNMonitor`. (ADR-0001) |

### 2.2 Technical refinements
- **R1 Feasibility (answer to the brainstorm's question).** Yes, it is feasible with parts already on the reference machine: Hyprland's event socket (`.socket2.sock`) announces every focus change with the window class; the kernel routing table (and NetworkManager) shows whether internet traffic leaves via a VPN interface; a click-through `wlr-layer-shell` surface (GTK4 + `gtk4-layer-shell`, the same stack as the owner's Cursor Highlight tool) can draw a glowing bar above all windows. Verified during planning: `ip route get 1.1.1.1` → `dev proton0` while ProtonVPN is up; `brave-browser` window class; Hyprland 0.56.2; `gtk4-layer-shell`, `python-gobject` and Python 3.14 installed.
- **R2 Architecture: three inputs, one pure decision.** A *focus watcher* (Hyprland IPC) and a *VPN detector* (routes) feed observations into a pure *state engine* that decides `HIDDEN | RED | BLUE` per monitor; an *overlay* only renders that decision. The engine has no I/O, so it is fully unit-tested with fakes. (Phase 03)
- **R3 VPN test is route-based.** For each probe destination (default IPv4 `1.1.1.1` and IPv6 `2606:4700:4700::1111`, configurable) resolve the route the *current user's* traffic would take (`ip -j route get`, which honours policy rules, fwmarks and per-uid rules as ProtonVPN uses them). Classify the egress interface as VPN if NetworkManager reports it as a `wireguard`, `tun` or `vpn` device, or it matches configurable name patterns (`proton*`, `wg*`, `tun*`, `tailscale*`, `nordlynx`, `mullvad*`). **Blue requires every probe family to be either routed via a VPN interface or blocked** (unreachable, blackholed or routed to a leak-guard dummy such as ProtonVPN's `ipv6leakintrf0`); an IPv4-via-VPN / IPv6-via-Wi-Fi split is **red** (leak). The exact leak-guard detection is verified on the machine in Phase 04. (ADR-0003)
- **R4 Fail-safe: never a false blue.** Any unknown, error, timeout or stale reading resolves to **red** while a browser is focused. Blue is shown only from a fresh, positive reading. Kill switch engaged with no tunnel (no internet at all) is red.
- **R5 Event-driven with a safety re-check.** Re-evaluate on route/link change events (`ip -j monitor route link` or NetworkManager D-Bus signals; Phase 04 picks one and records an ADR) and on every focus change, plus a periodic re-check (default 5 s, configurable) while a browser is focused only. No polling while no browser is focused. (ADR-0007)
- **R6 Focus details.** Use `activewindow`/`activewindowv2`, `focusedmon`, `monitoradded`/`monitorremoved`, `fullscreen` and `closewindow` events; query the initial state (`j/activewindow`, `j/monitors`) at start-up and after reconnect. Reconnect with back-off when Hyprland restarts. The bar appears on the focused window's monitor only. (Phase 05)
- **R7 Web-app matching.** Omarchy web apps are Chromium/Brave `--app` windows whose class differs from the browser's (e.g. `brave-<host>__-Default`, `chrome-<host>__-Default`). Default matcher: a list of exact classes plus regexes; Phase 05 records the real classes observed on the machine.
- **R8 Overlay.** GTK4 + `gtk4-layer-shell` via PyGObject, layer `OVERLAY`, anchored bottom/left/right, exclusive zone 0 (never pushes windows), keyboard interactivity `NONE`, empty input region (click-through). One surface per monitor, rebuilt on monitor changes (a layer surface is bound to one output). Draw with cairo: a core line plus a soft gradient glow. Short fade (≈150 ms) on show/hide/colour change, no continuous animation (no idle redraws). Python needs `LD_PRELOAD=libgtk4-layer-shell.so`; re-exec once as Cursor Highlight does. (Phase 06)
- **R9 Stack.** Python ≥ 3.12 on the system interpreter (PyGObject and gtk4-layer-shell come from pacman, so no runtime pip dependencies); dev tools (pytest, ruff, mypy) through `uv` in a venv created with `--system-site-packages`; CI on GitHub Actions runs everything that does not need a Wayland session, and GI/overlay tests skip cleanly without `gi`. Verified in Phase 02. (ADR-0006, Proposed)
- **R10 Control and CLI.** `vpn-monitor run | pause | resume | toggle | status [--json] | log [-f] [--events]`. The CLI talks to the running daemon over a Unix socket in `$XDG_RUNTIME_DIR/vpn-monitor/` (mode 0700 dir, 0600 socket). Pause hides the bar and stops probing; it lasts until resume or the next login (owner question 4). A desktop notification on pause/resume. (Phase 07)
- **R11 Logging (owner's standing preference).** A human-readable log (`~/.local/state/vpn-monitor/vpn-monitor.log`, rotated) and a JSONL event log (`events.jsonl`, rotated) that records every state change with its inputs and reason: focus class, browser match result, per-family route/interface, classification, decision, and why. (Phase 03 defines the schema, every later phase uses it.)
- **R12 Install and Omarchy-update safety.** `scripts/install.sh` / `uninstall.sh`: symlink the command into `~/.local/bin`, install the user unit into `~/.config/systemd/user/`, add the keybinding to `~/.config/hypr/bindings.lua` (user config, which Omarchy updates do not overwrite) with a backup, and never touch `/usr/share/omarchy/`. Documented in the OSMods log. (Phase 07)
- **R13 Performance budget.** Idle (no browser focused): no timers, ~0% CPU. Browser focused: < 1% CPU average, overlay RSS < 80 MB. Indicator reacts to a focus change in < 150 ms and to a VPN drop in < 2 s. Measured in Phase 08.

### 2.3 Security and privacy baseline (applies to every phase)
- **S1 No window titles.** Titles carry page names and URLs. Read only the window **class** (and address); never log, store or display titles. Tests assert this.
- **S2 No network calls.** Detection is local (routing table, NetworkManager). Never contact an IP-check service or any external host; the route probes do not send packets.
- **S3 Least privilege.** Runs as the user; no root, no `sudo`, no capabilities, no system-wide files. The user service uses systemd sandboxing options that still allow Wayland and D-Bus access (Phase 07 picks, Phase 08 reviews).
- **S4 Never steals input.** The overlay is click-through and takes no keyboard focus; a fault in it must not block the desktop.
- **S5 Control socket.** Only the owning user can connect (directory 0700, socket 0600, peer-credential check). Commands are a fixed small set; no arbitrary input is executed.
- **S6 Honest indicator.** A false *blue* is the worst failure: it says "safe" when not. R4 is a security requirement and is covered by tests in Phases 03, 04 and 08.
- **S7 Secrets.** The project handles none; `.gitignore` and a pre-commit `gitleaks` scan still guard against committing local logs or configs.

### 2.4 Repository and publication requirement (mandatory)
The project lives in a single Git repository that is ready to publish on GitHub. It must contain and keep accurate: README, LICENSE, NOTICE, THIRD_PARTY_NOTICES, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, CHANGELOG, .gitignore, .dockerignore, .editorconfig, .github/ (CI, templates, Dependabot), and docs/. Private data never gets committed; `.gitignore` and a pre-commit secret scan enforce this. The GitHub repo (`antonizick/VPNMonitor`) is created **private** in Phase 01; making it public is the owner's decision in Phase 09. Licence: MIT (matches the owner's other repos; ADR-0008).

### 2.5 Owner questions (status as of 2026-11-18 21:53 CST)
1. **Open (default proposed).** Pause/resume keybinding. SUPER+ALT+V is taken (Prometheus: cycle verbosity). Proposed default: **SUPER+ALT+SHIFT+V** (free on 2026-11-18). Needed by Phase 07.
2. **Open (decided at the Phase 06 review).** Exact look: bar thickness, glow size and the two colours. Proposed default: 3 px core line + 12 px glow (logical px), red `#FF3B30`, blue `#0A84FF`. Phase 06 produces screenshots for the owner to approve before it is wired into the live desktop.
3. **Open (default proposed).** Show the bar over a fullscreen browser (videos)? Proposed default: yes (it is thin; a safety signal should not disappear). Needed by Phase 06.
4. **Open (default proposed).** How long a pause lasts. Proposed default: until resumed or the next login. Alternative: auto-resume after N minutes. Needed by Phase 07.
5. **Deferred (future `/phase-add`).** DNS-leak checking (whether DNS queries bypass the tunnel) is not part of this plan; the route test does not detect it. README states this limit.
6. **Open.** Make the GitHub repo public and/or publish a release at the end? Default: stays private, no release. Needed by Phase 09.

### 2.6 Brainstorm trace
Where each idea in `VPM_Brainstorming.md` went. Disposition: **Adopted** (with the ADR, amendment or phase that carries it), **Deferred** (with its owner question) or **Dropped** (with the reason). A phase that fulfils or changes a row updates it at close-out; `/phase-add` appends rows for new brainstorm entries. Covered through: 2026-11-18 21:30 CST.

| # | Entry (stamp: label) | Idea | Disposition | Where |
|---|---|---|---|---|
| B1 | 2026-11-18 21:30 CST: (unlabelled) | Make it part of the operating system (always there, not an app you open) | Adopted | A4, ADR-0005, R12; Phase 07 |
| B2 | 2026-11-18 21:30 CST: (unlabelled) | Trigger only while a browser window has focus | Adopted | A3, ADR-0004, R6, R7; Phases 03, 05 |
| B3 | 2026-11-18 21:30 CST: (unlabelled) | Detect whether the OS is on a VPN | Adopted | A2, ADR-0003, R3, R4, R5; Phase 04 |
| B4 | 2026-11-18 21:30 CST: (unlabelled) | No VPN → glowing red line at the bottom of the screen | Adopted | A1, ADR-0002, R8; Phase 06 (look tuned via owner question 2) |
| B5 | 2026-11-18 21:30 CST: (unlabelled) | VPN active → glowing blue bar at the bottom of the screen | Adopted | A1, ADR-0002, R8; Phase 06 |
| B6 | 2026-11-18 21:30 CST: (unlabelled) | "Would this be technically feasible?" | Adopted | Answered yes in R1 (Phase 00), with the mechanisms verified on the machine |

---

## Appendix A: Reference machine facts (observed 2026-11-18 21:51 CST, Phase 00)
- Omarchy on Linux 7.2.8-9-omarchy, Hyprland 0.56.2 (Lua config: `~/.config/hypr/bindings.lua`), single monitor `eDP-1` 3840×2160 @ scale 1.6.
- Network: `wlo1` (Wi-Fi), `eno1` (down), `proton0` (ProtonVPN WireGuard via NetworkManager, connection "ProtonVPN US-IL#634"), `tailscale0`, `ipv6leakintrf0` (ProtonVPN IPv6 leak guard, NM dummy "pvpn-killswitch-ipv6"), Docker bridges.
- ProtonVPN uses policy routing: table `245447468`, rule `not from all fwmark 0xea13b2c lookup 245447468`; `ip route get 1.1.1.1` → `dev proton0 table 245447468 src 10.2.0.2 uid 1000`.
- Browsers: `brave-bin` (class `brave-browser`), `chromium`. Packages present: `gtk4-layer-shell`, `python-gobject`, `quickshell`, `proton-vpn-gtk-app`, `tailscale`, `wireguard-tools`, `openvpn`.
- Python 3.14.8 system interpreter; `gh` logged in as `antonizick`.
- Prior art on the same machine: `~/Work/CursorHighlight` (Python + GTK4 layer-shell overlay; LD_PRELOAD re-exec; per-monitor surface rebuild; human + JSONL logs).
