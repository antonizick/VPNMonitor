"""Window-class matcher: is the focused window a browser or an Omarchy web app? (ADR-0004)

Pure: no I/O. Built from the ``[browsers]`` config section. Exact classes are compared
case-sensitively; patterns are Python regular expressions matched against the **whole** class
(``re.fullmatch``), so ``firefox`` as a pattern does not match ``firefox-dev``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_CLASSES: tuple[str, ...] = (
    "brave-browser",
    "chromium",
    "google-chrome",
    "firefox",
    "librewolf",
    "zen",
    "vivaldi-stable",
    "org.mozilla.firefox",
)
"""Exact window classes of full browsers (spec A3, R7)."""

DEFAULT_PATTERNS: tuple[str, ...] = (r"^(brave|chrome|chromium|msedge)-.+__.*$",)
"""Chromium-family ``--app`` windows, which is how Omarchy web apps run (spec R7)."""


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Outcome of one match, with the rule that matched (for the event log, spec R11)."""

    matched: bool
    rule: str | None
    """``exact:<class>`` or ``regex:<pattern>``; ``None`` when nothing matched."""


NO_MATCH = MatchResult(matched=False, rule=None)


class BrowserMatcher:
    """Decides whether a window class belongs to a browser or a web app."""

    __slots__ = ("_exact", "_patterns")

    def __init__(
        self,
        classes: Iterable[str] = DEFAULT_CLASSES,
        patterns: Iterable[str] = DEFAULT_PATTERNS,
    ) -> None:
        """Build the matcher. Raises :class:`re.error` for an invalid pattern."""
        self._exact = frozenset(classes)
        self._patterns = tuple((p, re.compile(p)) for p in patterns)

    def match(self, window_class: str) -> MatchResult:
        """Return whether ``window_class`` is a browser, and which rule said so."""
        if not window_class:
            return NO_MATCH
        if window_class in self._exact:
            return MatchResult(matched=True, rule=f"exact:{window_class}")
        for source, compiled in self._patterns:
            if compiled.fullmatch(window_class):
                return MatchResult(matched=True, rule=f"regex:{source}")
        return NO_MATCH
