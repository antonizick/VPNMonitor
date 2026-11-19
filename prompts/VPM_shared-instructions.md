# Shared Instructions for Every Phase

Read this file in full before starting any phase. Each phase prompt assumes it.

**Phase IDs.** `NN` in this file is the phase ID: two digits, optionally with a lower-case letter suffix for a phase inserted after another one with `/phase-add` (`09a`, `15a`, `15b`…). An inserted phase is a normal phase with its own claim, branch and worktree; `15a` sorts after `15` and before `16`.

## 1. Orientation and claim (every phase, before writing code)
1. Read `CLAUDE.md`, `VPM_IMPLEMENTATION_PLAN.md` (including the Phase Log and Owner questions) and the spec sections named in your phase prompt. Always read the Amendments.
2. Confirm that every phase listed under "Depends on" is `✅ Complete`. If one is not, stop and tell Nick.
3. Read the Phase Log entries of the dependency phases; they may record deviations that change what you build.
   If the spec's Amendments have a Brainstorm trace, read the rows your phase fulfils; they say what the owner's brainstorming intended.
4. If an owner question this phase needs is still open, ask Nick before doing the affected work. (Hands-off mode: block-with-question, §1b.)
5. **Claim the phase on `main`** by following §1a. This is the first file change of every phase session. Do not start the Tasks until the claim is verified.
6. If the prompt is ambiguous or contradicts the spec, prefer the spec's Amendments. If it is still unclear, ask Nick before guessing on anything user-visible or hard to reverse. (Hands-off mode: block-with-question, §1b.)

## 1a. Claiming a phase (mandatory; other agents may be running in parallel)
Nick and other agents read the Status column from `main`. A status change made only on a phase branch, or left uncommitted in a worktree, is invisible to them. So every phase is claimed with a commit on `main` **before** any other work.
1. In the main checkout (`/home/nick/Work/VPNMonitor`), check that `git branch --show-current` prints `main` and that `git status --short VPM_IMPLEMENTATION_PLAN.md` prints nothing. If either check fails, stop and tell Nick. Never commit another agent's uncommitted changes.
2. Look for an existing claim: the phase's row on `main`, `git branch --list 'phase-NN-*'` and `git worktree list`. If the row is already `🔄 In progress`, or a branch or worktree exists, do not claim again; follow the resume rules in `/phase`.
3. Set the phase's Status cell to `🔄 In progress`, then commit **only that file** to `main`: `git commit -m "chore(plan): start phase NN" -- VPM_IMPLEMENTATION_PLAN.md`.
4. In the Obsidian project note, set the phase's row to `🔄 In progress`, update its `updated:` field and add a timestamped log line: "Phase NN started (claim commit `<hash>`, branch `phase-NN-<slug>`, worktree `../VPNMonitor-phase-NN`)".
5. Create the worktree and branch from that commit: `git worktree add ../VPNMonitor-phase-NN -b phase-NN-<slug> main`, then install the project's dependencies inside it if it has any. Do all of the phase's work in the worktree, using absolute paths or `cd <worktree> && …` in every command, because the shell may reset to the main checkout between commands. Never switch the main checkout off `main`: other agents commit their claims there.
6. Verify: `git show main:VPM_IMPLEMENTATION_PLAN.md | grep '^| NN '` must show `🔄 In progress`.

If the phase ends `⛔ Blocked`, commit that status to `main` the same way (`chore(plan): phase NN blocked`) so that `main` doesn't show a stale `🔄`. A `✅ Complete` status reaches `main` through the merge.

## 1b. Hands-off mode: block-with-question (PhaseHypervisor contract 1)
Applies only in hands-off mode (`/phase NN --auto` or `PHX_AUTO=1`, set only by PhaseHypervisor); manual sessions ignore this section. Wherever a manual session would ask Nick (an open owner question this phase needs, an ambiguity you must not guess, the risk rule in `CLAUDE.md`, or a failure you cannot fix within scope), do this instead, then end the session:
1. In the worktree, commit all work on the phase branch: `wip(phase-NN): blocked, <short reason>`. Do not merge; keep the branch and worktree.
2. In the main checkout, in `VPM_IMPLEMENTATION_PLAN.md`:
   - add an Owner questions row `| <next #> | <question> | Open (asked <TS>, Phase NN, auto mode). Proposed default: <default> | Phase NN |` (or, for an existing open question, name this phase in its Status cell and keep it `Open`);
   - set the phase's Status to `⛔ Blocked`;
   - add a Phase Log entry `### <TS>: Phase NN: <title> (⛔ Blocked)` with bullets: `- **Timeline:** started <claim TS> (claim commit <hash>) · blocked <TS> to (open)`, then `- **Model:** …`, then `- **Question:** #<id>: <question>`, then what is done, what remains and where to resume.
