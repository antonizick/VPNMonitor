# Route fixtures (Phase 04)

One JSON file per scenario, consumed by `tests/test_vpn.py::test_fixture_scenarios`. Each holds the
`ip` answers (`route4` = `ip -4 -j route get`, `route6` = `ip -6 -j route get`, `links` =
`ip -d -j link show`, reduced to `ifname` + `linkinfo.info_kind`) and the expected reading.

- **Recorded** (`source` says so): `proton_up`, `proton_down`, `proton_up_v6_leak_guard`,
  `kill_switch_no_tunnel`, captured on the reference machine on 2026-11-18 while Nick toggled
  ProtonVPN.
- **Synthesised**: the rest, built from the same interface names (Tailscale mesh/exit node,
  IPv6 leak, no network, blackhole, garbage output).

Sanitised: probe destinations are documentation addresses (`192.0.2.1`, `2001:db8::1111`), the
public IPv6 tunnel address became `2001:db8:ffff::2`, LAN addresses were renumbered, and MAC
addresses and every other link attribute were dropped. A test fails if any fixture contains a
globally routable address, a MAC address or an SSID.
