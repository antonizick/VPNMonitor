"""TOML configuration loading and validation (defaults live in code).

Stub: implemented in Phase 03.
"""

from __future__ import annotations

from pathlib import Path


def load_config(path: Path | None = None) -> dict[str, object]:
    """Load the user configuration, falling back to built-in defaults."""
    raise NotImplementedError("config.load_config: Phase 03")
