# VPM Phase 01: Repository foundation and governance

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 00 · **Branch:** `phase-01-repo-foundation` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.3 (security baseline), §2.4 (repository requirement) and Appendix A. Phase Log entry for Phase 00. Owner question 6 (visibility, informational only). The Brainstorm trace rows this phase fulfils or changes: none (governance only).

## Goal
The repo has every governance file the spec's §2.4 requires, a docs skeleton, and a **private** GitHub remote `antonizick/VPNMonitor` with `main` pushed, so later phases only add product code.

## Tasks
1. `LICENSE` (MIT, copyright holder "Nick Antoncic", current year) and `NOTICE` (project name, copyright, pointer to THIRD_PARTY_NOTICES).
2. `README.md`: what it does (red/blue bar while a browser is focused), status "in development", requirements (Omarchy/Hyprland, `python-gobject gtk4 gtk4-layer-shell`), planned commands (`vpn-monitor run|pause|resume|toggle|status|log`), the honest limits (route-based; DNS leaks not detected; spec owner question 5), links to the spec, plan and decisions.
3. `SECURITY.md` (private reporting via GitHub security advisories; scope; the S1–S7 baseline in brief), `CONTRIBUTING.md` (uv dev setup placeholder, Conventional Commits, phase method pointer), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, contact via GitHub), `CHANGELOG.md` (Keep a Changelog with `[Unreleased]`), `THIRD_PARTY_NOTICES.md` (GTK4 LGPL-2.1+, gtk4-layer-shell MIT, PyGObject LGPL-2.1+, as system dependencies that are not bundled; verify each licence from the installed package with `pacman -Qi`, do not guess).
4. `.gitignore` (Python, venvs, `.uv/`, caches, `*.log`, `events.jsonl`, local `config.toml`, screenshots except `docs/screenshots/`), `.dockerignore` (mirrors it; the project ships no image, say so in a comment), `.editorconfig`.
5. `.github/`: `ISSUE_TEMPLATE/bug_report.md` and `feature_request.md` (the bug template asks for `vpn-monitor status --json` output and reminds reporters not to paste window titles or IPs), `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml` (github-actions weekly; pip/uv added in Phase 02). A CI workflow placeholder is **not** added here (Phase 02 owns CI).
6. Docs skeleton: `docs/screenshots/.gitkeep`, and a short `docs/README.md` index linking the spec, decisions, plan and (future) architecture doc.
7. Pre-commit secret scan: `.pre-commit-config.yaml` with `gitleaks` (pin a tag you verify exists with `gh api repos/gitleaks/gitleaks/releases/latest`), plus basic hygiene hooks. Run it once over the repo.
8. Create the private GitHub repo: `gh repo create antonizick/VPNMonitor --private --source . --remote origin` from the main checkout **after the merge**, then push `main`. Never `--public`.

## Out of scope
Python packaging, CI, any product code (Phase 02+). Making the repo public (Phase 09, owner's call).

## Tests
`pre-commit run --all-files` passes (gitleaks finds nothing). `grep -rn '{{' .` finds no template markers.

## Acceptance criteria
- Every file listed in spec §2.4 exists and is non-trivial; licences in THIRD_PARTY_NOTICES match `pacman -Qi` output.
- `gh repo view antonizick/VPNMonitor --json visibility` reports `PRIVATE`; `git log origin/main -1` matches local `main`.

## Phase-specific docs
README, SECURITY, CONTRIBUTING, CHANGELOG (`[Unreleased]`: governance files), `docs/README.md`. Then the standard close-out checklist.
