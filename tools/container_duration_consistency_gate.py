#!/usr/bin/env python3
"""Container / stream / decoded-audio duration consistency gate.

Origin: E39-PACKAGING-001 (CL2X-1015/1016, supervisor independent final review).
The released E39 master declared format.duration = 149.479s while the video
stream held only 145.231s of picture -> a 4.22s phantom tail that every existing
gate missed.  `ffmpeg -f null -` and ffprobe packet timestamps BOTH report the
inflated number, so the only trustworthy audio length is the decoded sample
count.  This gate encodes that lesson so the same class of defect cannot ship
again.

Design notes
------------
* `evaluate()` is a pure function over a measurement dict, so the rule is unit
  testable without any media.
* `probe()` produces that dict from a real file using ffprobe + a full PCM
  decode (sample counting), never packet pts.
* Deliberately refuses to PASS on missing measurements: an un-run adapter is a
  FAIL, not a silent PASS (总账 v3 元规则: 审计缺失即 FAIL).
* Gate must be asserted on the RELEASED master AFTER packaging and BEFORE
  publish - the packaging step itself is what introduces the defect.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

TOLERANCE_S = 0.10
PROBE_SAMPLE_RATE = 48000
# Asymmetric on purpose (calibrated against E37/E38/E38R/E39 released masters):
# audio running PAST the picture is the phantom-tail failure mode; audio ending
# a few frames EARLY is normal AAC frame granularity + trailing silence and is
# not audience-perceptible until it becomes a genuinely lost tail.
AV_LEAD_BLOCK_S = 0.10   # decoded audio longer than video
AV_LAG_ADVISE_S = 0.10   # decoded audio shorter than video -> advisory band
AV_LAG_BLOCK_S = 0.50    # decoded audio shorter than video -> real lost tail
TRUSTED_AUDIO_METHODS = {"decoded_samples", "pcm_sample_count"}
FORBIDDEN_AUDIO_METHODS = {
    "packet_pts",
    "ffprobe_packet_pts",
    "format_duration",
    "ffmpeg_null_muxer",
    "audio_stream_duration",
}

REQUIRED_FIELDS = (
    "format_duration_s",
    "video_stream_duration_s",
    "decoded_audio_duration_s",
    "audio_measurement_method",
)

REPAIR_RECIPE = (
    "zero-credit repair (verified on E39): "
    "1) ffmpeg -i IN -map 0:a -c:a pcm_s16le tmp.wav  "
    "2) ffmpeg -i IN -i tmp.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 192k "
    "-movflags +faststart OUT.  "
    "Do NOT use `-c copy -shortest` (no-op on stream copy) and do NOT use `-t <video_len>` "
    "(cuts on the inflated pts and silently destroys real audio tail). "
    "Always re-verify with this gate, never with ffprobe pts or `ffmpeg -f null -`."
)


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate(payload: dict, tolerance_s: float = TOLERANCE_S) -> dict:
    """Return {'status', 'failures', 'metrics'} for one measurement dict."""
    failures: list[str] = []
    advisories: list[str] = []
    metrics: dict = {"tolerance_s": tolerance_s}

    if not isinstance(payload, dict):
        return {
            "status": "FAIL",
            "failures": ["measurement_payload_not_an_object"],
            "advisories": [],
            "metrics": metrics,
        }

    for field in REQUIRED_FIELDS:
        if payload.get(field) in (None, ""):
            failures.append(f"measurement_missing:{field}")

    method = str(payload.get("audio_measurement_method") or "").strip().lower()
    if method:
        if method in FORBIDDEN_AUDIO_METHODS:
            failures.append(f"untrustworthy_audio_measurement_method:{method}")
        elif method not in TRUSTED_AUDIO_METHODS:
            failures.append(f"unknown_audio_measurement_method:{method}")
    metrics["audio_measurement_method"] = method or None

    fmt = _as_float(payload.get("format_duration_s"))
    vid = _as_float(payload.get("video_stream_duration_s"))
    aud = _as_float(payload.get("decoded_audio_duration_s"))
    aud_declared = _as_float(payload.get("audio_stream_duration_s"))

    for name, value in (
        ("format_duration_s", fmt),
        ("video_stream_duration_s", vid),
        ("decoded_audio_duration_s", aud),
    ):
        if payload.get(name) not in (None, "") and value is None:
            failures.append(f"measurement_not_numeric:{name}")

    if fmt is not None and vid is not None:
        delta = round(fmt - vid, 4)
        metrics["container_minus_video_s"] = delta
        if abs(delta) > tolerance_s:
            direction = "over" if delta > 0 else "under"
            failures.append(f"container_duration_{direction}_declared:{delta:+.3f}s")

    if aud is not None and vid is not None:
        delta = round(aud - vid, 4)
        metrics["decoded_audio_minus_video_s"] = delta
        if delta > AV_LEAD_BLOCK_S:
            failures.append(f"audio_runs_past_picture:{delta:+.3f}s")
        elif delta < -AV_LAG_BLOCK_S:
            failures.append(f"audio_tail_lost:{delta:+.3f}s")
        elif delta < -AV_LAG_ADVISE_S:
            advisories.append(f"audio_ends_early_within_advise_band:{delta:+.3f}s")

    if aud_declared is not None and aud is not None:
        delta = round(aud_declared - aud, 4)
        metrics["audio_declared_minus_decoded_s"] = delta
        if abs(delta) > tolerance_s:
            failures.append(f"audio_track_pts_inflated:{delta:+.3f}s")

    if failures:
        status = "FAIL"
    elif advisories:
        status = "PASS_WITH_ADVISORY"
    else:
        status = "PASS"

    result = {
        "gate": "container_duration_consistency",
        "origin": "E39-PACKAGING-001",
        "status": status,
        "severity": "BLOCK",
        "failures": failures,
        "advisories": advisories,
        "metrics": metrics,
    }
    if failures:
        result["repair_recipe"] = REPAIR_RECIPE
    return result


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def probe(path: Path) -> dict:
    """Measure a real media file. Audio length = decoded PCM sample count."""
    if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
        raise RuntimeError("ffprobe/ffmpeg not available")

    info = _ffprobe(path)
    video = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    audio = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {}
    )

    decoded_audio_s = None
    if audio:
        # Raw s16le mono at a fixed rate: byte count -> sample count -> seconds.
        # Downmix/resample never changes duration, and this avoids the WAVE
        # header path entirely (ffmpeg emits WAVE_FORMAT_EXTENSIBLE for >2ch,
        # which python's `wave` module refuses to parse - real regression, E37).
        rate = PROBE_SAMPLE_RATE
        decoded = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ac",
                "1",
                "-ar",
                str(rate),
                "-",
            ],
            check=True,
            capture_output=True,
        )
        decoded_audio_s = round(len(decoded.stdout) / 2.0 / rate, 3)

    return {
        "file": str(path),
        "format_duration_s": _as_float(info.get("format", {}).get("duration")),
        "video_stream_duration_s": _as_float(video.get("duration")),
        "video_nb_frames": video.get("nb_frames"),
        "audio_stream_duration_s": _as_float(audio.get("duration")) if audio else None,
        "decoded_audio_duration_s": decoded_audio_s,
        "audio_measurement_method": "decoded_samples" if audio else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media", help="released master to probe and gate")
    parser.add_argument("--measurement", help="pre-computed measurement JSON")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE_S)
    parser.add_argument("--out", help="write gate result JSON here")
    args = parser.parse_args(argv)

    if not args.media and not args.measurement:
        parser.error("one of --media / --measurement is required")

    payload = (
        probe(Path(args.media))
        if args.media
        else json.loads(Path(args.measurement).read_text())
    )
    result = evaluate(payload, tolerance_s=args.tolerance)
    result["measurement"] = payload

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0 if result["status"] in ("PASS", "PASS_WITH_ADVISORY") else 1


if __name__ == "__main__":
    sys.exit(main())
