# VPM Phase 08: Hardening, security review and QA

**Model:** Claude Opus 5.5 (`/model opus`) · **Depends on:** 07 · **Branch:** `phase-08-hardening-security-qa` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the whole spec Amendments (§2), especially R4, R13 and §2.3. Every Phase Log entry, and every follow-up recorded in them. All ADRs. The Brainstorm trace rows this phase fulfils or changes: all (check each is still accurate).

## Goal
Evidence that VPN Monitor is honest (no false blue), private, cheap and robust, with every follow-up closed or explicitly deferred.

## Tasks
1. Threat model `docs/VPM_THREAT_MODEL.md`: assets (the owner's belief about protection), the false-blue failure modes (stale reading, split-tunnel leak, policy-routing surprises, watcher death, Hyprland reconnect, monitor hot-plug, clock jumps, suspend/resume), local attackers (another user on the control socket), and privacy (titles, logs). Map each to a test or a mitigation.
2. Fault-injection tests: `ip` hangs (Phase 04 covers `ip` missing/timeout/garbage at unit level; add an end-to-end daemon test), `ip monitor` dying (restart + red after `max_reading_age_s`, unit-tested in Phase 04), `nmcli` missing (not used since ADR-0015; confirm nothing else needs it), Hyprland socket closes mid-line, overlay surface creation fails, log directory read-only, suspend/resume (simulated clock jump): each ends red-or-hidden, never blue, and is logged.
3. Scanners: `ruff` (with security rules `S`), `bandit` or ruff-S, `pip-audit`/`uv` audit of dev deps, `gitleaks` over full history, `systemd-analyze --user security vpn-monitor`, `shellcheck` on scripts. Fix or justify every finding.
4. Measure on the reference machine and record numbers in the Phase Log and README: idle CPU with no browser focused (expect ~0 %, no wakeups: `perf`/`powertop` or `/proc` sampling over 10 min), CPU and RSS with Brave focused for 10 min, focus-to-bar latency (from the JSONL log), VPN-drop-to-red latency (ask Nick to toggle the VPN). Compare to spec R13.
5. Log hygiene: grep the real logs for anything resembling a window title, URL, public IP, SSID; rotation works; size bounded.
6. Accessibility: red vs blue is a colour-only signal, which colour-blind users may miss. Evaluate a second cue (for example a thicker or differently patterned red bar) and propose it to Nick; do not change the approved look without his answer.
7. Licence audit: dev dependencies and system dependencies vs THIRD_PARTY_NOTICES.
8. Close every follow-up from Phases 01–07 (fix, or move to an owner question / "Future work" in README with reasons).

## Out of scope
New features (DNS leak check stays deferred). Publication.

## Tests
New fault-injection and threat-model tests; full suite green; coverage report recorded.

## Acceptance criteria
- Every threat-model row maps to a passing test or a documented mitigation.
- Measured numbers meet R13 or a deviation is recorded with an ADR.
- No open follow-ups without a disposition.

## Phase-specific docs
`docs/VPM_THREAT_MODEL.md` (new, prefixed), SECURITY, README (performance, limits), `docs/VPM_ARCHITECTURE.md`, THIRD_PARTY_NOTICES, CHANGELOG, ADRs for deviations. OSMods write-up updated with measured results. Then the standard close-out checklist.

## Notes from Phase 04
- VPN-drop reaction measured in Phase 04 with `vpn-monitor probe --watch --log`: 228 ms (disconnect) and 222 ms (reconnect) from the first route event to the reading. For the end-to-end number, compare the `reading` event's `ts` with the `decision` event that follows it in `events.jsonl`.

## Notes from Phase 06 (overlay; 2026-11-19 09:18 CST)
- Overlay memory: RSS counts shared GTK libraries; report PSS (`/proc/<pid>/smaps_rollup`) next to RSS against R13's 80 MB. Phase 06 measured RSS 105 MB / PSS 58 MB with the cairo renderer (154 MB RSS with GTK's GPU renderer, which is why cairo is the default).
- `vpn-monitor preview blue --seconds 600` prints the draw counter; idle redraws must stay 0. `strace` and `pidstat` are not installed on the reference machine; `/proc/<pid>/stat` ticks and `voluntary_ctxt_switches` work.
- Fault injection: "overlay surface creation fails" is unit-tested (`overlay_error` logged, nothing raised); add the end-to-end daemon case.

## Notes from Phase 07 (daemon, service, install; 2026-11-19 09:43 CST)
- The daemon is `Daemon` in `daemon.py` (all parts injected), so end-to-end fault injection can use `FakeVpnSource` / `RecordingSink` / `FakeScheduler` (see `tests/test_daemon.py`: VPN drop, stale reading by timer, callback exception, broken engine, sink failure, reload failure). Real-process cases (`ip monitor` killed, overlay creation failing, Hyprland socket gone) run against the installed service: `systemctl --user kill -s KILL` the child, or `vpn-monitor run --foreground` in a spare terminal.
- Live drop timing seen in Phase 07 (Nick toggled ProtonVPN with the Proton app focused): `ip monitor` event to reading 229 ms (disconnect) and 222 ms (reconnect), the same as Phase 04. The end-to-end "VPN drop to red on screen with a browser focused" number is still to be measured here (grim or the JSONL timestamps).
- Child `ip` processes must not inherit `LD_PRELOAD=libgtk4-layer-shell.so` (fixed in `vpn._c_env`; probes were 300 to 400 ms with it). Check any new subprocess for the same.
- Service sandbox: `systemd-analyze --user security vpn-monitor.service` = 1.6 OK; `RestrictAddressFamilies=AF_UNIX AF_NETLINK` means no IP socket can exist (S2). Put that in the threat model.
- Control socket facts for the threat model: 0700 dir / 0600 socket, `SO_PEERCRED`, 4096-byte lines, 0.5 s client timeout (a slow same-uid client can block the main loop for that long; documented, not fixed).
- The overlay's first map takes 150 to 200 ms on the main loop (ADR-0017), so a bar appears about that long after focus; measure it with the rest.
- The installed symlink points into the repository; after the Phase 07 merge it points at `/home/nick/Work/VPNMonitor/scripts/vpn-monitor`.

