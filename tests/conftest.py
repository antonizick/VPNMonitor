"""Shared pytest configuration: skip `gi` and `wayland` tests when unavailable."""

from __future__ import annotations

import importlib.util
import os

import pytest


def _have_gi() -> bool:
    return importlib.util.find_spec("gi") is not None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skip_gi = pytest.mark.skip(reason="PyGObject (gi) is not importable")
    skip_wayland = pytest.mark.skip(reason="no Wayland session (WAYLAND_DISPLAY unset)")
    have_gi = _have_gi()
    have_wayland = bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("CI")
    for item in items:
        if "gi" in item.keywords and not have_gi:
            item.add_marker(skip_gi)
        if "wayland" in item.keywords and not (have_gi and have_wayland):
            item.add_marker(skip_wayland)
