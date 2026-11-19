# VPM Phase 06: Glow bar overlay and visual review

**Model:** Claude Opus 5.5 (`/model opus`) · **Depends on:** 03 · **Branch:** `phase-06-glow-bar-overlay` · **Gate:** review

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md`, and the spec sections §2.1 A1, §2.2 R8, R13 and §2.3 S4. Phase Log entries for Phases 02 and 03. ADR-0002. **Owner questions 2 (look) and 3 (fullscreen): if still open, build with the proposed defaults, then ask Nick to approve the screenshots before closing (hands-off: block-with-question with the screenshots committed).** Read `~/Work/CursorHighlight/cursor-highlight` for the proven LD_PRELOAD re-exec and per-monitor layer-surface pattern. The Brainstorm trace rows this phase fulfils or changes: B4, B5.

## Goal
`overlay.py` shows a thin, glowing, click-through red or blue bar along the bottom edge of a chosen monitor, fades between states, costs nothing when hidden, and Nick has approved how it looks.

## Tasks
1. Implement `IndicatorSink` in `overlay.py`: one `Gtk.Window` per monitor using `Gtk4LayerShell` (layer OVERLAY, anchors bottom+left+right, exclusive zone 0, keyboard mode NONE, namespace `vpn-monitor`), with an empty input region so clicks pass through (S4). Re-exec with `LD_PRELOAD` once if needed (same approach as Cursor Highlight).
2. Draw with cairo in a `Gtk.DrawingArea`: a core line (`thickness`, default 3 px logical) and a vertical gradient glow (`glow`, default 12 px) fading to transparent; colours from config (defaults red `#FF3B30`, blue `#0A84FF`). Respect monitor scale (3840×2160 @ 1.6) so it is crisp.
3. Transitions: ≈150 ms opacity fade on show/hide and a cross-fade on colour change, driven by a frame clock tick callback that is removed when the animation ends (no idle redraws, R13).
4. Monitor handling: create/destroy surfaces on monitor add/remove (Gdk display monitors), show only on the requested monitor, survive a monitor unplug without crashing.
5. Fullscreen: when `show_on_fullscreen` is true the overlay layer sits above fullscreen windows; verify on the machine with a fullscreen Brave video.
6. `scripts/preview.sh` and a `vpn-monitor preview red|blue|cycle [--seconds N]` subcommand that drives the overlay directly (no VPN or focus logic), plus `grim` screenshots of the bottom 60 px region into `docs/screenshots/` (red, blue, over a fullscreen window). Crop out anything personal on screen.
7. **Visual review:** show Nick the screenshots (and offer a live `vpn-monitor preview cycle`), apply his changes to thickness/glow/colours, record his decision in owner questions 2 and 3 and in an ADR. Do not wire the overlay into a running service (Phase 07).

## Out of scope
Focus/VPN logic, systemd unit, keybinding, install.

## Tests
`gi`/`wayland`-marked tests: surface properties (layer, anchors, exclusive zone, keyboard mode), input region empty, show/hide state machine with a fake frame clock; pure tests for colour parsing and glow gradient stops. Manual: clicking and typing through the bar works; CPU of `vpn-monitor preview blue` idle after the fade is ~0 % (`pidstat` or `ps` sampling, numbers in the Phase Log).

## Acceptance criteria
- Screenshots committed and **approved by Nick** (quote his answer in the Phase Log).
- Clicks on a browser tab bar directly above the glow still reach the browser.
- After a fade completes, the process does no redraws (verified with a draw counter in the debug log).

## Phase-specific docs
`docs/VPM_ARCHITECTURE.md` (overlay section), README (screenshots, appearance config), CHANGELOG, ADR for the approved look. Owner questions 2 and 3 updated. Brainstorm trace B4, B5 updated. Then the standard close-out checklist.

## Notes from Phase 03 (built interfaces you rely on)
- Appearance config is `config.appearance`: `red`, `blue` (`#RRGGBB` or `#RRGGBBAA`, validated), `thickness` (1–32), `glow` (0–128), `fade_ms` (0–2000, default 150). Fullscreen is `config.indicator.show_on_fullscreen`; the engine already returns HIDDEN for a fullscreen browser when it is off, so the overlay only renders the `Decision`.
- A `Decision` names one monitor; every other monitor shows nothing. HIDDEN has `monitor == ""`. `apply` may receive the same indicator twice (reason changed); make it idempotent.
- If the approved look changes a default, change it in `config.py` and `config/config.example.toml` together (a test checks they agree).
