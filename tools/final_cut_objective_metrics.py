#!/usr/bin/env python3
"""Measure the FINAL rendered mp4 and emit objective, non-self-declarable metrics.

Why this exists (E19R V15 post-mortem, CL2X-292):
  The old audience gate consumed `semantic_group_pct` built from AgentCut
  *source filenames* (`tools/build_agentcut_audience_evidence.py`,
  `semantic_group_basis="agentcut_source_identity"`). Forty distinct source
  files that render forty near-identical images scored ~1.3% each and passed a
  15% ceiling, while a per-shot pixel measurement of the same file showed 30.4%
  near-duplicate shots. The gate measured asset provenance, not what the
  audience sees.

  This module never reads the edit project. It decodes the delivered mp4 and
  reports what a viewer would actually receive. Everything here is measured;
  nothing here can be asserted by the producing agent.

Outputs `qingshan.final_cut_objective_metrics.v1`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=DeprecationWarning, module="PIL")

# Hamming distance between 64-bit average hashes below which two shots are
# treated as the same picture. 5 is the supervisor's long-standing manual
# threshold (CLAUDE.md step 5); it is deliberately NOT loosened here.
NEAR_DUPLICATE_HAMMING = 5

# Location clustering answers a coarser question than shot duplication ("are we
# still in the same alley?"). A bit-hash is the wrong instrument for it: on
# E19R the 108-bit RGB layout hash had a median pairwise distance of 51/108,
# i.e. indistinguishable from noise, and reported 7% dominance for an episode
# that is visibly ~95% one alley. Palette-and-layout distance in colour space
# is the right signal, because "same place under same lighting" is a colour
# fact. Calibrated on E19R: r=0.06 -> 46%, r=0.08 -> 84%, r=0.10 -> 91%,
# r=0.15 -> 100% (everything chains together). 0.08 sits mid-plateau.
SAME_LOCATION_DISTANCE = 0.08
LOCATION_GRID = 3

SCENE_DETECT_THRESHOLD = 0.25
MIN_SHOT_SECONDS = 0.15


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return (proc.stdout or "") + (proc.stderr or "")


def probe_duration(video: Path) -> float:
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video),
        ]
    ).strip()
    return float(out.splitlines()[0])


def detect_shots(video: Path, duration: float) -> list[tuple[float, float]]:
    """Return [(start, end)] shot boundaries from scene-change detection."""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        scenes_path = Path(handle.name)
    _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video),
            "-filter:v",
            f"select='gt(scene,{SCENE_DETECT_THRESHOLD})',metadata=print:file={scenes_path}",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    text = scenes_path.read_text(encoding="utf-8", errors="ignore")
    scenes_path.unlink(missing_ok=True)
    cuts = [float(m.group(1)) for m in re.finditer(r"pts_time:([0-9.]+)", text)]
    bounds = [0.0] + cuts + [duration]
    shots: list[tuple[float, float]] = []
    for index in range(len(bounds) - 1):
        start, end = bounds[index], bounds[index + 1]
        if end - start >= MIN_SHOT_SECONDS:
            shots.append((start, end))
    return shots


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _average_hash(path: Path, size: int = 8) -> int:
    from PIL import Image

    with Image.open(path) as image:
        small = image.convert("L").resize((size, size), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    bits = 0
    for pixel in pixels:
        bits = (bits << 1) | (1 if pixel >= mean else 0)
    return bits


def _location_signature(path: Path, grid: int = LOCATION_GRID) -> list[float]:
    """Colour-layout signature: grid x grid mean RGB, normalised to 0..1."""
    from PIL import Image

    with Image.open(path) as image:
        small = image.convert("RGB").resize((grid, grid), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
    return [channel / 255.0 for pixel in pixels for channel in pixel]


def _signature_distance(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _cluster_signatures(signatures: list[list[float]], radius: float) -> list[list[int]]:
    """Single-link clustering of colour signatures by mean absolute distance."""
    clusters: list[list[int]] = []
    for index, signature in enumerate(signatures):
        for cluster in clusters:
            if any(_signature_distance(signature, signatures[j]) <= radius for j in cluster):
                cluster.append(index)
                break
        else:
            clusters.append([index])
    return clusters


def _cluster(items: list[tuple[int, int]], radius: int) -> list[list[int]]:
    """Greedy single-link clustering of (index, hash) by hamming radius."""
    clusters: list[list[tuple[int, int]]] = []
    for index, value in items:
        for cluster in clusters:
            if any(_hamming(value, other) <= radius for _, other in cluster):
                cluster.append((index, value))
                break
        else:
            clusters.append([(index, value)])
    return [[index for index, _ in cluster] for cluster in clusters]


def _shot_rms(video: Path, start: float, length: float) -> float | None:
    out = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-ss",
            str(start),
            "-t",
            str(length),
            "-i",
            str(video),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "/dev/null",
        ]
    )
    match = re.search(r"mean_volume: (-?[0-9.]+)", out)
    return float(match.group(1)) if match else None


def measure(video: Path, workdir: Path) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(video)
    shots = detect_shots(video, duration)
    if not shots:
        raise ValueError("no shots detected; refusing to emit metrics")

    picture_hashes: list[tuple[int, int]] = []
    place_signatures: list[list[float]] = []
    place_shot_index: list[int] = []
    for index, (start, end) in enumerate(shots):
        midpoint = (start + end) / 2.0
        frame = workdir / f"shot_{index:04d}.jpg"
        # Crop off the lower fifth so burned-in subtitles do not dominate the
        # signature (subtitle text differs on every shot and would mask
        # picture repetition).
        _run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(midpoint),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "crop=in_w:in_h*0.8:0:0",
                str(frame),
                "-y",
            ]
        )
        if frame.is_file():
            picture_hashes.append((index, _average_hash(frame)))
            place_signatures.append(_location_signature(frame))
            place_shot_index.append(index)

    shot_count = len(shots)
    sampled = len(picture_hashes)

    duplicate_clusters = [c for c in _cluster(picture_hashes, NEAR_DUPLICATE_HAMMING) if len(c) > 1]
    duplicate_shots = sum(len(c) for c in duplicate_clusters)
    repetition_pct = round(duplicate_shots / sampled * 100.0, 3) if sampled else 0.0

    # Fast-cut episodes inflate the raw figure: scene detection fragments one
    # continuous take into several "shots", and neighbouring fragments are of
    # course near-identical. That is a measurement artifact, not reuse. E16
    # (ASL 1.08s) carried 13 adjacent pairs against 36 non-adjacent; E19R
    # carried 0 adjacent against 12, i.e. E19R's repetition is entirely real.
    # The blocking figure therefore counts only non-adjacent reuse.
    non_adjacent_clusters = []
    for cluster in duplicate_clusters:
        ordered = sorted(cluster)
        kept = [ordered[0]]
        for shot in ordered[1:]:
            if shot - kept[-1] > 1:
                kept.append(shot)
        if len(kept) > 1:
            non_adjacent_clusters.append(kept)
    non_adjacent_shots = sum(len(c) for c in non_adjacent_clusters)
    repetition_pct_non_adjacent = round(non_adjacent_shots / sampled * 100.0, 3) if sampled else 0.0

    location_clusters_local = _cluster_signatures(place_signatures, SAME_LOCATION_DISTANCE)
    location_clusters = [[place_shot_index[i] for i in cluster] for cluster in location_clusters_local]
    location_seconds = [sum(shots[i][1] - shots[i][0] for i in cluster) for cluster in location_clusters]
    dominant_pct = round(max(location_seconds) / duration * 100.0, 3) if location_seconds else 0.0

    lengths = [end - start for start, end in shots]
    asl = round(duration / shot_count, 3)

    levels: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(shots):
        rms = _shot_rms(video, start, end - start)
        levels.append({"shot": index, "start": round(start, 3), "mean_dbfs": rms})

    # Mean luma per shot, for the cut-continuity cross-check (baseline: adjacent
    # shots inside one scene must not jump more than 25).
    shot_luma: list[float] = []
    for index, _ in enumerate(shots):
        frame = workdir / f"shot_{index:04d}.jpg"
        if frame.is_file():
            from PIL import Image

            with Image.open(frame) as image:
                small = image.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
                pixels = list(small.getdata())
            shot_luma.append(round(sum(pixels) / len(pixels), 2))
    measured = [row for row in levels if row["mean_dbfs"] is not None]
    digital_zero = [row["shot"] for row in measured if row["mean_dbfs"] <= -90.0]
    jumps = [
        {
            "at": measured[i + 1]["start"],
            "delta_db": round(measured[i + 1]["mean_dbfs"] - measured[i]["mean_dbfs"], 2),
        }
        for i in range(len(measured) - 1)
        if abs(measured[i + 1]["mean_dbfs"] - measured[i]["mean_dbfs"]) > 12.0
    ]

    return {
        "schema": "qingshan.final_cut_objective_metrics.v1",
        "measured_from": "DECODED_FINAL_MP4",
        "video": str(video),
        "duration_seconds": round(duration, 3),
        "shot_count": shot_count,
        "sampled_shot_count": sampled,
        "sampling_basis": "per_shot_midpoint",
        "asl_seconds": asl,
        "sub_1s_shot_pct": round(sum(1 for x in lengths if x < 1.0) / shot_count * 100.0, 3),
        "longest_shot_seconds": round(max(lengths), 3),
        "picture_repetition": {
            "algorithm": "8x8-average-hash",
            "hamming_threshold": NEAR_DUPLICATE_HAMMING,
            "near_duplicate_shot_pct": repetition_pct,
            "near_duplicate_shot_pct_non_adjacent": repetition_pct_non_adjacent,
            "blocking_figure": "near_duplicate_shot_pct_non_adjacent",
            "clusters": duplicate_clusters,
            "non_adjacent_clusters": non_adjacent_clusters,
        },
        # NOT A GATE INPUT. See ADVISORY note below: this measures palette and
        # lighting uniformity, which is not the same claim as "one location",
        # and it was falsified on E16. Kept for observation only.
        "palette_uniformity_ADVISORY": {
            "status": "NOT_VALIDATED_DO_NOT_GATE_ON_THIS",
            "algorithm": f"{LOCATION_GRID}x{LOCATION_GRID}-rgb-colour-signature",
            "distance_metric": "mean_absolute_difference",
            "distance_threshold": SAME_LOCATION_DISTANCE,
            "clusters": len(location_clusters),
            "dominant_cluster_pct": dominant_pct,
            "known_false_positive": (
                "E16 is visibly multi-location (clinic interior, courtyard, street) but "
                "scores 88.8% because the whole episode shares one dark-blue candlelit "
                "grade. E19R scores 86.5% and genuinely is one alley. The metric cannot "
                "tell 'one room' from 'many rooms, one grade'."
            ),
        },
        "video_continuity": {"shot_luma": shot_luma},
        "audio": {
            "shot_levels": levels,
            "digital_zero_shots": digital_zero,
            "level_jump_over_12db_count": len(jumps),
            "level_jumps": jumps[:40],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        workdir = args.workdir or Path(tmp)
        metrics = measure(args.video.resolve(), workdir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "shots": metrics["shot_count"],
                "repetition_pct_raw": metrics["picture_repetition"]["near_duplicate_shot_pct"],
                "repetition_pct_blocking": metrics["picture_repetition"][
                    "near_duplicate_shot_pct_non_adjacent"
                ],
                "palette_uniformity_ADVISORY": metrics["palette_uniformity_ADVISORY"][
                    "dominant_cluster_pct"
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
