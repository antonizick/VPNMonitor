# VPN Monitor: Agent Instructions

These rules apply to every AI agent working in this repository. They are **mandatory**.

## What this project is
VPN Monitor (`vpn-monitor`) is an always-on Omarchy/Hyprland desktop add-on. While a web browser (or an Omarchy web app) has focus, it draws a thin glowing bar along the bottom of that monitor: **red** if internet traffic is not routed through a VPN, **blue** if it is. Stack: Python ≥ 3.12 on the system interpreter, PyGObject + GTK4 + `gtk4-layer-shell` (pacman) for the click-through overlay, Hyprland's IPC event socket for focus, the kernel routing table and NetworkManager for VPN detection, a systemd user service, and `uv` + pytest + ruff + mypy for development.

## Naming and timestamps (mandatory)
- **Project prefix: `VPM`.** Project documents are named `VPM_<NAME>` (`VPM_IMPLEMENTATION_PLAN.md`, `docs/VPM_DECISIONS.md`, `prompts/VPM_phase-NN-<slug>.md`…) so they can be told apart from other projects' documents without their path. Any new project-specific document gets the prefix. `CLAUDE.md`, `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md` and the like keep their conventional names.
- **Timestamps everywhere a date is recorded** (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated"): `YYYY-MM-DD HH:MM TZ`, from `date '+%Y-%m-%d %H:%M %Z'` at the moment you write it. Never a bare date, never guessed.

## Source-of-truth documents (read before working)
| File | Purpose |
|---|---|
| `docs/VPM_SPECIFICATION.md` | Canonical spec. **The Amendments section overrides earlier sections.** |
| `VPM_IMPLEMENTATION_PLAN.md` | Phase table, status, owner questions, phase log. **Keep it accurate.** |
| `prompts/VPM_shared-instructions.md` | Conventions and close-out checklist for every phase |
| `prompts/VPM_phase-NN-*.md` | The prompt for the phase you are executing (start sessions with `/phase`) |
| `docs/VPM_DECISIONS.md` | ADR log; append, never rewrite |
| `VPM_Brainstorming.md` | The owner's brainstorm (source); traced in the spec's Amendments §2.6 |

## Mandatory documentation upkeep
Documentation is part of the deliverable. A phase is **not complete** until all of the following are done:
1. `VPM_IMPLEMENTATION_PLAN.md`: set the phase's status as icon plus word (`🔄 In progress` when you start; `✅ Complete` or `⛔ Blocked` at the end) and add a timestamped Phase Log entry whose **first bullet is the Timeline** (`started` = the claim commit's time, `finished` = `date` as your last step, `merged`, any `blocked` interval; format in the plan's Phase Log header), then built, deviations, follow-ups, tests. **`🔄 In progress` must be committed to `main` before any other work** (the claim protocol in `prompts/VPM_shared-instructions.md` §1a), because parallel agents read the status from `main`. A status that exists only on a phase branch or in a worktree does not count.
2. `CHANGELOG.md`: add entries under `[Unreleased]`.
3. Update every affected document: README, SECURITY, `docs/VPM_ARCHITECTURE.md`, guides, THIRD_PARTY_NOTICES, `.gitignore` / `.dockerignore`.
4. `docs/VPM_DECISIONS.md`: add an ADR for any non-trivial choice or deviation. If the spec changes, add an amendment.
5. **Later phase prompts:** if your work changes an assumption a later prompt relies on, edit that prompt.
6. The Obsidian project note `/home/nick/Documents/02 Projects/VPM Implementation Plan.md`: update the status table (icons), the `updated:` field and add a timestamped log line.
7. Any host OS change must also be documented in `/home/nick/Documents/04 Resources/OSMods/` (read its README first; the index file is `OSMODs README.md`). Never edit root-owned files under `/usr/share/omarchy/`.

## Risk rule (mandatory)
Sessions may run with bypassed permissions. **If an action looks high-risk, irreversible or a bad idea, stop and ask Nick instead of doing it.** In an interactive session, ask. In a hands-off session (`/phase NN --auto` or `PHX_AUTO=1`, started by PhaseHypervisor), block the phase with the question recorded (block-with-question, `prompts/VPM_shared-instructions.md` §1b). Examples: deleting data you did not create, touching another project's files outside the scope your prompt names, changing system-wide config not covered by the prompt, spending money beyond a stated cap, making a repo public, publishing a release, force-pushing shared history. **Project-specific:** never disconnect, reconfigure or restart the VPN, NetworkManager or Tailscale to test something without asking Nick first (it drops his connection); test with fakes, or ask him to toggle the VPN himself.

## Engineering rules
- Stay within the phase's scope; record out-of-scope findings as follow-ups in the Phase Log.
- Tests, lint and type checks must pass before a phase closes. `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` (Phase 02 confirms the exact commands; update this line if they change).
- Never commit secrets, personal data, private recordings, model weights or `.env` files.
- Follow the security and privacy baseline in the spec's Amendments (§2.3). In particular: never read, log or display window **titles** (S1), never contact external hosts (S2), and never show blue on an unknown reading (R4/S6).
- Log every outcome with its reason, plus a record of inputs and outputs (human log + JSONL events, spec R11).
- Pin and lock dependencies, and check licences before adding one.
- Visual changes: produce screenshots (`grim`) for Nick to review before wiring them into the live desktop.
- Git: branch `phase-NN-<slug>` in its own worktree `../VPNMonitor-phase-NN`; the main checkout stays on `main`. Conventional Commits, commit at checkpoints. **Git authority (standing instruction from Nick):** commit, merge, push and create **private** GitHub repos without asking, at checkpoints and at close-out. Only making a repo **public**, publishing a GitHub **release**, or force-pushing shared history needs Nick's explicit confirmation (in hands-off mode: block-with-question). If an action looks high-risk or a bad idea, stop and ask anyway.
- Reference machine: Omarchy (Linux 7.2.8-9-omarchy), Hyprland 0.56.2 with Lua config, one 3840×2160 monitor at scale 1.6, ProtonVPN WireGuard (`proton0`) via NetworkManager with policy routing, Tailscale, Brave + Chromium, Python 3.14.8. Details: spec Appendix A.
