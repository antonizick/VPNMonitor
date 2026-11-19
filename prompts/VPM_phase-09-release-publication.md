# VPM Phase 09: Release and publication

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 08 · **Branch:** `phase-09-release-publication` · **Gate:** review

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec §2.4 and §2.5. Phase Log entries for all phases. **Owner question 6 (public repo / release): ask Nick; making the repo public or publishing a GitHub release requires his explicit confirmation in this session (hands-off: block-with-question).** The Brainstorm trace rows this phase fulfils or changes: all (final check).

## Goal
A tagged, documented v1.0.0 that Nick can install from a clean clone, and a final report with the generated timeline; published only if Nick says so.

## Tasks
1. Version bump to `1.0.0`; CHANGELOG `[1.0.0]` heading with a timestamp; README final pass (screenshots, install, usage, limits, uninstall).
2. Clean-clone check: clone into a temp dir, run `scripts/install.sh` against a temp `HOME` with stubs, and the full quality gates; then confirm the live install on the machine still works (`vpn-monitor status`).
3. Definition of done in `VPM_IMPLEMENTATION_PLAN.md`: tick each item with evidence.
4. `docs/VPM_FINAL-REPORT.md`: what was built, how it meets each brainstorm idea (from the trace), measured numbers, known limits, future work (DNS leak check, others), and a `## Timeline` section with the generator's markers (filled by `scripts/phase_timeline.py --write`; never hand-draw a chart).
5. Tag `v1.0.0` (annotated) and push the tag (private repo).
6. Ask Nick about owner question 6; only on his explicit yes: `gh repo edit --visibility public` and/or `gh release create v1.0.0` with notes from the changelog. Record his answer.
7. Vault: mark the project note complete; consider moving it to `05 Archive/` only if Nick asks.

## Out of scope
New features.

## Tests
Full suite green on the tagged commit; CI green.

## Acceptance criteria
- Tag `v1.0.0` on `origin`; final report present with a generated timeline; every Definition-of-done box ticked with evidence.
- Visibility and release state match Nick's recorded answer.

## Phase-specific docs
README, CHANGELOG, `docs/VPM_FINAL-REPORT.md` (new, prefixed), plan Definition of done, OSMods write-up (final version), vault note. Then the standard close-out checklist.
