# Contributing

Thanks for your interest. VPN Monitor is a small personal project built with a phased method; contributions are welcome within its security baseline (see `SECURITY.md`).

## Development setup
Requirements: Omarchy/Hyprland (or any Hyprland setup), Python ≥ 3.12 on the system interpreter, `uv`, and the system packages `python-gobject gtk4 gtk4-layer-shell`.

```
# Placeholder: exact commands are confirmed in Phase 02, when pyproject.toml lands.
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
```

Install the hooks once: `pre-commit install` (includes a `gitleaks` secret scan).

## Commit style
[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`. Keep commits focused, and update `CHANGELOG.md` under `[Unreleased]`.

## The phased method
Work is organised in numbered phases tracked in `VPM_IMPLEMENTATION_PLAN.md`; each phase has a prompt in `prompts/`. Agents and humans follow `CLAUDE.md` and `prompts/VPM_shared-instructions.md`. Each phase runs on its own branch (`phase-NN-<slug>`) and is merged when its acceptance criteria and checks pass.

## Ground rules
- Never read, log or display window titles. Never contact external hosts.
- Unknown or stale VPN readings must render red. A false blue is a bug.
- Do not commit logs, screenshots with personal content, IP addresses, secrets or `.env` files.
- Check the licence before adding any dependency, and pin it.
