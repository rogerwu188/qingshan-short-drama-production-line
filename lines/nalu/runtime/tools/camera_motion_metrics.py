#!/usr/bin/env python3
"""camera_motion_metrics.py — measure global camera motion per clip and classify locked-off shots.

Roger 2026-10-30 (E12 成片审看, item 2): dialogue units default to a static / locked-off camera;
metric = locked-off share of shots (target ≥ 70 %) and shots with ≥ 1 camera direction reversal per
second (target 0).  This tool is the measurement half; `clip_lockoff_stabilize.py` is the repair half.

Method (per clip, free, OpenCV only)
  * frames are read at native fps, converted to grey and downscaled so the width is ``--work-width``
    (default 384 px; all pixel figures are rescaled back to the clip's native width);
  * goodFeaturesToTrack on frame t-1 → calcOpticalFlowPyrLK to frame t → cv2.estimateAffinePartial2D
    (RANSAC, similarity: translation dx,dy, uniform scale s, rotation θ);
  * if fewer than ``--min-inliers`` tracks survive, the frame pair falls back to cv2.phaseCorrelate
    (translation only, scale 1, rotation 0) and is marked ``fallback``;
  * the per-frame deltas are integrated into a cumulative path x(t), y(t), log-scale z(t), θ(t).

Per-shot statistics
  translation_px_per_s_median   median over frames of |(dx,dy)| · fps   (native pixels)
  zoom_pct_per_s                |z(T) − z(0)| / T · 100   (cumulative log-scale rate; 1 %/s = the frame grows or
                                shrinks by 1 % of its width per second)
  zoom_total_pct                |exp(z(T)) − 1| · 100
  reversals_per_s               direction reversals per second of the cumulative camera path, summed over
                                x, y and log-scale.  A reversal is a turning point of the path whose excursion
                                on BOTH sides is at least the prominence: ``--prominence-pct`` of the frame
                                width for translation (default 1.5 % ≈ 11 px on a 768-wide clip) and
                                ``--prominence-zoom-pct`` for scale (default 1.5 %).  The path is smoothed first
                                (moving average over ``--smooth-frames``, default 5 ≈ 0.2 s).  Why prominence
                                and not velocity sign: LK tracking on a 768-wide frame carries ±0.3 px/frame
                                (±7 px/s) of jitter, so a velocity-sign rule counts noise as "camera changed
                                direction"; a viewer only registers a reversal when the frame visibly moves
                                one way and then visibly comes back.
  camera_class                  LOCKED_OFF | SLOW_MOVE | MOVING | UNSTABLE

Locked-off definition (stated for the record, see --help of the thresholds):
  translation_px_per_s_median ≤ 2 px/s  AND  zoom_pct_per_s ≤ 1 %/s  AND  reversals_per_s ≤ 0.2 /s.
  Why: on a 768-wide clip 2 px/s is below what a viewer perceives as a move over a 4 s shot (8 px total,
  ~1 % of width), 1 %/s zoom is the slowest dolly a viewer registers as intentional, and 0.2 reversals/s
  tolerates at most one direction change per 5 s shot (one accidental drift correction), which a locked
  tripod never shows but an LK tracker on a near-static image occasionally does.
  UNSTABLE = reversals_per_s ≥ 1.0 regardless of magnitude (Roger's "每秒换向 ≥1 次" metric).
  MOVING = any threshold exceeded and translation or zoom clearly above the perceptual floor
  (translation > 6 px/s or zoom > 3 %/s); otherwise SLOW_MOVE.

Shot vs unit: this line renders one clip per video unit; a unit can contain several editorial shots
(E12: 53 units, 61 editorial shot ids).  The clip is what the viewer sees and what stabilisation can
change, so the metric is per unit clip, with the editorial shot ids listed on each row for mapping.

Usage
  camera_motion_metrics.py --clips-dir <dir> [--timeline <release_timeline.json>]
                           [--grouping <GROUPING_PLAN.json>] --out <metrics.json> [--md <table.md>]
  camera_motion_metrics.py --clip <one.mp4> --out <metrics.json>
No network, no writes outside --out/--md.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

SCHEMA = "nalu.camera_motion_metrics.v1"

LOCKED_TRANSLATION_PX_S = 2.0
LOCKED_ZOOM_PCT_S = 1.0
LOCKED_REVERSALS_S = 0.2
UNSTABLE_REVERSALS_S = 1.0
MOVING_TRANSLATION_PX_S = 6.0
MOVING_ZOOM_PCT_S = 3.0

THRESHOLDS = {
    "locked_off": {"translation_px_per_s_median_max": LOCKED_TRANSLATION_PX_S,
                   "zoom_pct_per_s_max": LOCKED_ZOOM_PCT_S, "reversals_per_s_max": LOCKED_REVERSALS_S},
    "unstable": {"reversals_per_s_min": UNSTABLE_REVERSALS_S},
    "moving": {"translation_px_per_s_median_min": MOVING_TRANSLATION_PX_S, "zoom_pct_per_s_min": MOVING_ZOOM_PCT_S},
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def frame_transforms(path: Path, *, work_width: int = 384, min_inliers: int = 12,
                     max_corners: int = 600) -> dict[str, Any]:
    """Per-frame similarity deltas (native pixel units) and clip facts."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    scale = work_width / float(width) if width else 1.0
    size = (work_width, max(1, int(round(height * scale))))
    prev = None
    rows: list[dict[str, Any]] = []
    fallbacks = 0
    frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        grey = cv2.cvtColor(cv2.resize(frame, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if prev is None:
            prev = grey
            continue
        dx = dy = 0.0
        ds = 0.0  # log scale
        dth = 0.0
        inliers = 0
        fallback = False
        pts = cv2.goodFeaturesToTrack(prev, maxCorners=max_corners, qualityLevel=0.01, minDistance=7, blockSize=7)
        if pts is not None and len(pts) >= min_inliers:
            nxt, status, _err = cv2.calcOpticalFlowPyrLK(prev, grey, pts, None, winSize=(21, 21), maxLevel=3,
                                                         criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
            good = status.reshape(-1) == 1
            src = pts[good].reshape(-1, 2)
            dst = nxt[good].reshape(-1, 2)
            if len(src) >= min_inliers:
                m, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=2.0,
                                                     maxIters=2000, confidence=0.99)
                inliers = int(inl.sum()) if inl is not None else 0
                if m is not None and inliers >= min_inliers:
                    a, b = float(m[0, 0]), float(m[0, 1])
                    s = math.hypot(a, b)
                    dth = math.atan2(-b, a)
                    ds = math.log(max(s, 1e-6))
                    # translation of the frame centre (not the origin) so rotation/zoom do not leak into dx,dy
                    cx, cy = size[0] / 2.0, size[1] / 2.0
                    tx = float(m[0, 0] * cx + m[0, 1] * cy + m[0, 2]) - cx
                    ty = float(m[1, 0] * cx + m[1, 1] * cy + m[1, 2]) - cy
                    dx, dy = tx / scale, ty / scale
                else:
                    fallback = True
            else:
                fallback = True
        else:
            fallback = True
        if fallback:
            (sx, sy), _resp = cv2.phaseCorrelate(np.float32(prev), np.float32(grey))
            dx, dy = float(sx) / scale, float(sy) / scale
            ds = 0.0
            dth = 0.0
            fallbacks += 1
        rows.append({"dx": dx, "dy": dy, "dlogscale": ds, "dtheta": dth, "inliers": inliers, "fallback": fallback})
        prev = grey
    cap.release()
    return {"fps": fps, "width": width, "height": height, "frames": frames, "work_width": work_width,
            "fallback_frames": fallbacks, "deltas": rows}


def _smooth(values: list[float], window: int) -> list[float]:
    if window <= 1 or len(values) < window:
        return list(values)
    out = []
    half = window // 2
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def count_reversals(path: list[float], prominence: float) -> int:
    """Turning points of a cumulative path with excursions >= prominence on both sides (hysteresis)."""
    if len(path) < 3 or prominence <= 0:
        return 0
    reversals = 0
    anchor = path[0]          # last confirmed extreme
    direction = 0             # +1 rising, -1 falling, 0 undecided
    extreme = path[0]
    for v in path[1:]:
        if direction == 0:
            if v - anchor >= prominence:
                direction, extreme = 1, v
            elif anchor - v >= prominence:
                direction, extreme = -1, v
            continue
        if direction == 1:
            if v > extreme:
                extreme = v
            elif extreme - v >= prominence:   # came back down by >= prominence after rising
                reversals += 1
                anchor, direction, extreme = extreme, -1, v
        else:
            if v < extreme:
                extreme = v
            elif v - extreme >= prominence:
                reversals += 1
                anchor, direction, extreme = extreme, 1, v
    return reversals


def mask_internal_cuts(tf: dict[str, Any], cuts_s: Sequence[float] | None, pad_frames: int = 1) -> dict[str, Any]:
    """Zero the frame deltas at authored picture cuts inside a derived clip (unit re-cut, Roger 2026-10-30 item 3).

    A cut between two shots is not a camera move: the tracker reports it as a one-frame jump that the
    reversal counter then reads as the camera changing direction.  The deltas within ``pad_frames`` of each
    cut are set to zero (the path continues from where the previous shot left it); the rest is untouched."""
    if not cuts_s:
        return tf
    fps = float(tf.get("fps") or 24.0)
    deltas = tf.get("deltas") or []
    masked = 0
    for cut in cuts_s:
        centre = int(round(float(cut) * fps)) - 1          # delta i is frame i -> i+1
        for i in range(max(0, centre - pad_frames), min(len(deltas), centre + pad_frames + 1)):
            if any(abs(float(deltas[i].get(k) or 0.0)) > 0 for k in ("dx", "dy", "dlogscale", "dtheta")):
                masked += 1
            deltas[i] = {**deltas[i], "dx": 0.0, "dy": 0.0, "dlogscale": 0.0, "dtheta": 0.0, "masked_cut": True}
    out = dict(tf, deltas=deltas)
    out["internal_cuts_masked"] = {"cuts_s": [float(c) for c in cuts_s], "frames_masked": masked}
    return out


def summarise(path: Path, tf: dict[str, Any], *, smooth_frames: int = 5, prominence_pct: float = 1.5,
              prominence_zoom_pct: float = 1.5) -> dict[str, Any]:
    fps = tf["fps"]
    deltas = tf["deltas"]
    n = len(deltas)
    duration = (tf["frames"] or 1) / fps
    if n == 0:
        return {"clip": str(path), "error": "NO_FRAME_PAIRS", "frames": tf["frames"]}
    dx = [d["dx"] for d in deltas]
    dy = [d["dy"] for d in deltas]
    dz = [d["dlogscale"] for d in deltas]
    dth = [d["dtheta"] for d in deltas]
    trans_mag_px_s = [math.hypot(a, b) * fps for a, b in zip(dx, dy)]
    cum_x, cum_y, cum_z, cum_th = sum(dx), sum(dy), sum(dz), sum(dth)
    width = float(tf["width"] or 768)
    px_prom = width * prominence_pct / 100.0
    sx = _smooth([0.0, *np.cumsum(dx).tolist()], smooth_frames)
    sy = _smooth([0.0, *np.cumsum(dy).tolist()], smooth_frames)
    sz = _smooth([0.0, *(np.cumsum(dz) * 100.0).tolist()], smooth_frames)   # cumulative zoom in %
    reversals = (count_reversals(sx, px_prom) + count_reversals(sy, px_prom)
                 + count_reversals(sz, prominence_zoom_pct))
    reversals_per_s = reversals / duration
    trans_median = statistics.median(trans_mag_px_s)
    zoom_pct_s = abs(cum_z) / duration * 100.0
    zoom_total_pct = abs(math.exp(cum_z) - 1.0) * 100.0
    # path extent: how far the frame drifts from its first position (what a lock-off must crop)
    path_x = list(np.cumsum(dx))
    path_y = list(np.cumsum(dy))
    extent_x = (max(path_x + [0.0]) - min(path_x + [0.0]))
    extent_y = (max(path_y + [0.0]) - min(path_y + [0.0]))
    locked = (trans_median <= LOCKED_TRANSLATION_PX_S and zoom_pct_s <= LOCKED_ZOOM_PCT_S
              and reversals_per_s <= LOCKED_REVERSALS_S)
    if reversals_per_s >= UNSTABLE_REVERSALS_S:
        camera_class = "UNSTABLE"
    elif locked:
        camera_class = "LOCKED_OFF"
    elif trans_median > MOVING_TRANSLATION_PX_S or zoom_pct_s > MOVING_ZOOM_PCT_S:
        camera_class = "MOVING"
    else:
        camera_class = "SLOW_MOVE"
    return {
        "clip": str(path), "frames": tf["frames"], "fps": fps, "duration_s": round(duration, 3),
        "width": tf["width"], "height": tf["height"], "fallback_frames": tf["fallback_frames"],
        "translation_px_per_s_median": round(trans_median, 2),
        "translation_px_per_s_p90": round(float(np.percentile(trans_mag_px_s, 90)), 2),
        "path_extent_px": {"x": round(extent_x, 1), "y": round(extent_y, 1)},
        "cumulative": {"dx_px": round(cum_x, 1), "dy_px": round(cum_y, 1), "zoom_total_pct": round(zoom_total_pct, 2),
                       "rotation_deg": round(math.degrees(cum_th), 2)},
        "zoom_pct_per_s": round(zoom_pct_s, 3),
        "reversals": reversals, "reversals_per_s": round(reversals_per_s, 3),
        "locked_off": locked, "camera_class": camera_class,
        "unstable": reversals_per_s >= UNSTABLE_REVERSALS_S,
    }


def _measure_one(path: str, kw: dict[str, Any]) -> dict[str, Any]:
    """ProcessPool entry (module-level so it pickles)."""
    return measure_clip(Path(path), **kw)


def measure_clip(path: Path, **kw: Any) -> dict[str, Any]:
    internal_cuts = kw.pop("internal_cuts", None)
    tf = frame_transforms(path, work_width=kw.pop("work_width", 384), min_inliers=kw.pop("min_inliers", 12))
    tf = mask_internal_cuts(tf, internal_cuts)
    row = summarise(path, tf, **kw)
    if tf.get("internal_cuts_masked"):
        row["internal_cuts_masked"] = tf["internal_cuts_masked"]
    row["sha256"] = sha256_file(path)
    return row


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def summary_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if "error" not in r]
    classes: dict[str, int] = {}
    for r in ok:
        classes[r["camera_class"]] = classes.get(r["camera_class"], 0) + 1
    locked = sum(1 for r in ok if r["locked_off"])
    unstable = sum(1 for r in ok if r["unstable"])
    return {"clips": len(rows), "measured": len(ok), "locked_off": locked,
            "locked_off_share": round(locked / len(ok), 4) if ok else None,
            "unstable_reversal_ge_1_per_s": unstable, "classes": classes,
            "targets": {"locked_off_share_min": 0.70, "unstable_max": 0},
            "status": "PASS" if ok and locked / len(ok) >= 0.70 and unstable == 0 else "FAIL"}


def markdown_table(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = ["| unit | shots | dur s | trans px/s med | zoom %/s | zoom tot % | rev | rev/s | class |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r.get('unit_id') or Path(r['clip']).stem} | | | ERROR {r['error']} | | | | | |")
            continue
        lines.append(f"| {r.get('unit_id') or Path(r['clip']).stem} | {','.join(s.split('-')[-1] for s in r.get('editorial_shot_ids') or [])} "
                     f"| {r['duration_s']:.2f} | {r['translation_px_per_s_median']:.2f} | {r['zoom_pct_per_s']:.2f} "
                     f"| {r['cumulative']['zoom_total_pct']:.1f} | {r['reversals']} | {r['reversals_per_s']:.2f} | {r['camera_class']} |")
    lines.append("")
    lines.append(f"locked-off {summary['locked_off']}/{summary['measured']} = {summary['locked_off_share']}; "
                 f"unstable (≥1 reversal/s) {summary['unstable_reversal_ge_1_per_s']}; classes {summary['classes']}; "
                 f"status {summary['status']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clips-dir", type=Path)
    ap.add_argument("--clip", type=Path, action="append")
    ap.add_argument("--timeline", type=Path, help="release_timeline.json: orders rows and names units")
    ap.add_argument("--grouping", type=Path, help="VIDEO_UNIT_GROUPING_PLAN: editorial shot ids + dialogue per unit")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--md", type=Path)
    ap.add_argument("--work-width", type=int, default=384)
    ap.add_argument("--min-inliers", type=int, default=12)
    ap.add_argument("--smooth-frames", type=int, default=5)
    ap.add_argument("--prominence-pct", type=float, default=1.5, help="translation reversal prominence, %% of frame width")
    ap.add_argument("--prominence-zoom-pct", type=float, default=1.5, help="zoom reversal prominence, %% of scale")
    ap.add_argument("--contract", type=Path, help="GENERATION_CONTRACT: marks dialogue units from shots[].prompt_spec.dialogue")
    ap.add_argument("--label", default="")
    ap.add_argument("--internal-cuts", type=Path,
                    help="JSON {unit_id: [cut_s, ...]} (or a nalu.unit_recut_report.v1): authored picture cuts inside "
                         "derived clips are masked so a shot change is not counted as a camera reversal")
    ap.add_argument("--workers", type=int, default=1,
                    help="measure clips in N processes (clips are independent; 53 E12 units ≈ 33 s with 8)")
    args = ap.parse_args(argv)

    clips: list[tuple[str, Path]] = []
    if args.timeline and args.clips_dir:
        tl = json.loads(args.timeline.read_text(encoding="utf-8"))
        for seg in tl.get("segments") or []:
            uid = str(seg.get("unit_id"))
            clips.append((uid, args.clips_dir / f"{uid}.mp4"))
    elif args.clips_dir:
        for p in sorted(args.clips_dir.glob("*.mp4")):
            clips.append((p.stem, p))
    for p in args.clip or []:
        clips.append((p.stem, p))
    if not clips:
        ap.error("no clips: pass --clips-dir (+ --timeline) or --clip")

    shots_of: dict[str, list[str]] = {}
    dialogue_of: dict[str, bool] = {}
    dialogue_shots: set[str] = set()
    if args.contract:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        for shot in contract.get("shots") or []:
            if shot_has_dialogue(shot):
                dialogue_shots.add(str(shot.get("shot_id")))
    if args.grouping:
        gp = json.loads(args.grouping.read_text(encoding="utf-8"))
        for unit in gp.get("units") or []:
            uid = str(unit.get("unit_id"))
            shots_of[uid] = [str(s) for s in unit.get("editorial_shot_ids") or []]
            dialogue_of[uid] = (any(s in dialogue_shots for s in shots_of[uid]) if dialogue_shots
                                else unit_has_dialogue(unit))

    kw = dict(work_width=args.work_width, min_inliers=args.min_inliers, smooth_frames=args.smooth_frames,
              prominence_pct=args.prominence_pct, prominence_zoom_pct=args.prominence_zoom_pct)
    cuts_by_unit: dict[str, list[float]] = {}
    if args.internal_cuts and args.internal_cuts.is_file():
        payload = json.loads(args.internal_cuts.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("units"), dict):      # unit re-cut report
            for uid, row in payload["units"].items():
                if isinstance(row, dict) and row.get("status") == "APPLIED":
                    cuts_by_unit[str(uid)] = [float(c) for c in (row.get("internal_cuts_s") or [])]
        elif isinstance(payload, dict):
            cuts_by_unit = {str(k): [float(c) for c in v] for k, v in payload.items() if isinstance(v, list)}

    def _kw_for(uid: str) -> dict[str, Any]:
        return dict(kw, internal_cuts=cuts_by_unit.get(uid) or None)

    measured: dict[str, dict[str, Any]] = {}
    todo = [(uid, path) for uid, path in clips if path.is_file()]
    if args.workers > 1 and len(todo) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_measure_one, str(path), _kw_for(uid)): uid for uid, path in todo}
            for fut, uid in futures.items():
                measured[uid] = fut.result()
    rows = []
    for uid, path in clips:
        if not path.is_file():
            rows.append({"unit_id": uid, "clip": str(path), "error": "CLIP_MISSING"})
            continue
        row = measured.get(uid) or measure_clip(path, **_kw_for(uid))
        row["unit_id"] = uid
        if uid in shots_of:
            row["editorial_shot_ids"] = shots_of[uid]
            row["dialogue_unit"] = dialogue_of.get(uid)
        rows.append(row)
        print(f"{uid}: {row.get('camera_class')} trans={row.get('translation_px_per_s_median')} zoom%/s={row.get('zoom_pct_per_s')} rev/s={row.get('reversals_per_s')}", flush=True)

    summary = summary_counts(rows)
    summary["editorial_shots"] = sum(len(v) for v in shots_of.values()) if shots_of else None
    summary["dialogue_units"] = sum(1 for r in rows if r.get("dialogue_unit"))
    summary["dialogue_units_locked_off"] = sum(1 for r in rows if r.get("dialogue_unit") and r.get("locked_off"))
    payload = {"schema": SCHEMA, "recorded_at": now(), "label": args.label, "thresholds": THRESHOLDS,
               "method": {"work_width": args.work_width, "min_inliers": args.min_inliers, "smooth_frames": args.smooth_frames,
                          "prominence_pct": args.prominence_pct, "prominence_zoom_pct": args.prominence_zoom_pct},
               "summary": summary, "rows": rows}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.md:
        args.md.write_text(markdown_table(rows, summary) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def shot_has_dialogue(shot: dict[str, Any]) -> bool:
    """In-video spoken line on a generation-contract shot (same reading as static_design_gate._dialogue)."""
    d = (shot.get("prompt_spec") or {}).get("dialogue")
    if isinstance(d, list):
        return any(str(x.get("text") if isinstance(x, dict) else x).strip() for x in d)
    return bool(str(d or "").strip())


def unit_has_dialogue(unit: dict[str, Any]) -> bool:
    """A unit is a dialogue unit when any of its rows carries a spoken line."""
    def has(value: Any) -> bool:
        return isinstance(value, str) and value.strip() != "" and value.strip().upper() not in {"NONE", "NULL"}
    for key in ("dialogue", "line", "dialogue_text", "speech"):
        if has(unit.get(key)):
            return True
    for key in ("dialogue_lines", "lines", "speaking"):
        value = unit.get(key)
        if isinstance(value, list) and any(has(v) or (isinstance(v, dict) and has(v.get("text") or v.get("line"))) for v in value):
            return True
    for shot in unit.get("shots") or unit.get("editorial_shots") or []:
        if isinstance(shot, dict) and (has(shot.get("dialogue")) or has(shot.get("line"))):
            return True
    beat = unit.get("narrative_beat")
    return has(beat) and any(marker in beat for marker in ("说", "问", "答", "开口", "喊", "道：", "念"))


if __name__ == "__main__":
    sys.exit(main())
