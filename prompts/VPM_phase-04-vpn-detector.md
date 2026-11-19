# VPM Phase 04: VPN route detector and change watcher

**Model:** Claude Opus 5.5 (`/model opus`) · **Depends on:** 03 · **Branch:** `phase-04-vpn-detector` · **Gate:** auto

## Read first
`CLAUDE.md` (especially the project-specific risk rule: never touch the VPN yourself), `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 A2, §2.2 R3, R4, R5, R13, §2.3 S2, S6 and Appendix A. Phase Log entries for Phases 02 and 03. ADR-0003, ADR-0007 (Proposed: this phase decides it). Owner question 5 (DNS, deferred: do not build it). The Brainstorm trace rows this phase fulfils or changes: B3.

## Goal
`vpn.py` produces an honest `VpnReading` for the current user's internet traffic, on demand and on every routing change, with every probe family classified and every failure resolved to UNKNOWN.

## Tasks
1. Route probe: run `ip -j route get <dest>` for each configured destination (default `1.1.1.1`, `2606:4700:4700::1111`) with a short timeout, via `subprocess` with a fixed argv (no shell). Parse JSON: egress `dev`, `type` (`unicast`, `unreachable`, `blackhole`, `prohibit`), table. Errors such as "Network is unreachable" map to kind `unreachable`. No packets are sent (S2); assert in a test that the module never imports `socket` for remote connections.
2. Interface classifier: VPN if NetworkManager reports the device type as `wireguard`, `tun` or `vpn` (`nmcli -t -f DEVICE,TYPE device`, cached and refreshed on link changes) **or** the name matches configured patterns (`proton*`, `wg*`, `tun*`, `tailscale*`, `nordlynx`, `mullvad*`). Leak-guard dummies (ProtonVPN `ipv6leakintrf0`, NM type `dummy` named in config) count as **blocked**, not as a route.
3. Combine per spec R3: VPN only if every family is `routed via VPN` or `blocked/unreachable`, **and at least one family is routed via VPN**; any family routed via a non-VPN interface → NO_VPN (reason names the leaking family and interface); any error/timeout/parse failure → UNKNOWN.
4. Change watcher: pick the event source (an `ip -j monitor route link` subprocess read line by line, or NetworkManager D-Bus `StateChanged`/`PropertiesChanged` via Gio; justify the choice in ADR-0007 and set it Accepted). Debounce bursts (≈200 ms), re-probe, emit a `VpnReading` through the `VpnSource` protocol. Restart the watcher with back-off if it dies; while it is down, readings are UNKNOWN after `max_reading_age`.
5. Periodic re-check only while the engine reports a browser focused (an `active(bool)` hook), default every 5 s.
6. Verify on the real machine **without touching the VPN**: record `ip -j route get` output for both families with ProtonVPN up (expect `proton0` / `ipv6leakintrf0` or unreachable). Then **ask Nick** to disconnect ProtonVPN for a minute (hands-off: block-with-question) and record the NO_VPN reading and the reaction time. Save sanitised fixtures (replace public IPs and the Wi-Fi SSID) under `tests/fixtures/routes/`.
7. A `vpn-monitor probe` debug subcommand (or `status --probe`) that prints the reading and reasons, so Nick can check it any time.

## Out of scope
DNS-leak checks (owner question 5). Focus handling, overlay, control socket.

## Tests
Unit tests over fixture JSON: Proton up (v4 via proton0, v6 to the leak guard), Proton down, Tailscale mesh only (red), Tailscale exit node (blue), IPv4 VPN + IPv6 Wi-Fi leak (red), `ip` missing, timeout, garbage output, kill switch with no route (red). Watcher tests with a fake subprocess stream (burst debounce, restart).

## Acceptance criteria
- On the reference machine with ProtonVPN up, `vpn-monitor probe` reports VPN with both families explained.
- With ProtonVPN disconnected by Nick, it reports NO_VPN within 2 s of the change (measured, logged).
- No fixture contains a real public IP address, SSID or MAC.

## Phase-specific docs
`docs/VPM_ARCHITECTURE.md` (detection algorithm, classification table), README (what blue means, limits), ADR-0007 Accepted, CHANGELOG. Brainstorm trace B3 updated. Then the standard close-out checklist.
