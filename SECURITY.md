# Security policy

## Reporting a vulnerability
Please report security issues **privately** through GitHub's security advisories: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue. Expect an acknowledgement within a few days. This is a personal project, so there is no formal SLA.

If you find that VPN Monitor shows **blue** (VPN) when your traffic is **not** routed through a VPN, treat that as a security issue and report it privately. It is the most serious failure this tool can have.

## Scope
In scope: the `vpn-monitor` daemon, CLI, control socket, systemd unit and install scripts in this repository, and false "safe" indications.

Out of scope: vulnerabilities in GTK, Hyprland, NetworkManager, your VPN client or the VPN service itself (report those upstream), and DNS leaks (VPN Monitor checks routes only; see the README's limits).

## Security and privacy baseline (summary)
The full text is in `docs/VPM_SPECIFICATION.md` (Amendments §2.3).

- **S1 No window titles.** Only the window class is read. Titles are never logged, stored or displayed. The logs (`~/.local/state/vpn-monitor/`, directory mode 0700, files 0600) hold window classes, interface names and reasons only; an Omarchy web app's class includes its host name (for example `brave-basecamp.com__-Default`). Tests use a `TitleGuard` that fails if a title would reach either log.
- **S2 No network calls.** The service unit allows only `AF_UNIX` and `AF_NETLINK` sockets (`RestrictAddressFamilies`), so the kernel refuses any IP socket from the daemon. Detection uses the local routing table (`ip route get` looks a route up without sending anything) and the kernel's link list; the detector has no socket code (a test checks its imports). No IP-check services, no external hosts, no telemetry.
- **S3 Least privilege.** Runs as the user; no root, no sudo, no capabilities, no system-wide files. The systemd user unit adds sandboxing (`NoNewPrivileges`, `ProtectSystem=strict`, read-only home, `PrivateTmp`, an empty capability set, `SystemCallFilter=@system-service`); `systemd-analyze --user security` rates it 1.6 OK.
- **S4 Never steals input.** The overlay is click-through and takes no keyboard focus: layer-shell keyboard mode NONE, an empty input region set on every map, no exclusive zone. If gtk4-layer-shell is not active the overlay refuses to start instead of opening an ordinary window, and toolkit errors are logged, never raised into the daemon (ADR-0017).
- **S5 Control socket.** `$XDG_RUNTIME_DIR/vpn-monitor/control.sock`: directory 0700, socket 0600 (created under umask 0177), every peer's uid is read with `SO_PEERCRED` and must be the daemon's own (any other peer is dropped without a reply and logged). One JSON line of at most 4096 bytes per connection; only `pause`, `resume`, `toggle` and `status` are accepted, anything else is rejected and logged (with a sanitised, truncated command). A silent client is dropped after 0.5 s. A second daemon is refused by an `flock` on `daemon.lock`. `status` reveals window **classes** but never titles. There is no network listener.
- **S6 Honest indicator.** Unknown or stale readings render red (staleness counts time spent suspended). A false blue is a bug. Every known false-blue failure mode and its test is listed in the threat model, [`docs/VPM_THREAT_MODEL.md`](docs/VPM_THREAT_MODEL.md).
- **S7 Secrets.** The project handles none. `.gitignore` and a pre-commit `gitleaks` scan guard against committing logs or local config.

## Security checks (Phase 08, 2026-11-19 10:41 CST)
`ruff` with the bandit (`S`) rules is part of the lint gate; `bandit -r src` reports no medium or high findings; `uv audit` finds no known vulnerabilities in the locked dev dependencies; `gitleaks` finds nothing in the full history; `shellcheck` is clean on the scripts; `systemd-analyze --user security vpn-monitor.service` rates the unit 1.6 OK. The open exposure items are justified in the threat model.

## Supported versions
Only the latest release (or `main` while in development).
