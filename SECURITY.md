# Security policy

## Reporting a vulnerability
Please report security issues **privately** through GitHub's security advisories: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue. Expect an acknowledgement within a few days. This is a personal project, so there is no formal SLA.

If you find that VPN Monitor shows **blue** (VPN) when your traffic is **not** routed through a VPN, treat that as a security issue and report it privately. It is the most serious failure this tool can have.

## Scope
In scope: the `vpn-monitor` daemon, CLI, control socket, systemd unit and install scripts in this repository, and false "safe" indications.

Out of scope: vulnerabilities in GTK, Hyprland, NetworkManager, your VPN client or the VPN service itself (report those upstream), and DNS leaks (VPN Monitor checks routes only; see the README's limits).

## Security and privacy baseline (summary)
The full text is in `docs/VPM_SPECIFICATION.md` (Amendments §2.3).

- **S1 No window titles.** Only the window class is read. Titles are never logged, stored or displayed.
- **S2 No network calls.** Detection uses the local routing table and NetworkManager. No IP-check services, no external hosts, no telemetry.
- **S3 Least privilege.** Runs as the user; no root, no sudo, no capabilities, no system-wide files.
- **S4 Never steals input.** The overlay is click-through and takes no keyboard focus.
- **S5 Control socket.** Owner-only (directory 0700, socket 0600, peer-credential check) with a fixed, small command set.
- **S6 Honest indicator.** Unknown or stale readings render red. A false blue is a bug.
- **S7 Secrets.** The project handles none. `.gitignore` and a pre-commit `gitleaks` scan guard against committing logs or local config.

## Supported versions
Only the latest release (or `main` while in development).