3. Commit only that file to `main`: `git commit -m "chore(plan): phase NN blocked" -- VPM_IMPLEMENTATION_PLAN.md`, and push `main` if a remote exists.
   Then refresh the timeline on `main` (§4a) in its own commit, `docs(plan): refresh timeline`.
4. In the Obsidian note: row `⛔ Blocked`, `updated:` field, and a timestamped log line naming the question.
5. Final message: what was done, the question and its proposed default, then the `PHX-RESULT` line with `"status":"blocked"` and the question IDs (see `/phase`).

A question is **open** while its Status cell starts with `Open`; `Answered …`, `Decided …` and `Deferred …` are not open.

**Resuming** a `⛔ Blocked` phase in hands-off mode: if a question needed by it is still open, refuse without changing anything. Otherwise set the row to `🔄 In progress`, change `blocked <TS> to (open)` to `blocked <TS> to <TS now>` in its Timeline, commit only the plan file to `main` (`chore(plan): resume phase NN`), refresh the timeline on `main` (§4a) as `docs(plan): refresh timeline`, update the Obsidian note, then run `git merge main` in the worktree, read the answer and continue as a normal resume.

## 2. Target repository layout (evolves; keep `docs/VPM_ARCHITECTURE.md` in sync)
```
VPNMonitor/
├── CLAUDE.md                          agent rules
├── VPM_IMPLEMENTATION_PLAN.md         (prefixed) plan, status, owner questions, Phase Log
├── VPM_Brainstorming.md               (prefixed) owner's brainstorm (source)
├── README.md  LICENSE  NOTICE  SECURITY.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md
├── CHANGELOG.md  THIRD_PARTY_NOTICES.md
├── pyproject.toml  uv.lock  .pre-commit-config.yaml
├── .gitignore  .dockerignore  .editorconfig
├── .github/                           workflows/ci.yml, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md, dependabot.yml
├── .claude/commands/                  phase.md, phase-add.md
├── src/vpn_monitor/
│   ├── __init__.py  __main__.py
│   ├── cli.py                         vpn-monitor run|pause|resume|toggle|status|log
│   ├── config.py                      TOML config load + validation (defaults in code)
│   ├── model.py                       shared types: Observation, VpnReading, Decision, Indicator
│   ├── engine.py                      pure state engine (no I/O)
│   ├── browsers.py                    window-class matcher
│   ├── eventlog.py                    human log + JSONL events (rotation, no titles)
│   ├── vpn.py                         route probe + interface classifier + change watcher
│   ├── focus.py                       Hyprland socket2 watcher + initial-state query
│   ├── overlay.py                     GTK4 layer-shell glow bar (per monitor)
│   ├── control.py                     Unix control socket (daemon side + client)
│   ├── daemon.py                      wiring: watchers -> engine -> overlay
│   └── fakes.py                       fake focus source, fake VPN source, fake overlay
├── tests/                             unit (pure), integration (fakes), gi/overlay tests (skip without gi)
├── config/config.example.toml
├── packaging/systemd/vpn-monitor.service
├── scripts/
│   ├── phase_timeline.py              timeline generator (never edit here; copy from the skill)
│   ├── install.sh  uninstall.sh
│   └── preview.sh                     screenshot red/blue bars for review (grim)
├── docs/
│   ├── VPM_SPECIFICATION.md           (prefixed)
│   ├── VPM_DECISIONS.md               (prefixed)
│   ├── VPM_ARCHITECTURE.md            (prefixed, from Phase 02)
│   ├── VPM_TIMELINE.svg               (prefixed, generated)
│   ├── VPM_FINAL-REPORT.md            (prefixed, Phase 09)
│   └── screenshots/
└── prompts/                           VPM_shared-instructions.md, VPM_phase-NN-*.md, VPM_change-request-template.md (all prefixed)
```

