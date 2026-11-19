# Contributing

Thanks for your interest. VPN Monitor is a small personal project built with a phased method; contributions are welcome within its security baseline (see `SECURITY.md`).

## Development setup
Requirements: Omarchy/Hyprland (or any Hyprland setup), Python ≥ 3.12 on the system interpreter, `uv`, and the system packages `python-gobject gtk4 gtk4-layer-shell`.

```
git clone <repo> && cd VPNMonitor
sudo pacman -S --needed python-gobject gtk4 gtk4-layer-shell uv
uv venv --system-site-packages     # the venv must see the system PyGObject (ADR-0006)
uv sync                            # installs the pinned dev tools from uv.lock
```

`pyproject.toml` sets `python-preference = "only-system"`, so `uv` never picks a uv-managed Python (which cannot import `gi`). Check the GTK bindings:

```
uv run python -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Gtk4LayerShell','1.0'); print('gi ok')"
```

This works without `LD_PRELOAD` on the reference machine (`/usr/lib/libgtk4-layer-shell.so`, gtk4-layer-shell 1.3.0). If a later phase finds that a real layer-shell window needs it, run with `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.

Quality gates (all must pass before a phase closes):

```
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

Tests marked `gi` skip when PyGObject is missing; tests marked `wayland` skip without a Wayland session and always in CI. `scripts/phase_timeline.py` is copied from the phased-project skill and is excluded from ruff; never edit it here.

Install the hooks once: `pre-commit install` (includes a `gitleaks` secret scan). CI does not run `pre-commit`: the hooks are a local safety net for secrets and whitespace, and CI already runs the code gates, so a second runner would only duplicate them and pull in extra tooling.

## Commit style
[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Keep commits focused, and update `CHANGELOG.md` under `[Unreleased]`.

## The phased method
Work is organised in numbered phases tracked in `VPM_IMPLEMENTATION_PLAN.md`; each phase has a prompt in `prompts/`. Agents and humans follow `CLAUDE.md` and `prompts/VPM_shared-instructions.md`. Each phase runs on its own branch (`phase-NN-<slug>`) and is merged when its acceptance criteria and checks pass.

## Ground rules
- Never read, log or display window titles. Never contact external hosts.
- Unknown or stale VPN readings must render red. A false blue is a bug.
- Do not commit logs, screenshots with personal content, IP addresses, secrets or `.env` files.
- Check the licence before adding any dependency, and pin it.
