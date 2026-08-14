#!/usr/bin/env python3
"""Measure the strict E36 fps=1 adjacent average-hash release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ahash(path: Path) -> int:
    with Image.open(path) as image:
        pixels = list(image.convert("L").resize((8, 8), Image.Resampling.LANCZOS).getdata())
    mean = sum(pixels) / len(pixels)
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= mean)
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    video = Path(args.video).resolve()
    out = Path(args.out).resolve()
    with tempfile.TemporaryDirectory(prefix="e36_fps1_ahash_") as temp:
        pattern = str(Path(temp) / "%06d.png")
        subprocess.run([args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf", "fps=1", pattern], check=True)
        frames = sorted(Path(temp).glob("*.png"))
        hashes = [ahash(frame) for frame in frames]
    distances = [bin(left ^ right).count("1") for left, right in zip(hashes, hashes[1:])]
    near = [index + 1 for index, distance in enumerate(distances) if distance <= 5]
    ratio = round(len(near) / len(distances) * 100.0, 3) if distances else 0.0
    payload = {
        "schema": "qingshan.e36.fps1_adjacent_ahash.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video": str(video),
        "video_sha256": sha256(video),
        "sample_fps": 1,
        "sampled_frames": len(hashes),
        "adjacent_pairs": len(distances),
        "hamming_distance_threshold": 5,
        "near_pairs": len(near),
        "near_pair_indices": near,
        "near_pair_ratio_percent": ratio,
        "release_threshold_percent": 15.0,
        "status": "PASS" if ratio <= 15.0 else "FAIL",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "ratio": ratio, "near_pairs": len(near), "pairs": len(distances), "out": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