## 3. Conventions
- **Prefix.** Project documents carry the project prefix `VPM_` (see `CLAUDE.md`). New project-specific documents follow the same rule; convention-bound files (`README.md`, `LICENSE`, `CHANGELOG.md`, `CLAUDE.md`…) keep their names.
- **Timestamps, not dates.** Every place that records when (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated", changelog release headings) uses `YYYY-MM-DD HH:MM TZ`. Run `date '+%Y-%m-%d %H:%M %Z'` when you write each one; do not guess or copy an earlier timestamp.
- **Python:** `src/` layout, package `vpn_monitor`, console script `vpn-monitor`. Type hints everywhere; `mypy --strict` on `src/` (GI modules typed as `Any` behind a thin wrapper). Ruff for lint and format. No runtime pip dependencies (stdlib + system PyGObject only); dev dependencies pinned in `uv.lock`.
- **Pure core first.** `engine.py`, `browsers.py`, `config.py` and `model.py` never import `gi`, never touch sockets, subprocesses or the clock directly (time is injected). I/O modules talk to the engine only through the types in `model.py`.
- **Fail-safe:** any exception, timeout or unknown reading in a VPN path must produce `VpnReading(state=UNKNOWN, reason=…)`, which the engine renders red (spec R4/S6). Tests cover it.
- **No titles, no network** (spec S1/S2): focus parsing drops the title field at the parser; there is no code path that opens a TCP/UDP socket to a remote host.
- **Logging:** every decision change and every error goes to both logs via `eventlog.py`, with inputs and reason (spec R11). Never `print` from the daemon.
- **Safe testing on the real desktop:** never restart/disconnect the VPN, NetworkManager or Tailscale yourself (ask Nick to toggle it); run the daemon in the foreground (`vpn-monitor run --foreground`) in a spare terminal; use `grim` for screenshots. Overlay tests that need a Wayland session are marked `@pytest.mark.wayland` and skipped in CI.
- **Host changes** (user unit, keybinding, `~/.local/bin` symlink) happen only in Phase 07 via `scripts/install.sh`, with backups, and are recorded in the OSMods log.

## 4. Phase close-out checklist (all items required)
- [ ] All acceptance criteria in the phase prompt are met, with a short verification note for each.
- [ ] Tests, lint and type checks pass: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
- [ ] `VPM_IMPLEMENTATION_PLAN.md`: Status set (`✅ Complete` or `⛔ Blocked`, icon plus word; a `⛔ Blocked` status is also committed to `main` per §1a), Phase Log entry added (timestamp, summary, deviations, follow-ups, test counts).
- [ ] **Timeline bullet written** as the first bullet of the Phase Log entry: *started* = the claim commit's time (`git log -1 --format=%cd --date=format-local:'%Y-%m-%d %H:%M %Z' <claim hash>`), *finished* = `date '+%Y-%m-%d %H:%M %Z'` taken as the last step before the final commit, *merged* = the merge time or `not merged yet`, plus `blocked <TS> to <TS>` for any `⛔` interval. Never reuse an earlier timestamp.
- [ ] `CHANGELOG.md` `[Unreleased]` updated (a release heading carries a timestamp, not just a date).
- [ ] README, SECURITY, `VPM_ARCHITECTURE`, guides, THIRD_PARTY_NOTICES, ignore files updated where affected.
- [ ] ADR added for any notable choice (timestamped in both the entry and its row in the index table at the top of `docs/VPM_DECISIONS.md`); spec amendment added if the spec changed.
- [ ] Later phase prompts corrected if your work changed their assumptions.
- [ ] Brainstorm trace (spec Amendments) updated for every row this phase fulfilled, changed or dropped.
- [ ] Obsidian project note updated (status icons, `updated:` field and a timestamped log line).
- [ ] OS-modification log (`/home/nick/Documents/04 Resources/OSMods/`) updated if the host system was modified.
- [ ] Work committed on the phase branch. Once the phase is `✅ Complete` and every check passes, merge it into `main` without asking (fast-forward where possible), from the main checkout. Conflicts in `VPM_IMPLEMENTATION_PLAN.md` and the changelog are expected when phases ran in parallel: keep every row and entry from both sides, and use the branch's final status for this phase's row. Then push `main` if a remote exists (create a **private** GitHub repo if the plan calls for one), `git worktree remove ../VPNMonitor-phase-NN` and `git branch -d phase-NN-<slug>`. Do not merge a `⛔ Blocked` phase or one with failing checks. Making a repo public or publishing a release needs Nick's explicit confirmation (hands-off mode: block-with-question, §1b).
- [ ] **Timeline refreshed on `main`** after the merge (§4a), committed as `docs(plan): refresh timeline` and pushed.
- [ ] Final message to Nick: what was built, how to try it, what's next, and any open questions. In hands-off mode, its last line is the `PHX-RESULT` line (see `/phase`).

## 4a. Visual timeline (`scripts/phase_timeline.py`)
The plan's `## Timeline` block, `docs/VPM_TIMELINE.svg`, the vault note's timeline and the final report's timeline (once it exists) are generated. Refresh them **only on `main`, never on a phase branch**, so parallel branches never conflict over them:
`python3 scripts/phase_timeline.py --write --vault-note "/home/nick/Documents/02 Projects/VPM Implementation Plan.md"`, then commit the plan, the SVG and the final report (if present) together: `docs(plan): refresh timeline`.
- When: after the merge at close-out, after the `⛔` commit (§1b) and after the resume commit. The claim commit stays status-only, but refresh in its own `docs(plan): refresh timeline` commit right after it so the running phase shows at once. Under `phx` the supervisor also does this itself while a phase runs, so a miss here is repaired.
- If the block or the SVG ever conflicts, take either side and re-run `--write`; never merge it by hand.
- `python3 scripts/phase_timeline.py --check` exits 1 when the outputs are stale (right after a claim this is expected).

