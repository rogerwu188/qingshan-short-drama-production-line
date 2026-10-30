#!/usr/bin/env python3
"""clip_lockoff_stabilize.py — turn an already-generated unit clip into a locked-off shot, or smooth it.

Roger 2026-10-30 (E12 成片审看, item 2): dialogue units default to static / locked-off camera; clips that
are already paid for get a stabilisation pass instead of a reroll (no identical-prompt reroll, K130).

Two modes, chosen per clip from the measured camera path (camera_motion_metrics.frame_transforms):

  LOCK_OFF   cancel the cumulative global similarity motion (translation + rotation + scale) relative to the
             first frame, warp every frame back onto the first frame's framing, crop to the region that stays
             valid in every frame, rescale to the output size.  Chosen when the crop needed is <= --max-crop
             (default 20 % per axis).  The result is what a tripod would have recorded: the scene content
             (actors, cloth, petals) still moves, the frame does not.
  SMOOTH     when lock-off would crop more than --max-crop (a long dolly), keep the slow intended move and
             remove only jitter / direction reversals: the camera path is low-pass filtered (moving average
             over --smooth-seconds, default 1.0 s) and each frame is warped by (smoothed - measured), with
             the same common-valid-region crop.  This is the vidstab idea done on the measured similarity
             path; ffmpeg's libvidstab is not in the default build (see --engine ffmpeg-vidstab for the
             brew ffmpeg-full binary when present).
  NONE       the clip is already locked-off; copied through untouched.

Audio is copied bit-exact (``-c:a copy``); the video stream is re-encoded with libx264 at --crf (default 16)
and the source fps.  Nothing is written over the source clip; outputs go to --out-dir/<name>.mp4 plus a
provenance JSON per clip recording mode, measured path extent, crop %, source and output sha256, and the
before/after camera metrics so the S7 integration can bind them.

Face guard: when --face-guard is on (default), faces are detected (InsightFace buffalo_l if importable,
else OpenCV Haar) on sampled source frames; if the lock-off crop would cut into any detected face box the
clip falls back to SMOOTH and the provenance says FACE_GUARD_FALLBACK.

Usage
  clip_lockoff_stabilize.py --clip <in.mp4> [--clip ...] --out-dir <dir> [--max-crop 0.20]
                            [--smooth-seconds 1.0] [--out-size 720x1280] [--force-mode LOCK_OFF|SMOOTH]
  clip_lockoff_stabilize.py --clips-dir <dir> --timeline <release_timeline.json> --out-dir <dir>
  Exit 0 when every clip produced an output; 1 on any failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_motion_metrics as cmm  # noqa: E402

SCHEMA = "nalu.clip_lockoff_stabilize.v1"
FFMPEG = os.environ.get("NALU_FFMPEG", "ffmpeg")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- camera path
def cumulative_path(deltas: list[dict[str, Any]]) -> list[tuple[float, float, float, float]]:
    """(x, y, logscale, theta) of frame i relative to frame 0 (native pixels); frame 0 = (0,0,0,0)."""
    x = y = z = th = 0.0
    path = [(0.0, 0.0, 0.0, 0.0)]
    for d in deltas:
        x += float(d["dx"]); y += float(d["dy"]); z += float(d["dlogscale"]); th += float(d["dtheta"])
        path.append((x, y, z, th))
    return path


def smooth_path(path: list[tuple[float, float, float, float]], window: int) -> list[tuple[float, float, float, float]]:
    if window <= 1:
        return list(path)
    arr = np.array(path, dtype=np.float64)
    out = np.empty_like(arr)
    half = window // 2
    for i in range(len(arr)):
        lo, hi = max(0, i - half), min(len(arr), i + half + 1)
        out[i] = arr[lo:hi].mean(axis=0)
    return [tuple(map(float, row)) for row in out]


def similarity_matrix(dx: float, dy: float, logscale: float, theta: float, cx: float, cy: float) -> np.ndarray:
    """2x3 matrix mapping the first-frame coordinate system to the current frame (about the frame centre)."""
    s = math.exp(logscale)
    c, sn = math.cos(theta), math.sin(theta)
    a, b = s * c, s * sn
    # p' = R*(p - C) + C + t
    m = np.array([[a, -b, cx - a * cx + b * cy + dx],
                  [b, a, cy - b * cx - a * cy + dy]], dtype=np.float64)
    return m


def invert_affine(m: np.ndarray) -> np.ndarray:
    full = np.vstack([m, [0.0, 0.0, 1.0]])
    return np.linalg.inv(full)[:2]


def valid_region(correction: list[np.ndarray], width: int, height: int) -> tuple[int, int, int, int]:
    """Largest axis-aligned rectangle (x0, y0, x1, y1) that stays inside every warped frame.

    Each correction maps source → stabilised; the stabilised frame is valid where the inverse lands inside
    the source.  Conservative estimate from the four warped source corners: the intersection over frames of
    the inscribed rectangle of the warped quadrilateral."""
    x0, y0, x1, y1 = 0.0, 0.0, float(width), float(height)
    corners = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float64)
    for m in correction:
        pts = (m[:, :2] @ corners.T).T + m[:, 2]
        # inscribed rectangle of a (nearly rectangular) quad: take the inner-most of each edge's two endpoints
        left = max(pts[0, 0], pts[3, 0]); right = min(pts[1, 0], pts[2, 0])
        top = max(pts[0, 1], pts[1, 1]); bottom = min(pts[2, 1], pts[3, 1])
        x0, y0, x1, y1 = max(x0, left), max(y0, top), min(x1, right), min(y1, bottom)
    x0, y0 = int(math.ceil(x0)), int(math.ceil(y0))
    x1, y1 = int(math.floor(x1)), int(math.floor(y1))
    return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


def fit_aspect(region: tuple[int, int, int, int], width: int, height: int, aspect_w: int, aspect_h: int) -> tuple[int, int, int, int]:
    """Shrink the valid region to the output aspect ratio, centred, so the rescale does not distort."""
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    target = aspect_w / aspect_h
    if rw / rh > target:  # too wide
        nw = int(math.floor(rh * target)); dx = (rw - nw) // 2
        x0, x1 = x0 + dx, x0 + dx + nw
    else:
        nh = int(math.floor(rw / target)); dy = (rh - nh) // 2
        y0, y1 = y0 + dy, y0 + dy + nh
    return x0, y0, x1, y1


# --------------------------------------------------------------------------- faces
_FACE_APP = None


def detect_faces(frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    global _FACE_APP
    try:
        if _FACE_APP is None:
            from insightface.app import FaceAnalysis  # type: ignore
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=(640, 640))
            _FACE_APP = app
        faces = _FACE_APP.get(frame_bgr)
        return [tuple(int(v) for v in f.bbox) for f in faces if float(getattr(f, "det_score", 1.0)) >= 0.5]
    except Exception:  # noqa: BLE001 — fall back to Haar
        if _FACE_APP is None:
            _FACE_APP = False
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    grey = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    boxes = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    return [(int(x), int(y), int(x + w), int(y + h)) for (x, y, w, h) in boxes]


def face_boxes_sampled(path: Path, frame_count: int, *, samples: int = 6) -> list[dict[str, Any]]:
    cap = cv2.VideoCapture(str(path))
    idxs = sorted({int(round(i * (frame_count - 1) / max(1, samples - 1))) for i in range(samples)})
    out = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        for box in detect_faces(frame):
            out.append({"frame": idx, "box": list(box)})
    cap.release()
    return out


def crop_cuts_face(region: tuple[int, int, int, int], faces: list[dict[str, Any]], corrections: list[np.ndarray]) -> bool:
    x0, y0, x1, y1 = region
    for f in faces:
        m = corrections[min(f["frame"], len(corrections) - 1)]
        bx0, by0, bx1, by1 = f["box"]
        pts = np.array([[bx0, by0], [bx1, by0], [bx1, by1], [bx0, by1]], dtype=np.float64)
        warped = (m[:, :2] @ pts.T).T + m[:, 2]
        wx0, wy0 = warped[:, 0].min(), warped[:, 1].min()
        wx1, wy1 = warped[:, 0].max(), warped[:, 1].max()
        if wx0 < x0 or wy0 < y0 or wx1 > x1 or wy1 > y1:
            return True
    return False


# --------------------------------------------------------------------------- stabilise one clip
def stabilize_clip(src: Path, out_dir: Path, *, max_crop: float = 0.20, smooth_seconds: float = 1.0,
                   out_size: tuple[int, int] = (720, 1280), crf: int = 16, force_mode: str | None = None,
                   face_guard: bool = True, work_width: int = 384) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / src.name
    prov_path = out_dir / f"{src.stem}.stabilize.json"
    params = {"max_crop": max_crop, "smooth_seconds": smooth_seconds, "out_size": list(out_size), "crf": crf,
              "face_guard": face_guard}
    if prov_path.is_file() and dst.is_file():
        # idempotent re-entry (S7 re-run after a repair): same source bytes, same parameters, output intact -> reuse
        try:
            prior = json.loads(prov_path.read_text(encoding="utf-8"))
        except ValueError:
            prior = {}
        if (prior.get("source_sha256") == sha256_file(src) and prior.get("params") == params
                and prior.get("output_sha256") == sha256_file(dst)):
            return dict(prior, reused=True)
    tf = cmm.frame_transforms(src, work_width=work_width)
    before = cmm.summarise(src, tf)
    fps, width, height, frames = tf["fps"], tf["width"], tf["height"], tf["frames"]
    path = cumulative_path(tf["deltas"])
    cx, cy = width / 2.0, height / 2.0

    def corrections_for(target: list[tuple[float, float, float, float]]) -> list[np.ndarray]:
        rows = []
        for measured, wanted in zip(path, target):
            m_meas = similarity_matrix(*measured, cx, cy)       # frame0 → frame i
            m_want = similarity_matrix(*wanted, cx, cy)          # frame0 → wanted framing of frame i
            # source pixel p_i = m_meas(p0); stabilised pixel q = m_want(p0) → q = m_want(inv(m_meas)(p_i))
            inv = invert_affine(m_meas)
            full = np.vstack([m_want, [0, 0, 1]]) @ np.vstack([inv, [0, 0, 1]])
            rows.append(full[:2])
        return rows

    # ---- LOCK_OFF candidate: every frame back to frame 0
    lock_target = [(0.0, 0.0, 0.0, 0.0)] * len(path)
    lock_corr = corrections_for(lock_target)
    lock_region = valid_region(lock_corr, width, height)
    crop_x = 1.0 - (lock_region[2] - lock_region[0]) / width
    crop_y = 1.0 - (lock_region[3] - lock_region[1]) / height
    faces = face_boxes_sampled(src, frames) if face_guard else []
    reasons: list[str] = []
    mode = force_mode
    if mode is None:
        if before.get("locked_off"):
            mode = "NONE"; reasons.append("ALREADY_LOCKED_OFF")
        elif max(crop_x, crop_y) <= max_crop:
            mode = "LOCK_OFF"
            if faces and crop_cuts_face(fit_aspect(lock_region, width, height, *out_size), faces, lock_corr):
                mode = "SMOOTH"; reasons.append("FACE_GUARD_FALLBACK")
        else:
            mode = "SMOOTH"; reasons.append(f"LOCK_OFF_CROP_{max(crop_x, crop_y):.3f}_OVER_{max_crop}")
    if mode == "SMOOTH":
        window = max(3, int(round(smooth_seconds * fps)) | 1)
        target = smooth_path(path, window)
        corr = corrections_for(target)
        region = valid_region(corr, width, height)
    elif mode == "LOCK_OFF":
        corr, region = lock_corr, lock_region
    else:
        corr, region = [], (0, 0, width, height)
    region = fit_aspect(region, width, height, *out_size)
    crop = {"x_pct": round(100 * (1 - (region[2] - region[0]) / width), 2),
            "y_pct": round(100 * (1 - (region[3] - region[1]) / height), 2),
            "region": list(region)}
    # E12 batch (2026-10-30): SMOOTH on a large generated dolly/arc/track (path extent ~ a frame width, parallax,
    # actors dominating the tracked features) needed 22-94 % crops and often ADDED reversals.  The crop cap
    # applies to SMOOTH too; a smooth that must crop more than --max-crop is not a repair, so the clip passes
    # through untouched (NONE) and the provenance says why.  A regression guard after the render does the same.
    if mode == "SMOOTH" and max(crop["x_pct"], crop["y_pct"]) > 100 * max_crop and force_mode is None:
        reasons.append(f"SMOOTH_CROP_{max(crop['x_pct'], crop['y_pct']):.1f}PCT_OVER_{100 * max_crop:g}")
        mode = "NONE"
        corr, region = [], fit_aspect((0, 0, width, height), width, height, *out_size)
        crop = {"x_pct": 0.0, "y_pct": 0.0, "region": list(region)}

    def passthrough() -> None:
        """NONE: the source bytes when the raster already matches (no generation loss), else a rescale; audio copied."""
        if (width, height) == out_size:
            shutil.copyfile(src, dst)
            return
        cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-vf", f"scale={out_size[0]}:{out_size[1]}:flags=lanczos",
               "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "copy",
               "-movflags", "+faststart", str(dst)]
        subprocess.run(cmd, check=True)

    if mode == "NONE":
        passthrough()
    else:
        with tempfile.TemporaryDirectory(prefix="lockoff_") as td:
            raw = Path(td) / "video.mp4"
            cap = cv2.VideoCapture(str(src))
            writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, out_size)
            idx = 0
            x0, y0, x1, y1 = region
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                m = corr[min(idx, len(corr) - 1)]
                warped = cv2.warpAffine(frame, m, (width, height), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT101)
                cropped = warped[y0:y1, x0:x1]
                writer.write(cv2.resize(cropped, out_size, interpolation=cv2.INTER_LANCZOS4))
                idx += 1
            cap.release(); writer.release()
            cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-i", str(src), "-map", "0:v:0", "-map", "1:a:0?",
                   "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", f"{fps:g}",
                   "-c:a", "copy", "-movflags", "+faststart", str(dst)]   # no -shortest: it dropped the last AAC packet (E12: 229→228)
            subprocess.run(cmd, check=True)
    after_tf = cmm.frame_transforms(dst, work_width=work_width)
    after = cmm.summarise(dst, after_tf)
    if mode != "NONE" and force_mode is None and (
            float(after.get("reversals_per_s") or 0) > float(before.get("reversals_per_s") or 0)
            or (after.get("unstable") and not before.get("unstable"))):
        # regression guard: a "repair" that measures worse than the source is discarded, source passes through
        reasons.append(f"REGRESSION_GUARD_rev_{before.get('reversals_per_s')}_to_{after.get('reversals_per_s')}")
        mode = "NONE"
        passthrough()
        after = cmm.summarise(dst, cmm.frame_transforms(dst, work_width=work_width))
        crop = {"x_pct": 0.0, "y_pct": 0.0, "region": [0, 0, width, height]}
    prov = {
        "schema": SCHEMA, "recorded_at": now(), "source": str(src), "source_sha256": sha256_file(src),
        "output": str(dst), "output_sha256": sha256_file(dst), "mode": mode, "reasons": reasons,
        "params": {"max_crop": max_crop, "smooth_seconds": smooth_seconds, "out_size": list(out_size), "crf": crf,
                   "face_guard": face_guard},
        "lock_off_crop_needed": {"x_pct": round(100 * crop_x, 2), "y_pct": round(100 * crop_y, 2)},
        "crop_applied": crop, "faces_sampled": len(faces),
        "audio": "copied bit-exact (-c:a copy)",
        "before": {k: before.get(k) for k in ("translation_px_per_s_median", "zoom_pct_per_s", "reversals_per_s", "camera_class", "locked_off", "unstable")},
        "after": {k: after.get(k) for k in ("translation_px_per_s_median", "zoom_pct_per_s", "reversals_per_s", "camera_class", "locked_off", "unstable")},
    }
    prov_path.write_text(json.dumps(prov, ensure_ascii=False, indent=2), encoding="utf-8")
    return prov


def _stabilize_one(clip: str, out_dir: str, kw: dict[str, Any]) -> dict[str, Any]:
    """ProcessPool entry (module-level so it pickles)."""
    return stabilize_clip(Path(clip), Path(out_dir), **kw)


def applied_sources(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """unit -> provenance row whose mode changed the picture (LOCK_OFF / SMOOTH) and whose output still exists
    with the recorded sha — the shape the AgentCut builder's derived-clip hooks consume (--stabilized-clips)."""
    out: dict[str, dict[str, Any]] = {}
    for row in summary.get("results") or []:
        if row.get("mode") in (None, "NONE"):
            continue
        target = Path(str(row.get("output") or ""))
        if target.is_file() and sha256_file(target) == row.get("output_sha256"):
            out[Path(str(row.get("source"))).stem] = row
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, action="append")
    ap.add_argument("--clips-dir", type=Path)
    ap.add_argument("--timeline", type=Path)
    ap.add_argument("--only", action="append", help="unit id(s) to process when using --clips-dir")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--max-crop", type=float, default=0.20)
    ap.add_argument("--smooth-seconds", type=float, default=1.0)
    ap.add_argument("--out-size", default="720x1280")
    ap.add_argument("--crf", type=int, default=16)
    ap.add_argument("--force-mode", choices=["LOCK_OFF", "SMOOTH", "NONE"])
    ap.add_argument("--no-face-guard", action="store_true")
    ap.add_argument("--summary", type=Path, help="write a batch summary JSON here")
    ap.add_argument("--workers", type=int, default=1, help="stabilise clips in N processes (independent clips)")
    args = ap.parse_args(argv)
    w, h = (int(v) for v in args.out_size.lower().split("x"))
    clips: list[Path] = list(args.clip or [])
    if args.clips_dir:
        if args.timeline:
            tl = json.loads(args.timeline.read_text(encoding="utf-8"))
            ids = [str(s.get("unit_id")) for s in tl.get("segments") or []]
        else:
            ids = [p.stem for p in sorted(args.clips_dir.glob("*.mp4"))]
        if args.only:
            ids = [i for i in ids if i in set(args.only)]
        clips += [args.clips_dir / f"{i}.mp4" for i in ids]
    if not clips:
        ap.error("no clips")
    results, failures = [], []
    kw = dict(max_crop=args.max_crop, smooth_seconds=args.smooth_seconds, out_size=(w, h), crf=args.crf,
              force_mode=args.force_mode, face_guard=not args.no_face_guard)

    def _report(clip: Path, prov: dict[str, Any] | None, exc: BaseException | None) -> None:
        if prov is not None:
            results.append(prov)
            print(f"{clip.stem}: {prov['mode']} crop={prov['crop_applied']['x_pct']}/{prov['crop_applied']['y_pct']}% "
                  f"{prov['before']['camera_class']} -> {prov['after']['camera_class']} rev/s {prov['before']['reversals_per_s']} -> {prov['after']['reversals_per_s']}", flush=True)
        else:
            failures.append({"clip": str(clip), "error": f"{type(exc).__name__}:{exc}"})
            print(f"{clip.stem}: FAILED {type(exc).__name__}: {exc}", flush=True)

    if args.workers > 1 and len(clips) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [(clip, pool.submit(_stabilize_one, str(clip), str(args.out_dir), kw)) for clip in clips]
            for clip, fut in futures:
                try:
                    _report(clip, fut.result(), None)
                except Exception as exc:  # noqa: BLE001
                    _report(clip, None, exc)
    else:
        for clip in clips:
            try:
                _report(clip, stabilize_clip(clip, args.out_dir, **kw), None)
            except Exception as exc:  # noqa: BLE001
                _report(clip, None, exc)
    summary = {"schema": SCHEMA + ".batch", "recorded_at": now(), "out_dir": str(args.out_dir),
               "processed": len(results), "failed": failures,
               "modes": {m: sum(1 for r in results if r["mode"] == m) for m in ("LOCK_OFF", "SMOOTH", "NONE")},
               "locked_off_before": sum(1 for r in results if r["before"].get("locked_off")),
               "locked_off_after": sum(1 for r in results if r["after"].get("locked_off")),
               "unstable_before": sum(1 for r in results if r["before"].get("unstable")),
               "unstable_after": sum(1 for r in results if r["after"].get("unstable")),
               "results": results}
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
