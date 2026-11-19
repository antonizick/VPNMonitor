# VPN Monitor

A tiny always-on desktop add-on for [Omarchy](https://omarchy.org)/Hyprland. While a web browser (or an Omarchy web app) has focus, a thin glowing bar is drawn along the bottom edge of that monitor:

- 🔴 **red**: internet traffic is **not** routed through a VPN
- 🔵 **blue**: internet traffic **is** routed through a VPN

No browser focused means no bar. The overlay is click-through and never takes input.

> **Status: in development.** Nothing is installable yet. See the [implementation plan](VPM_IMPLEMENTATION_PLAN.md).

## How it works
Hyprland's event socket reports which window has focus (window **class** only, never the title). The Linux routing table and NetworkManager tell whether internet-bound routes (IPv4 and IPv6) leave through a VPN interface. A pure decision engine combines the two, and a GTK4 + `gtk4-layer-shell` overlay draws the bar. Anything unknown renders red: the indicator never says "safe" unless it is sure.

## Requirements
- Omarchy / Hyprland
- Python ≥ 3.12 on the system interpreter
- System packages: `python-gobject`, `gtk4`, `gtk4-layer-shell` (`sudo pacman -S python-gobject gtk4 gtk4-layer-shell`)
- `uv` for development only

## Development
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup (`uv venv --system-site-packages && uv sync`) and the quality gates. Architecture: [docs/VPM_ARCHITECTURE.md](docs/VPM_ARCHITECTURE.md). Commands exist as stubs (exit status 2, "not implemented yet") until Phase 07.

## Planned commands
```
vpn-monitor run         # start the daemon (normally run by a systemd user service)
vpn-monitor pause       # hide the bar
vpn-monitor resume      # show it again
vpn-monitor toggle      # pause or resume
vpn-monitor status      # current state (add --json for machine-readable output)
vpn-monitor log         # show recent events
```

## Configuration
Optional: `~/.config/vpn-monitor/config.toml` (or `$XDG_CONFIG_HOME/vpn-monitor/config.toml`). Every key is optional; [`config/config.example.toml`](config/config.example.toml) lists them all with their defaults. Copy it and keep only what you change. The main keys:

| Key | Default | Meaning |
|---|---|---|
| `browsers.classes` / `browsers.patterns` | Brave, Chromium, Chrome, Firefox family, Zen, Vivaldi / Chromium `--app` windows | which windows count as a browser (exact classes; regexes matched against the whole class) |
| `probes.ipv4` / `probes.ipv6` | `1.1.1.1` / `2606:4700:4700::1111` | destinations whose route is looked up (nothing is sent to them) |
| `vpn.interface_patterns` | `proton*`, `wg*`, `tun*`, `tailscale*`, `nordlynx`, `mullvad*` | interface names that count as a VPN |
| `vpn.recheck_interval_s` / `vpn.max_reading_age_s` | `5.0` / `10.0` | re-check while a browser is focused; older readings show red |
| `indicator.show_on_fullscreen` | `true` | show the bar over fullscreen browsers |
| `indicator.blue_confirm_ms` | `0` | a VPN reading must hold this long before blue (red is never delayed) |
| `appearance.red` / `appearance.blue` / `thickness` / `glow` | `#FF3B30` / `#0A84FF` / `3` / `12` | the bar's look |
| `pause.auto_resume_minutes` | `0` | 0 = paused until resumed or the next login |

Unknown keys are ignored with a warning in the log; an invalid value stops the daemon with an error naming the key. Logs live in `~/.local/state/vpn-monitor/` (`vpn-monitor.log` and `events.jsonl`, rotated by size).

## Honest limits
- **Route-based.** "VPN" means internet routes leave through a VPN interface. It does not prove your VPN provider is trustworthy.
- **DNS leaks are not detected.** The route test cannot see whether DNS queries bypass the tunnel. This is deferred (owner question 5); it may be added later.
- A Tailscale mesh connection alone counts as **not** a VPN (red), unless it is used as an exit node routing internet traffic.
- Only browsers on the configurable class list are tracked.

## Privacy and security
No window titles are read, logged or stored. No network calls are made. See [SECURITY.md](SECURITY.md).

## Documentation
- [Specification](docs/VPM_SPECIFICATION.md) (the Amendments section overrides earlier sections)
- [Decisions (ADRs)](docs/VPM_DECISIONS.md)
- [Implementation plan](VPM_IMPLEMENTATION_PLAN.md)
- [Docs index](docs/README.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Licence
MIT. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
