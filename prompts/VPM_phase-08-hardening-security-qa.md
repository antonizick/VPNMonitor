# VPM Phase 08: Hardening, security review and QA

**Model:** Claude Opus 5.5 (`/model opus`) · **Depends on:** 07 · **Branch:** `phase-08-hardening-security-qa` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the whole spec Amendments (§2), especially R4, R13 and §2.3. Every Phase Log entry, and every follow-up recorded in them. All ADRs. The Brainstorm trace rows this phase fulfils or changes: all (check each is still accurate).

## Goal
Evidence that VPN Monitor is honest (no false blue), private, cheap and robust, with every follow-up closed or explicitly deferred.

## Tasks
1. Threat model `docs/VPM_THREAT_MODEL.md`: assets (the owner's belief about protection), the false-blue failure modes (stale reading, split-tunnel leak, policy-routing surprises, watcher death, Hyprland reconnect, monitor hot-plug, clock jumps, suspend/resume), local attackers (another user on the control socket), and privacy (titles, logs). Map each to a test or a mitigation.
2. Fault-injection tests: `ip` hangs, `nmcli` missing, Hyprland socket closes mid-line, overlay surface creation fails, log directory read-only, suspend/resume (simulated clock jump): each ends red-or-hidden, never blue, and is logged.
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
