#!/usr/bin/env python3
"""combat_density — a fight must be cut, and each weapon must keep one shape.

Roger 2026-11-08 (E15 看片, order seq=219): 「打斗镜头根本不像是专业的武侠打斗。」

Two things E15 got away with, measured after generation, both free:

  CUT DENSITY   every fight unit stayed on one moving camera; no unit carried a cut, so two authored
                beats were blended by one camera move (H3_SCRIPT_ADAPTATION_GUIDE §1: two beats in one
                unit = one camera move smearing them).  Target: one detected cut per
                ``cut_window_seconds`` inside a fight unit (default 4 s), or the unit's own shot list
                must declare the cuts.
  SHAPE LOCK    the same prop rendered as four different weapons across neighbouring units
                (E15: thin straight sword / curved sabre / broad blade / short cleaver across
                VU-018..021).  Measured without a model: each prop reference card is compared with the
                frames of every unit that binds it, by silhouette-area ratio and aspect ratio of the
                largest foreground component that matches the card's silhouette band.  A unit whose
                best match is below ``min_shape_similarity`` is reported.

Both are diagnostics for the line owner and the writer: neither triggers a reroll on its own
(``on_fail`` is REDESIGN_UNIT_NOT_REROLL, same contract as combat_execution_check).

exit 0 all measured, 3 any unit below threshold, 2 unreadable / nothing measured.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

CHECK_NAME = "combat_density"
CUT_WINDOW_SECONDS = 4.0
#: scene-change score (ffmpeg scdet); 8 % fires on snow, fire and sparks, 15 % fires on real cuts
CUT_THRESHOLD = 15.0
MIN_SHAPE_SIMILARITY = 0.62
SAMPLE_FPS = 2.0


def _ffmpeg() -> str:
    return os.environ.get("NALU_FFMPEG", "ffmpeg")


def _ffprobe() -> str:
    return os.environ.get("NALU_FFPROBE", "ffprobe")


def duration(path: Path) -> float:
    out = subprocess.run([_ffprobe(), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def scene_cuts(path: Path, *, threshold: float = 15.0) -> list[float]:
    """Detected hard cuts (seconds) via ffmpeg's scene detector."""
    out = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-vf",
                          f"select='gt(scene,{threshold / 100.0:.3f})',metadata=print:file=-",
                          "-an", "-f", "null", "-"], capture_output=True, text=True)
    cuts: list[float] = []
    for line in out.stdout.splitlines():
        if "pts_time:" in line:
            try:
                cuts.append(round(float(line.split("pts_time:")[1].split()[0]), 2))
            except ValueError:
                continue
    return cuts


def cut_density(cuts: list[float], seconds: float, *, window: float = CUT_WINDOW_SECONDS,
                declared_cuts: int | None = None) -> dict[str, Any]:
    windows = max(1, int(math.ceil(seconds / window)))
    needed = windows - 1
    count = max(len(cuts), int(declared_cuts or 0))
    return {"cuts": len(cuts), "declared_cuts": declared_cuts, "windows": windows,
            "required_cuts": needed, "status": "PASS" if count >= needed else "FAIL",
            "reason": None if count >= needed else f"CUT_DENSITY_LOW:{count}<{needed}"}


# --------------------------------------------------------------------------- #
# weapon shape
# --------------------------------------------------------------------------- #

def _frame_samples(video: Path, out_dir: Path, *, fps: float = SAMPLE_FPS) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(video), "-vf", f"fps={fps}",
                    str(out_dir / "f_%03d.png")], capture_output=True, text=True)
    return sorted(out_dir.glob("f_*.png"))


