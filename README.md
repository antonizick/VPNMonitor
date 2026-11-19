# VPN Monitor

A tiny always-on desktop add-on for [Omarchy](https://omarchy.org)/Hyprland. While a web browser (or an Omarchy web app) has focus, a thin glowing bar is drawn along the bottom edge of that monitor:

- 🔴 **red**: internet traffic is **not** routed through a VPN
- 🔵 **blue**: internet traffic **is** routed through a VPN

No browser focused means no bar. The overlay is click-through and never takes input.

> **Status: in development.** Nothing is installable yet. See the [implementation plan](VPM_IMPLEMENTATION_PLAN.md).

## How it works
Hyprland's event socket reports which window has focus (window **class** only, never the title). The kernel routing table tells which interface internet-bound traffic (IPv4 and IPv6) would leave through, and the kernel's own link type says whether that is a VPN tunnel (WireGuard or tun). That works for any VPN of those kinds (ProtonVPN, Mullvad, `wg-quick`, OpenVPN, a Tailscale exit node), with or without NetworkManager. Blue means every family either goes through a VPN or is blocked (kill switch, leak guard), and at least one goes through a VPN. Route changes are watched, so a VPN drop turns the bar red within a fraction of a second (measured: 0.23 s). A pure decision engine combines the two, and a GTK4 + `gtk4-layer-shell` overlay draws the bar. Anything unknown renders red: the indicator never says "safe" unless it is sure.

## Requirements
- Omarchy / Hyprland
- Python ≥ 3.12 on the system interpreter
- System packages: `python-gobject`, `gtk4`, `gtk4-layer-shell` (`sudo pacman -S python-gobject gtk4 gtk4-layer-shell`)
- `uv` for development only

## Development
See [CONTRIBUTING.md](CONTRIBUTING.md) for setup (`uv venv --system-site-packages && uv sync`) and the quality gates. Architecture: [docs/VPM_ARCHITECTURE.md](docs/VPM_ARCHITECTURE.md). Daemon commands exist as stubs (exit status 2, "not implemented yet") until Phase 07. `vpn-monitor probe` works now: it checks the routes once and explains the verdict (`--json`, or `--watch` to follow changes live). So does `vpn-monitor focus`: it prints the focused window's class, whether it counts as a browser (and by which rule) and its monitor, never the title (`--watch` follows focus changes live). To make another app count as a browser, run `vpn-monitor focus` while it is focused to read its class, then add that class to `browsers.classes` (exact) or a regex to `browsers.patterns` in the config.

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
| `vpn.interface_patterns` | `proton*`, `wg*`, `tun*`, `tailscale*`, `nordlynx`, `mullvad*` | interface names that count as a VPN (WireGuard and tun devices count whatever their name) |
| `vpn.leak_guard_interfaces` | `ipv6leakintrf*`, `pvpnksintrf*`, `pvpnrouteintrf*` | kill-switch interfaces: a route into one counts as blocked (any `dummy` device does too) |
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
- **Interface-based VPNs only.** Policy-based IPsec without its own interface (classic strongSwan/libreswan setups) routes through the Wi-Fi/Ethernet interface and shows red; add a name glob if yours has an `xfrm`/`ipsec` interface. Conversely, a non-VPN tool that uses a tun device (for example a tun2socks proxy) counts as a VPN.
- The check reflects the **current user's** routes (policy and uid rules included). An app that marks its packets differently (fwmark) could take another route.

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
