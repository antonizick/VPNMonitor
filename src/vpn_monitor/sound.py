"""Soft audio feedback for pause and resume (played by the CLI, never by the daemon).

Two short sine cues with a smooth envelope: **resume** rises, **pause** falls. The WAV files are
synthesised with the standard library into ``$XDG_CACHE_HOME/vpn-monitor/`` on first use and played
with the first of ``pw-play``, ``paplay`` or ``aplay`` that exists, detached so the command returns
at once. Any failure is silent: sound is a nicety, never a reason for ``pause`` to fail.
"""

from __future__ import annotations

import io
import math
import os
import shutil
import struct
import subprocess
import wave
from collections.abc import Mapping
from pathlib import Path

RATE = 44_100
PLAYERS = ("pw-play", "paplay", "aplay")
CUES: dict[str, tuple[tuple[float, float], ...]] = {
    "resume": ((523.25, 0.09), (783.99, 0.14)),  # C5 then G5: rising
    "pause": ((783.99, 0.09), (523.25, 0.14)),  # G5 then C5: falling
}
MAX_PEAK = 0.5
"""Full volume (100 %) peaks at half scale; the configured volume scales it down further."""


def cue_wav(name: str, volume_percent: int) -> bytes:
    """WAV bytes (mono, 16-bit) of cue ``name`` at ``volume_percent`` (0 to 100)."""
    gain = MAX_PEAK * max(0, min(100, volume_percent)) / 100
    samples: list[int] = []
    for freq, seconds in CUES[name]:
        count = int(RATE * seconds)
        for i in range(count):
            # raised-cosine attack and release: no clicks
            edge = min(i, count - 1 - i) / (RATE * 0.02)
            env = 0.5 - 0.5 * math.cos(math.pi * min(1.0, edge))
            value = math.sin(2 * math.pi * freq * i / RATE) * env * gain
            samples.append(int(value * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()


def cache_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_CACHE_HOME") or ""
    root = Path(base) if os.path.isabs(base) else Path.home() / ".cache"
    return root / "vpn-monitor"


def play(name: str, volume_percent: int, *, directory: Path | None = None) -> bool:
    """Play cue ``name``; return True if a player was started."""
    player = next((p for p in PLAYERS if shutil.which(p)), None)
    if player is None:
        return False
    try:
        folder = cache_dir() if directory is None else directory
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}-{volume_percent}.wav"
        if not path.exists():
            path.write_bytes(cue_wav(name, volume_percent))
        argv = [player, "-q", str(path)] if player == "aplay" else [player, str(path)]
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True
