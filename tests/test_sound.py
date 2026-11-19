"""Pause/resume audio cues."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import pytest

from vpn_monitor import sound


def peak(data: bytes) -> int:
    with wave.open(io.BytesIO(data)) as w:
        frames = w.readframes(w.getnframes())
    return max(
        abs(int.from_bytes(frames[i : i + 2], "little", signed=True))
        for i in range(0, len(frames), 2)
    )


@pytest.mark.parametrize("name", ["pause", "resume"])
def test_cues_are_short_quiet_valid_wavs(name: str) -> None:
    data = sound.cue_wav(name, 30)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert 0.2 < w.getnframes() / w.getframerate() < 0.35
    assert 0 < peak(data) < 0.2 * 32767
    assert peak(sound.cue_wav(name, 0)) == 0
    assert peak(sound.cue_wav(name, 500)) == peak(sound.cue_wav(name, 100))


def test_cues_differ() -> None:
    assert sound.cue_wav("pause", 30) != sound.cue_wav("resume", 30)


def test_play_writes_the_cache_once_and_starts_a_detached_player(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(sound.shutil, "which", lambda p: f"/usr/bin/{p}" if p == "paplay" else None)
    monkeypatch.setattr(sound.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    assert sound.play("pause", 30, directory=tmp_path)
    assert sound.play("pause", 30, directory=tmp_path)
    argv, kw = calls[0]
    assert argv == ["paplay", str(tmp_path / "pause-30.wav")]
    assert kw["start_new_session"] is True
    assert (tmp_path / "pause-30.wav").stat().st_size > 1000
    assert len(calls) == 2


def test_aplay_is_quiet_and_no_player_is_fine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sound.shutil, "which", lambda p: f"/usr/bin/{p}" if p == "aplay" else None)
    monkeypatch.setattr(sound.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
    assert sound.play("resume", 30, directory=tmp_path)
    assert calls[0][:2] == ["aplay", "-q"]
    monkeypatch.setattr(sound.shutil, "which", lambda p: None)
    assert sound.play("resume", 30, directory=tmp_path) is False


def test_play_swallows_os_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sound.shutil, "which", lambda p: "/usr/bin/pw-play")

    def boom(*_: Any, **__: Any) -> None:
        raise OSError("no audio")

    monkeypatch.setattr(sound.subprocess, "Popen", boom)
    assert sound.play("pause", 30, directory=tmp_path) is False


def test_cache_dir_follows_xdg() -> None:
    assert sound.cache_dir({"XDG_CACHE_HOME": "/x/c"}) == Path("/x/c/vpn-monitor")
    assert sound.cache_dir({}).name == "vpn-monitor"
