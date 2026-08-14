#!/usr/bin/env python3
"""Rank local E36 unadmitted clips as possible source-native motion inserts."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import re
import statistics
from pathlib import Path

import cv2
import numpy as np


UNIT = re.compile(r"(?:^|[-_])(U\d{2}(?:[-_][A-Z0-9]+)*)(?:[-_.]|$)", re.I)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ahash(gray: np.ndarray) -> int:
    tiny = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    mean = float(tiny.mean())
    bits = 0
    for value in tiny.flat:
        bits = (bits << 1) | int(value >= mean)
    return bits


def clip_metrics(path: Path) -> dict:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {"path": str(path), "readable": False}
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frames / fps if fps else 0.0
    sample_step = max(1, round(fps / 2.0))
    sampled = []
    frame_index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index % sample_step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sampled.append(cv2.resize(gray, (180, 320), interpolation=cv2.INTER_AREA))
        frame_index += 1
    capture.release()
    differences = [float(cv2.absdiff(a, b).mean()) for a, b in zip(sampled, sampled[1:])]
    one_fps = sampled[::2]
    hashes = [ahash(frame) for frame in one_fps]
    distances = [bin(a ^ b).count("1") for a, b in zip(hashes, hashes[1:])]
    near = sum(value <= 5 for value in distances)
    match = UNIT.search(path.name)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "readable": True,
        "decoded_frame_count": frame_index,
        "full_decode_complete": frame_index == frames and frames > 0,
        "unit_token": match.group(1).replace("-", "_").upper() if match else None,
        "duration_seconds": duration,
        "fps": fps,
        "frames": frames,
        "sample_count_2fps": len(sampled),
        "frame_difference_mae": {
            "p50": statistics.median(differences) if differences else 0.0,
            "p90": sorted(differences)[min(len(differences) - 1, int(len(differences) * 0.9))] if differences else 0.0,
            "max": max(differences, default=0.0),
        },
        "adjacent_fps1_ahash": {
            "near_pairs_dist_le5": near,
            "pairs": len(distances),
            "ratio": near / len(distances) if distances else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_map", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source_map = json.loads(args.source_map.read_text())
    accepted = {str(Path(item["media"])) for item in source_map["sources"]}
    roots = [
        Path("working_assets/e36_recovery_10000_20260730"),
        Path("working_assets/e36_autonomous_recovery_20260731"),
        Path("working_assets/e36_v2_stills_20260728/local_fight_fallbacks"),
        Path("working_assets/e36_v2_stills_20260728/u17_local_fallback"),
        Path("workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs"),
    ]
    candidates = sorted({path for root in roots if root.exists() for path in root.rglob("*.mp4") if str(path) not in accepted})
    accepted_paths = [Path(item["media"]) for item in source_map["sources"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        accepted_metrics = list(executor.map(clip_metrics, accepted_paths))
        candidate_metrics = list(executor.map(clip_metrics, candidates))
    accepted_metrics.sort(key=lambda item: item.get("adjacent_fps1_ahash", {}).get("ratio", 0.0), reverse=True)
    candidate_metrics.sort(
        key=lambda item: (
            -item.get("frame_difference_mae", {}).get("p50", 0.0),
            item.get("adjacent_fps1_ahash", {}).get("ratio", 1.0),
        )
    )
    by_base_unit: dict[str, list[dict]] = {}
    for item in candidate_metrics:
        token = item.get("unit_token")
        if token:
            base = token.split("_")[0]
            by_base_unit.setdefault(base, []).append(item)
    report = {
        "schema": "qingshan.e36.unadmitted_motion_salvage_inventory.v1",
        "source_map": str(args.source_map.resolve()),
        "source_map_sha256": sha256(args.source_map),
        "accepted_clip_count": len(accepted_metrics),
        "unadmitted_candidate_count": len(candidate_metrics),
        "method": "full clip decode; 2fps 180x320 grayscale adjacent MAE for motion; 1fps 8x8 aHash dist<=5 for low-change ratio",
        "accepted_ranked_by_low_change": accepted_metrics,
        "unadmitted_ranked_by_motion": candidate_metrics,
        "unadmitted_by_base_unit": by_base_unit,
        "gate_results": {
            "all_candidate_paths_read": "PASS" if all(item.get("readable") for item in candidate_metrics) else "FAIL_SOME_UNREADABLE",
            "all_candidate_full_decodes_complete": "PASS"
            if all(item.get("full_decode_complete") for item in candidate_metrics)
            else "FAIL_SOME_INCOMPLETE_DECODES",
            "admission": "NOT_GRANTED_REQUIRES_UNIT_SPECIFIC_VISUAL_AUDIO_AND_CANONICAL_QA",
            "automatic_hybrid_use": "PROHIBITED_UNTIL_QA",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
