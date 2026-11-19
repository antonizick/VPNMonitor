# VPM Phase 02: Python scaffold, CI and quality gates

**Model:** Claude Sonnet 5.5 (`/model sonnet`) · **Depends on:** 01 · **Branch:** `phase-02-python-scaffold-ci` · **Gate:** auto

## Read first
`CLAUDE.md`, `prompts/VPM_shared-instructions.md` (§2 layout, §3 conventions), and the spec sections §2.2 R2, R9, R10, R11 and §2.3. Phase Log entry for Phase 01. ADR-0006 (Proposed: this phase verifies it). The Brainstorm trace rows this phase fulfils or changes: none.

## Goal
An installable, typed Python package `vpn_monitor` with a `vpn-monitor` console script stub, the shared types every later phase uses, fakes, and green local + CI quality gates, so Phases 03–06 can be built in parallel against stable interfaces.

## Tasks
1. `pyproject.toml` (hatchling or setuptools, `requires-python = ">=3.12"`, console script `vpn-monitor = vpn_monitor.cli:main`, no runtime dependencies), dev group: pytest, pytest-cov, ruff, mypy (pin via `uv lock`). Ruff and mypy (`strict` for `src/`) config in `pyproject.toml`.
2. Verify ADR-0006 on the machine: `uv venv --system-site-packages` then `uv run python -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Gtk4LayerShell','1.0')"` works (with `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` if needed; record the exact path). Set the ADR to Accepted (or supersede it) with a timestamp.
3. `src/vpn_monitor/model.py`: frozen dataclasses/enums that are the contract between modules: `FocusEvent` (window class, address, monitor name, fullscreen flag, **no title field**), `MonitorInfo`, `VpnState` (`VPN | NO_VPN | UNKNOWN`), `FamilyRoute` (family, destination, egress interface or None, kind `routed|blocked|unreachable|error`, is_vpn), `VpnReading` (state, per-family routes, reason, timestamp), `Indicator` (`HIDDEN | RED | BLUE`), `Decision` (indicator, monitor, reason, inputs). Docstrings define each field.
4. Module stubs with typed signatures and `NotImplementedError` bodies for `engine.py`, `browsers.py`, `config.py`, `eventlog.py`, `vpn.py`, `focus.py`, `overlay.py`, `control.py`, `daemon.py`; Protocols in `model.py` for `FocusSource`, `VpnSource` and `IndicatorSink` (async iterator / callback style; choose one, record an ADR).
5. `src/vpn_monitor/fakes.py`: scripted fake focus source, fake VPN source and a recording fake indicator sink, implementing the Protocols.
6. `cli.py` with argparse subcommands from spec R10 (stubs print "not implemented yet" and exit 2) and `--version`; `__main__.py`.
7. Tests: `tests/test_model.py` (types immutable, `FocusEvent` has no title attribute), `tests/test_cli.py`, `tests/test_fakes.py`. Mark `wayland` and `gi` pytest markers; a `conftest.py` that skips `gi` tests when `gi` is unavailable.
8. `.github/workflows/ci.yml`: Ubuntu, uv, Python 3.12 and 3.14 matrix, ruff check + format check, mypy, pytest (gi/wayland tests skipped); actions pinned by commit SHA. Add `uv` (pip) ecosystem to `dependabot.yml`. Add `pre-commit` to CI or document why not.
9. `docs/VPM_ARCHITECTURE.md`: the component diagram (focus watcher + VPN detector → engine → overlay; control socket; logs), data types, threading/event-loop model (GLib main loop on the main thread; watchers feed it via `GLib.idle_add` or a GLib-integrated source; record the ADR).

## Out of scope
Real logic in any module (Phases 03–07).

## Tests
`uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` all pass locally; CI green on the pushed branch.

## Acceptance criteria
- `uv run vpn-monitor --version` prints the version; `uv run vpn-monitor status` exits 2 with "not implemented yet".
- The `gi` import check of task 2 passes on the reference machine and the exact incantation is in CONTRIBUTING.
- CI run green on GitHub (link the run in the Phase Log).

## Phase-specific docs
`docs/VPM_ARCHITECTURE.md` (new), CONTRIBUTING (dev setup), README (development section), CHANGELOG, ADR-0006 status + new ADRs (source protocol style, event-loop model). Update the test-command line in `CLAUDE.md` and shared instructions if it changed. Then the standard close-out checklist.
