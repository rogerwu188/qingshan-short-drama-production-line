#!/usr/bin/env python3
"""audio_cut_overlap.py — W1 (Roger 2026-09-25 §一,
codex_docs/ROGER-20260925-NALU-LINE-OPTIMIZATION.md): soften the audio at every unit cut point,
zero video/audio duration change, zero paid cost.

Design choice: a true two-stream ``acrossfade`` shortens total duration by the crossfade length
per cut (N segments -> N-1 crossfades -> total shrinks by (N-1)*crossfade_seconds), which risks
video/audio desync on a chain this codebase has not ffmpeg-tested end to end. Instead this module
builds a short symmetric volume "dip" (fade down into the cut, fade up out of it) straddling each
cut point on the SAME single audio stream — the standard soft-transition trick for masking a
content discontinuity at an edit point, with no duration change and no risk to sync.

BUILT AND TESTED, NOT YET WIRED into lines/nalu/runtime/tools/nalu_pipeline.py's stage_s7 (see
configs/DIRECTION_POLICY_V1.json's W1 entry, status BUILT_NOT_WIRED_INTEGRATION_PENDING) — the
existing S7 assembly chain (render -> subtitle burn-in -> endcard -> selective BGM -> loudness
leveling) has no verified insertion point without ffmpeg-level testing against a real rendered
episode, which this session had no safe way to do without risking every future episode's audio.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from lines.nalu.runtime.tools.nalu_media_tools import require_ffmpeg, require_ffprobe
except ImportError:
    try:
        from nalu_media_tools import require_ffmpeg, require_ffprobe  # type: ignore
    except ImportError:
        def require_ffmpeg() -> str:
            path = shutil.which("ffmpeg")
            if not path:
                raise RuntimeError("ffmpeg not found on PATH")
            return path

        def require_ffprobe() -> str:
            path = shutil.which("ffprobe")
            if not path:
                raise RuntimeError("ffprobe not found on PATH")
            return path


def build_dip_filter_chain(boundaries: list[float], crossfade_seconds: float, *, min_start: float = 0.0) -> str:
    """A comma-chained ``afade`` filter string: for every boundary time, fade the audio down into
    it and back up out of it over ``crossfade_seconds`` total (split evenly either side). Applied
    with ``-af`` to a single continuous audio stream — never changes total duration.

    Boundaries at or before ``min_start`` (the very start of the file) and any duplicate/out-of-
    order values are skipped; each fade window is clamped to start at >= 0.
    """
    half = round(crossfade_seconds / 2, 3)
    parts: list[str] = []
    seen: set[float] = set()
    for t in sorted(boundaries):
        t = round(float(t), 3)
        if t <= min_start or t in seen:
            continue
        seen.add(t)
        fade_start = max(0.0, round(t - half, 3))
        parts.append(f"afade=t=out:st={fade_start:g}:d={half:g}")
        parts.append(f"afade=t=in:st={t:g}:d={half:g}")
    return ",".join(parts)


def probe_duration(ffprobe: str, path: Path) -> float:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=False,
    )
    return round(float((result.stdout or "0").strip() or 0), 6)


def apply_cut_point_dips(input_video: Path, boundaries: list[float], crossfade_seconds: float,
                         output_video: Path) -> dict[str, object]:
    """Re-encodes the audio track only (video stream copied) with a volume dip at every boundary.
    Never overwrites an existing output — same convention as tools/ad_tail_insert.py."""
    if output_video.is_file():
        raise FileExistsError(f"refusing to overwrite existing output: {output_video}")
    ffmpeg, ffprobe = require_ffmpeg(), require_ffprobe()
    duration = probe_duration(ffprobe, input_video)
    chain = build_dip_filter_chain(boundaries, crossfade_seconds)
    output_video.parent.mkdir(parents=True, exist_ok=True)
    argv = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(input_video)]
    if chain:
        argv += ["-af", chain]
    argv += ["-c:v", "copy", "-c:a", "aac", str(output_video)]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not output_video.is_file():
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")
    out_duration = probe_duration(ffprobe, output_video)
    return {"input": str(input_video), "output": str(output_video), "boundaries_applied": len(boundaries),
            "crossfade_seconds": crossfade_seconds, "input_duration": duration, "output_duration": out_duration,
            "duration_unchanged": abs(out_duration - duration) < 0.1}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--boundary", action="append", type=float, default=[], dest="boundaries",
                    help="a cut-point time in seconds; repeatable (e.g. from release_timeline.json's segments[].output_start)")
    ap.add_argument("--crossfade-seconds", type=float, default=0.08)
    ap.add_argument("--output", required=True, type=Path)
    a = ap.parse_args()
    try:
        report = apply_cut_point_dips(a.input, a.boundaries, a.crossfade_seconds, a.output)
    except (FileExistsError, RuntimeError) as exc:
        print(f"FAIL:{exc}", file=sys.stderr)
        return 2
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