def _largest_component_signature(path: Path) -> dict[str, float] | None:
    """Silhouette signature of the dominant dark object: area share and aspect ratio.

    Weapon cards are the prop on a plain ground, so the prop is the largest non-background region.
    Frames are downsampled; no model, no torch.
    """
    try:
        import numpy as np
        from PIL import Image
    except ModuleNotFoundError:  # pragma: no cover
        return None
    try:
        img = Image.open(path).convert("L").resize((96, 96))
    except OSError:
        return None
    a = np.asarray(img, dtype=float)
    bg = float(np.median(a))
    mask = np.abs(a - bg) > 28.0
    if mask.sum() < 40:
        return None
    ys, xs = np.nonzero(mask)
    h = float(ys.max() - ys.min() + 1)
    w = float(xs.max() - xs.min() + 1)
    return {"area": float(mask.mean()), "aspect": w / h if h else 0.0,
            "fill": float(mask.sum()) / (w * h) if w * h else 0.0}


def shape_similarity(card: dict[str, float], frame: dict[str, float]) -> float:
    """1.0 = same silhouette; compares aspect and fill, tolerant to scale."""
    if not card or not frame:
        return 0.0
    aspect = min(card["aspect"], frame["aspect"]) / max(card["aspect"], frame["aspect"]) if max(card["aspect"], frame["aspect"]) else 0.0
    fill = min(card["fill"], frame["fill"]) / max(card["fill"], frame["fill"]) if max(card["fill"], frame["fill"]) else 0.0
    return round(0.6 * aspect + 0.4 * fill, 3)


def measure_unit(video: Path, card_paths: list[Path], *, window: float = CUT_WINDOW_SECONDS,
                 declared_cuts: int | None = None, min_similarity: float = MIN_SHAPE_SIMILARITY) -> dict[str, Any]:
    secs = duration(video)
    cuts = scene_cuts(video, threshold=CUT_THRESHOLD) if secs else []
    density = cut_density(cuts, secs, window=window, declared_cuts=declared_cuts)
    cards = [c for c in (_largest_component_signature(p) for p in card_paths if p.is_file()) if c]
    shapes: list[dict[str, Any]] = []
    result: dict[str, Any] = {"video": str(video), "check": CHECK_NAME, "duration_seconds": round(secs, 2),
                              "cut_density": density, "weapon_shape": {"status": "NOT_MEASURED"},
                              "on_fail": "REDESIGN_UNIT_NOT_REROLL"}
    if not cards:
        result["weapon_shape"]["reason"] = "NO_PROP_CARD_MEASURABLE"
    else:
        with tempfile.TemporaryDirectory() as tmp:
            frames = _frame_samples(video, Path(tmp))
            best = 0.0
            for frame_path in frames:
                sig = _largest_component_signature(frame_path)
                if not sig:
                    continue
                for card in cards:
                    best = max(best, shape_similarity(card, sig))
            shapes.append({"best_similarity": best, "frames": len(frames)})
            result["weapon_shape"] = {"status": "PASS" if best >= min_similarity else "FAIL",
                                      "best_similarity": best, "min_similarity": min_similarity,
                                      "frames": len(frames),
                                      "reason": None if best >= min_similarity else f"SHAPE_LOCK_LOW:{best}<{min_similarity}"}
    failures = [density["reason"]] if density["status"] == "FAIL" else []
    if result["weapon_shape"].get("status") == "FAIL":
        failures.append(result["weapon_shape"]["reason"])
    result["status"] = "FAIL" if failures else "PASS"
    result["reasons"] = failures
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{CHECK_NAME} — cut density and weapon shape of fight units.")
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--card", action="append", default=[], help="prop reference card (png)")
    ap.add_argument("--cut-window", type=float, default=CUT_WINDOW_SECONDS)
    ap.add_argument("--min-similarity", type=float, default=MIN_SHAPE_SIMILARITY)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cards = [Path(c).expanduser() for c in args.card]
    rc = 0
    for video in args.videos:
        path = Path(video).expanduser()
        if not path.is_file():
            print(json.dumps({"video": str(path), "check": CHECK_NAME, "status": "NOT_MEASURED",
                              "reason": "VIDEO_MISSING"}), file=sys.stderr)
            rc = max(rc, 2)
            continue
        result = measure_unit(path, cards, window=args.cut_window, min_similarity=args.min_similarity)
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] == "FAIL":
            rc = max(rc, 3)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
