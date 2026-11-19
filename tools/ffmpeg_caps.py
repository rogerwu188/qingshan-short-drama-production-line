"""Optional ffmpeg filter options that older builds lack (probed once per binary, free).

Device …1485 (2026-11-19, Ubuntu ffmpeg): ``alimiter`` has no ``latency`` option there, so every S7 level step
that asked for ``latency=1`` failed.  ``latency`` only compensates the limiter's lookahead (~5 ms at attack=5),
so dropping it on an old build changes timing by a few ms and nothing else.
"""
from __future__ import annotations

import functools
import subprocess


@functools.lru_cache(maxsize=None)
def filter_has_option(filter_name: str, option: str, ffmpeg: str = "ffmpeg") -> bool:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-h", f"filter={filter_name}"],
                             capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return True  # cannot probe: keep the historical argument
    text = (out.stdout or "") + (out.stderr or "")
    if "Unknown filter" in text or not text.strip():
        return True
    return f" {option} " in text or f"\n  {option}" in text or f" {option}  " in text


def alimiter_latency(ffmpeg: str = "ffmpeg") -> str:
    """``":latency=1"`` when this ffmpeg's alimiter supports it, else ``""``."""
    return ":latency=1" if filter_has_option("alimiter", "latency", ffmpeg) else ""
