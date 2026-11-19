import re

import pytest

from vpn_monitor.browsers import DEFAULT_CLASSES, DEFAULT_PATTERNS, BrowserMatcher, MatchResult

WEBAPP_RULE = f"regex:{DEFAULT_PATTERNS[0]}"


@pytest.mark.parametrize(
    ("window_class", "rule"),
    [
        # Real classes on the reference machine (spec Appendix A).
        ("brave-browser", "exact:brave-browser"),
        ("chromium", "exact:chromium"),
        # Other default browsers.
        ("google-chrome", "exact:google-chrome"),
        ("firefox", "exact:firefox"),
        ("org.mozilla.firefox", "exact:org.mozilla.firefox"),
        ("librewolf", "exact:librewolf"),
        ("zen", "exact:zen"),
        ("vivaldi-stable", "exact:vivaldi-stable"),
        # Omarchy web apps: Chromium-family --app windows (spec R7).
        ("brave-basecamp.com__-Default", WEBAPP_RULE),
        ("brave-chat.openai.com__-Default", WEBAPP_RULE),
        ("chrome-web.whatsapp.com__-Default", WEBAPP_RULE),
        ("chromium-app.hey.com__-Profile_1", WEBAPP_RULE),
        ("msedge-outlook.office.com__mail_-Default", WEBAPP_RULE),
    ],
)
def test_default_matches(window_class: str, rule: str) -> None:
    assert BrowserMatcher().match(window_class) == MatchResult(True, rule)


@pytest.mark.parametrize(
    "window_class",
    [
        "",
        "foot",
        "KeePassXC",
        "md.obsidian.Obsidian",
        "proton.vpn.app.gtk",
        "Brave-browser",  # case-sensitive
        "BRAVE-BROWSER",
        "brave-browser-beta",  # exact, not prefix
        "firefoxx",
        "brave-",  # no host, no __
        "brave-host",  # no __ marker
        "electron-app__x",  # not a Chromium-family prefix
        " brave-browser",
    ],
)
def test_default_rejects(window_class: str) -> None:
    result = BrowserMatcher().match(window_class)
    assert result == MatchResult(False, None)


def test_patterns_use_fullmatch() -> None:
    matcher = BrowserMatcher(classes=(), patterns=("firefox",))
    assert matcher.match("firefox").matched
    assert not matcher.match("firefox-dev").matched
    assert not matcher.match("xfirefox").matched


def test_exact_wins_over_pattern() -> None:
    matcher = BrowserMatcher(classes=("brave-x__y",), patterns=DEFAULT_PATTERNS)
    assert matcher.match("brave-x__y").rule == "exact:brave-x__y"


def test_first_matching_pattern_is_reported() -> None:
    matcher = BrowserMatcher(classes=(), patterns=("a.*", "ab.*"))
    assert matcher.match("abc").rule == "regex:a.*"


def test_empty_matcher_matches_nothing() -> None:
    matcher = BrowserMatcher(classes=(), patterns=())
    for cls in DEFAULT_CLASSES:
        assert not matcher.match(cls).matched


def test_invalid_pattern_raises() -> None:
    with pytest.raises(re.error):
        BrowserMatcher(patterns=("(",))
