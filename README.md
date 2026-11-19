# VPN Monitor

A tiny always-on desktop add-on for [Omarchy](https://omarchy.org)/Hyprland. While a web browser (or an Omarchy web app) has focus, a thin glowing bar is drawn along the bottom edge of that monitor:

- 🔴 **red**: internet traffic is **not** routed through a VPN
- 🔵 **blue**: internet traffic **is** routed through a VPN

No browser focused means no bar. The overlay is click-through and never takes input.

![Red bar: not on a VPN](docs/screenshots/vpm-bar-red.png)
![Blue bar: on a VPN](docs/screenshots/vpm-bar-blue.png)

*The bottom 60 px of a 3840×2160 monitor at scale 1.6, over a plain fullscreen window. The bar shows over fullscreen browsers too.*

> **Status: v1.0.0.** Complete and running as a systemd user service on the reference machine (Omarchy, Hyprland 0.56, ProtonVPN WireGuard). Hardened and measured (see [Performance](#performance-measured-2026-11-19-reference-machine) and the [threat model](docs/VPM_THREAT_MODEL.md)). CI is configured but has not run on GitHub yet (account billing block); the same checks pass locally. See the [final report](docs/VPM_FINAL-REPORT.md).

## How it works
Hyprland's event socket reports which window has focus (window **class** only, never the title). The kernel routing table tells which interface internet-bound traffic (IPv4 and IPv6) would leave through, and the kernel's own link type says whether that is a VPN tunnel (WireGuard or tun). That works for any VPN of those kinds (ProtonVPN, Mullvad, `wg-quick`, OpenVPN, a Tailscale exit node), with or without NetworkManager. Blue means every family either goes through a VPN or is blocked (kill switch, leak guard), and at least one goes through a VPN. Route changes are watched, so a VPN drop turns the bar red within a fraction of a second (measured: 0.23 s). A pure decision engine combines the two, and a GTK4 + `gtk4-layer-shell` overlay draws the bar. Anything unknown renders red: the indicator never says "safe" unless it is sure.

## Install
```
git clone https://github.com/antonizick/VPNMonitor.git && cd VPNMonitor
scripts/install.sh            # add --no-keybinding or --no-start to skip those steps
```
`install.sh` is idempotent and changes only your home directory:

| What | Where |
|---|---|
| command (a symlink to `scripts/vpn-monitor`, which runs the repository with the system python) | `~/.local/bin/vpn-monitor` |
| systemd user unit, enabled and started (it follows your graphical session) | `~/.config/systemd/user/vpn-monitor.service` |
| pause/resume key **SUPER+ALT+SHIFT+V** (one marked block; the original is saved once as `bindings.lua.bak.vpn-monitor`) | `~/.config/hypr/bindings.lua` |

It refuses to touch anything if that key is already bound to something else. The command points into the repository, so run `scripts/install.sh` again if you move it. **Uninstall:** `scripts/uninstall.sh` removes all three (the bindings file is restored exactly unless you edited it meanwhile, and the backup is left in place). Logs stay in `~/.local/state/vpn-monitor/`.

## Usage
```
vpn-monitor status [--json]   # focus, VPN reading with per-family reasons, indicator, uptime
vpn-monitor pause             # hide the bar and stop probing (also: SUPER+ALT+SHIFT+V)
vpn-monitor resume            # show it again
vpn-monitor toggle            # pause or resume (what the key runs)
vpn-monitor log [-f] [--events]   # recent human log, or the JSONL events; -f follows
vpn-monitor run [--foreground]    # run the daemon yourself (the service does this at login)
```
`pause` and `resume` show a desktop notification and play a soft two-tone cue (falling for pause, rising for resume; `pause.sound = false` mutes it, `pause.sound_volume` sets the level). A pause lasts until you resume or the next login (set `pause.auto_resume_minutes` for an automatic resume). `systemctl --user reload`-style config changes: send `SIGHUP` (`systemctl --user kill -s HUP vpn-monitor`); a broken file keeps the old settings, and `[vpn]`/`[probes]` changes need a restart.

## Troubleshooting
- **No bar at all.** `vpn-monitor status` (exit 3 means the daemon is not running: `systemctl --user status vpn-monitor`, `journalctl --user -u vpn-monitor`). The bar shows only while a window on the browser list has focus: run `vpn-monitor focus` to see the class and the rule that matched.
- **"overlay_unavailable" in the log.** gtk4-layer-shell is missing or the compositor lacks layer-shell; the daemon exits instead of opening a normal window.
- **Red although you are on a VPN.** `vpn-monitor probe` explains the verdict per address family (a kill-switch or leak-guard interface, an IPv6 route outside the tunnel, a stale reading).
- **The key does nothing.** `hyprctl binds -j | grep -i 'VPN Monitor'`; if it is missing, run `hyprctl reload` or `scripts/install.sh` again.
- **"another instance is already running".** Only one daemon may run (`vpn-monitor status` shows it).

## Requirements
- Omarchy / Hyprland
- Python ≥ 3.12 on the system interpreter
- System packages: `python-gobject`, `python-cairo`, `gtk4`, `gtk4-layer-shell` (`sudo pacman -S python-gobject python-cairo gtk4 gtk4-layer-shell`)
- `uv` for development only

## Development
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup (`uv venv --system-site-packages && uv sync`) and the quality gates. Architecture: [docs/VPM_ARCHITECTURE.md](docs/VPM_ARCHITECTURE.md). `vpn-monitor probe` checks the routes once and explains the verdict: it checks the routes once and explains the verdict (`--json`, or `--watch` to follow changes live). `vpn-monitor focus` prints the focused window's class, whether it counts as a browser (and by which rule) and its monitor, never the title (`--watch` follows focus changes live). `vpn-monitor preview red|blue|cycle` draws the bar directly (no VPN or focus logic) so you can judge the look: `--seconds N` stops after N seconds, `--monitor DP-1` picks the monitor, `--backdrop` adds a plain fullscreen window underneath (it takes keyboard focus while open), and the draw counter it prints should stay put once a fade ends. `scripts/preview.sh [MONITOR]` saves the screenshots in `docs/screenshots/`. To make another app count as a browser, run `vpn-monitor focus` while it is focused to read its class, then add that class to `browsers.classes` (exact) or a regex to `browsers.patterns` in the config.

## Configuration
Optional: `~/.config/vpn-monitor/config.toml` (or `$XDG_CONFIG_HOME/vpn-monitor/config.toml`). Every key is optional; [`config/config.example.toml`](config/config.example.toml) lists them all with their defaults. Copy it and keep only what you change. The main keys:

| Key | Default | Meaning |
|---|---|---|
| `browsers.classes` / `browsers.patterns` | Brave, Chromium, Chrome, Firefox family, Zen, Vivaldi / Chromium `--app` windows | which windows count as a browser (exact classes; regexes matched against the whole class) |
| `probes.ipv4` / `probes.ipv6` | `1.1.1.1` / `2606:4700:4700::1111` | destinations whose route is looked up (nothing is sent to them) |
| `vpn.interface_patterns` | `proton*`, `wg*`, `tun*`, `tailscale*`, `nordlynx`, `mullvad*` | interface names that count as a VPN (WireGuard and tun devices count whatever their name) |
| `vpn.leak_guard_interfaces` | `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*` | kill-switch interfaces: a route into one counts as blocked (any `dummy` device does too) |
| `vpn.recheck_interval_s` / `vpn.max_reading_age_s` | `5.0` / `10.0` | re-check while a browser is focused; older readings show red |
| `indicator.show_on_fullscreen` | `true` | show the bar over fullscreen browsers |
| `indicator.blue_confirm_ms` | `0` | a VPN reading must hold this long before blue (red is never delayed) |
| `appearance.red` / `appearance.blue` / `thickness` / `glow` | `#FF3B30CC` / `#0A84FFCC` / `2` / `10` | the bar's look: colours (`#RRGGBBAA` alpha allowed), core line and glow height in logical px |
| `appearance.fade_ms` | `150` | fade on show, hide and red ↔ blue |
| `pause.auto_resume_minutes` | `0` | 0 = paused until resumed or the next login |
| `pause.sound` / `pause.sound_volume` | `true` / `30` | soft audio cue on pause (falling) and resume (rising); volume 0 to 100 |

Unknown keys are ignored with a warning in the log; an invalid value stops the daemon with an error naming the key. Logs live in `~/.local/state/vpn-monitor/` (`vpn-monitor.log` and `events.jsonl`, mode 0600, rotated by size: at most about 8 MB with the defaults). If they cannot be written, the daemon keeps running and logs to the journal instead (`journalctl --user -u vpn-monitor`).

## Honest limits
- **Route-based.** "VPN" means internet routes leave through a VPN interface. It does not prove your VPN provider is trustworthy.
- **DNS leaks are not detected.** The route test cannot see whether DNS queries bypass the tunnel. This is deferred (owner question 5); it may be added later.
- A Tailscale mesh connection alone counts as **not** a VPN (red), unless it is used as an exit node routing internet traffic.
- Only browsers on the configurable class list are tracked.
- **Interface-based VPNs only.** Policy-based IPsec without its own interface (classic strongSwan/libreswan setups) routes through the Wi-Fi/Ethernet interface and shows red; add a name glob if yours has an `xfrm`/`ipsec` interface. Conversely, a non-VPN tool that uses a tun device (for example a tun2socks proxy) counts as a VPN.
- **Up, but dead.** A tunnel interface that exists but no longer passes traffic still shows blue: nothing leaks (packets go into the tunnel and stop), but blue does not mean the internet works.
- **No bar is not "safe".** If the overlay cannot draw, or the daemon is paused or not running, there is no bar; only blue means protected. `vpn-monitor status` tells you which.
- The check reflects the **current user's** routes (policy and uid rules included). An app that marks its packets differently (fwmark) could take another route.

## Performance (measured 2026-11-19, reference machine)
| What | Measured | Budget (spec R13) |
|---|---|---|
| CPU, no browser focused (10 min) | 0.057 %, 0.73 wake-ups/s (no timers; the wake-ups are Hyprland events) | ~0 % |
| CPU, Brave focused (10 min, re-check every 5 s) | 0.12 % | < 1 % |
| Memory | PSS 42–45 MB (RSS 104 MB, most of it shared GTK libraries) | < 80 MB |
| Focus change → first frame of the bar | 15–75 ms (then a 150 ms fade-in) | < 150 ms |
| VPN drop → red | 0.25 s (route event → reading 240 ms, → decision 2 ms) | < 2 s |
| Redraws after a fade | 0 | 0 |

## Future work
- **DNS-leak check** (owner question 5, deferred): needs its own phase.
- **A second, non-colour cue** for red (for example a dashed line). The colours are distinct for every common colour-vision deficiency (Phase 08 analysis, ADR-0019), so the owner kept colour only; add it with `/phase-add` if wanted.
- **Suspend signal from logind** (`PrepareForSleep`): would drop the reading the moment the machine sleeps. The suspend-aware clock already makes the first wake-up after resume red; the lock screen covers the short gap before it.
- **A slow same-user control client** can stall the main loop for up to 0.5 s (documented, accepted: it needs a process of your own account).

## Privacy and security
No window titles are read, logged or stored. No network calls are made. See [SECURITY.md](SECURITY.md) and the [threat model](docs/VPM_THREAT_MODEL.md).

## Documentation
- [Specification](docs/VPM_SPECIFICATION.md) (the Amendments section overrides earlier sections)
- [Decisions (ADRs)](docs/VPM_DECISIONS.md)
- [Threat model](docs/VPM_THREAT_MODEL.md)
- [Final report](docs/VPM_FINAL-REPORT.md) (what was built, measured numbers, timeline)
- [Implementation plan](VPM_IMPLEMENTATION_PLAN.md)
- [Docs index](docs/README.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Licence
MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
