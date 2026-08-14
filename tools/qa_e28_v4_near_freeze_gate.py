#!/usr/bin/env python3
"""Compare E28 V3/V4 midsection near-freeze and repeated-composition evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "exports/e28/final/E28_AGENTCUT_V3_WRITER_AGENT_V050_FINAL.mp4"
V4 = ROOT / "exports/e28/agentcut_v4_midsection_recut_20260721/E28_AGENTCUT_V4_MIDSECTION_RECUT_NOT_FINAL.mp4"
OUT = ROOT / "qa/e28_writer_agent_v050_agentcut_v4_recut_20260721/E28_V4_NEAR_FREEZE_AND_REPEAT_GATE.json"
SAMPLE_START = 80.0
V3_WINDOW = 35.0
V4_WINDOW = 21.0
WIDTH = 32
HEIGHT = 32
HASH_DISTANCE_MAX = 120
FREEZE_HASH_DISTANCE_MAX = 64
FREEZE_MAE_MAX = 0.025
MAX_FREEZE_SECONDS = 4.0
MAX_COMPOSITION_REPEATS = 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample(path: Path, start: float, duration: float) -> list[bytes]:
    raw = subprocess.check_output(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(start), "-t", str(duration), "-i", str(path),
            "-vf", f"fps=1,scale={WIDTH}:{HEIGHT},format=gray",
            "-f", "rawvideo", "-",
        ]
    )
    size = WIDTH * HEIGHT
    return [raw[i:i + size] for i in range(0, len(raw), size) if len(raw[i:i + size]) == size]


def ahash(frame: bytes) -> tuple[bool, ...]:
    mean = sum(frame) / len(frame)
    return tuple(pixel >= mean for pixel in frame)


def hamming(left: tuple[bool, ...], right: tuple[bool, ...]) -> int:
    return sum(a != b for a, b in zip(left, right))


def mae(left: bytes, right: bytes) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / len(left) / 255.0


def components(hashes: list[tuple[bool, ...]]) -> list[list[int]]:
    parent = list(range(len(hashes)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left in range(len(hashes)):
        for right in range(left + 1, len(hashes)):
            if hamming(hashes[left], hashes[right]) <= HASH_DISTANCE_MAX:
                union(left, right)
    groups: dict[int, list[int]] = {}
    for index in range(len(hashes)):
        groups.setdefault(find(index), []).append(index)
    return sorted(groups.values(), key=len, reverse=True)


def freeze_clusters(edges: list[dict]) -> list[dict]:
    clusters = []
    active = []
    for edge in edges:
        is_freeze = edge["hash_distance"] <= FREEZE_HASH_DISTANCE_MAX and edge["pixel_mae"] <= FREEZE_MAE_MAX
        if is_freeze:
            active.append(edge)
        elif active:
            clusters.append(active)
            active = []
    if active:
        clusters.append(active)
    return [
        {
            "start": group[0]["from"],
            "end": group[-1]["to"],
            "duration_seconds": round(group[-1]["to"] - group[0]["from"], 3),
            "edge_count": len(group),
            "hash_distances": [row["hash_distance"] for row in group],
            "pixel_mae": [row["pixel_mae"] for row in group],
        }
        for group in clusters
    ]


def inspect(path: Path, start: float, duration: float) -> dict:
    frames = sample(path, start, duration)
    hashes = [ahash(frame) for frame in frames]
    edges = [
        {
            "from": round(start + index, 3),
            "to": round(start + index + 1, 3),
            "hash_distance": hamming(hashes[index], hashes[index + 1]),
            "pixel_mae": round(mae(frames[index], frames[index + 1]), 6),
        }
        for index in range(len(frames) - 1)
    ]
    freezes = freeze_clusters(edges)
    groups = components(hashes)
    repeated = [
        {
            "sample_times": [round(start + index, 3) for index in group],
            "sample_count": len(group),
            "repeat_count": max(0, len(group) - 1),
        }
        for group in groups if len(group) > 1
    ]
    max_freeze = max((row["duration_seconds"] for row in freezes), default=0.0)
    max_repeats = max((row["repeat_count"] for row in repeated), default=0)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "sample_start": start,
        "sample_duration": duration,
        "sample_count": len(frames),
        "thresholds": {
            "composition_hash_distance_max": HASH_DISTANCE_MAX,
            "freeze_hash_distance_max": FREEZE_HASH_DISTANCE_MAX,
            "freeze_pixel_mae_max": FREEZE_MAE_MAX,
            "max_freeze_seconds": MAX_FREEZE_SECONDS,
            "max_composition_repeats": MAX_COMPOSITION_REPEATS,
        },
        "freeze_clusters": freezes,
        "repeated_composition_clusters": repeated,
        "max_freeze_seconds_observed": max_freeze,
        "max_composition_repeats_observed": max_repeats,
        "status": "PASS" if max_freeze <= MAX_FREEZE_SECONDS and max_repeats <= MAX_COMPOSITION_REPEATS else "FAIL",
    }


def main() -> None:
    v3 = inspect(V3, SAMPLE_START, V3_WINDOW)
    v4 = inspect(V4, SAMPLE_START, V4_WINDOW)
    report = {
        "schema": "qingshan.e28.near-freeze-repeat-gate.v1",
        "episode": "E28",
        "recorded_at": now(),
        "status": "PASS_V4_REGRESSION" if v3["status"] == "FAIL" and v4["status"] == "PASS" else "FAIL",
        "method": "1fps 32x32 grayscale aHash connected components plus consecutive-frame pixel-MAE freeze detection",
        "v3_baseline": v3,
        "v4_candidate": v4,
        "conclusion": "V4 must remove V3's two near-freeze runs and reduce the repeated crouch composition to no more than two repeats.",
        "limitations": "Production evidence gate for this recut; AgentCut runtime integration and versioned regression are delegated to the AgentCut implementation task.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "v3": v3["status"], "v4": v4["status"], "report": str(OUT)}, ensure_ascii=False))
    if report["status"] != "PASS_V4_REGRESSION":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
