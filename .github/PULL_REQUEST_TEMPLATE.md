## What and why
<!-- What does this change, and why? Link the issue or phase. -->

## Checklist
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest` passes
- [ ] Conventional Commit message(s)
- [ ] `CHANGELOG.md` `[Unreleased]` updated
- [ ] Docs updated where affected
- [ ] No window titles, IP addresses, logs or secrets in code, tests, fixtures or screenshots
- [ ] No code path contacts an external host
- [ ] An unknown or stale VPN reading still renders red (never a false blue)
