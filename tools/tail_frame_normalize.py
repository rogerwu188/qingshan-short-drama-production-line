#!/usr/bin/env python3
"""Undo H3 generational drift on a unit's real tail frame before it becomes the next unit's start frame.

Line owner 2026-11-20 (Korean E01, device …0080, live-action H3): inside one scene the male lead's face turned
"smeared with oil" from one unit to the next -- clean matte skin and dry hair at 0:36, glossy skin with specular
highlights, visible sweat / pores, wet-looking strands, higher contrast and crunchy over-sharpened texture at 0:39
(same framing, next unit).  Cause: successive units in a scene start from the previous unit's REAL final frame
(``extract_real_final_frame`` / ``bind_predecessor_tail_frame``).  An H3 output frame is compressed and
model-sharpened; fed back as @Image1 the model sharpens it again, so contrast, sharpening, specular sheen and noise
compound with every generation of the chain.

:func:`normalize_tail_frame` runs right after the OCR text clean (``tail_frame_text_clean``) at both extraction
points and pulls the tail back toward the scene's clean anchor -- the chain root's own generated keyframe (or, in the
supervisor, the unit's planned start keyframe):

* tone: Lab L / a / b spread matched toward the anchor with a blend strength (only ever LOWERED -- contrast and
  chroma creep), plus a small clamped a/b mean pull (colour drift); measured on skin when both images show skin
  (content-invariant across framings), else the whole frame at half strength.  The L mean is never moved, so a
  hard continuation does not get a brightness jump at its cut;
* sharpening: when the tail is sharper than the image its unit opened on (``start``: for a tail-started unit that is
  the predecessor's already-normalised tail, so no generation may out-sharpen the one before it; else the anchor),
  measured as Laplacian variance on the face / skin region at the tail's size, a Gaussian blend proportional to the
  excess -- no unsharp mask anywhere;
* noise: a mild edge-preserving bilateral filter on the same condition;
* specular sheen: a soft highlight knee on L inside the face / skin region (face box widened upward over the hair),
  knee at the anchor's own skin highlight level -- compresses highlights, never paints.

Every operation is per-pixel or a small symmetric filter: pose and geometry are untouched (no warping, no resize of
the tail).  The pre-normalisation frame is kept as ``<unit>.raw.png`` and ``<unit>.tail_normalize.json`` records
``tail_normalized`` and the before / after / anchor metrics.  Local only, zero credits.  Fail-open (any error keeps
the frame as it was); ``NALU_TAIL_NORMALIZE=0`` turns it off.

The same metrics drive the free S6 detector :func:`sheen_drift` (``QA-SKIN-SHEEN-DRIFT``, a finding for the final
review must-check list and the final fix round -- never a gate).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ENV_FLAG = "NALU_TAIL_NORMALIZE"
SCHEMA = "qingshan.tail_frame_normalize.v1"
DRIFT_SCHEMA = "qingshan.skin_sheen_drift.v1"

#: tone match strength (0 = none, 1 = full match) and clamps (L in 0..100, a/b in Lab units)
TONE_STRENGTH = 0.6
AB_MEAN_MAX_SHIFT = 2.5
STD_SCALE_MIN = 0.85
#: sharpening: tail/anchor Laplacian-variance ratio above which the tail is softened, and the blend cap
SHARP_RATIO_START = 1.15
SHARP_BLUR_SIGMA = 1.0
SHARP_BLEND_MAX = 0.65
SHARP_MAX_PASSES = 3
#: bilateral denoise (only when the tail is sharper / noisier than the anchor)
BILATERAL = {"d": 5, "sigmaColor": 14.0, "sigmaSpace": 3.0}
#: specular knee: L (0..100) above which skin highlights are compressed, and the slope above it
KNEE_FLOOR = 72.0
KNEE_DEFAULT = 82.0
KNEE_SLOPE = 0.35
#: a pixel counts as a specular highlight when L >= SPEC_L and chroma <= SPEC_CHROMA
SPEC_L = 88.0
SPEC_CHROMA = 14.0
MIN_SKIN_FRACTION = 0.004

#: drift thresholds (unit's frame vs its start frame / the chain anchor) -- advisory flags only
DRIFT_SPEC_DELTA = 0.02          # +2 % of the face region turned near-white specular
DRIFT_SHARP_RATIO = 1.8          # Laplacian variance on the face 1.8x the reference ...
DRIFT_CONTRAST_RATIO = 1.15      # ... together with 15 % more local contrast


def enabled(env: dict[str, str] | None = None) -> bool:
    value = str((env if env is not None else os.environ).get(ENV_FLAG, "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


def _warn(message: str) -> None:
    print(f"[tail_frame_normalize] WARNING: {message}", file=sys.stderr)


# ------------------------------------------------------------------------------------------------ regions
_CASCADE: Any = None


def _face_boxes(gray: Any) -> list[tuple[int, int, int, int]]:
    """OpenCV's bundled frontal-face Haar cascade (no download); [] when unavailable."""
    global _CASCADE
    import cv2  # noqa: PLC0415
    if _CASCADE is None:
        try:
            path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(str(path))
            _CASCADE = cascade if not cascade.empty() else False
        except Exception:  # noqa: BLE001 - no cascade: skin mask only
            _CASCADE = False
    if _CASCADE is False:
        return []
    h, w = gray.shape[:2]
    found = _CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(max(24, w // 20),) * 2)
    return [tuple(int(v) for v in box) for box in (found if len(found) else [])]


def skin_mask(image: Any) -> Any:
    """Soft 0..1 skin mask (YCrCb box, closed so specular holes inside skin are included)."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    ycc = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    raw = cv2.inRange(ycc, np.array([40, 135, 85], np.uint8), np.array([255, 175, 135], np.uint8))
    k = max(3, (min(image.shape[:2]) // 60) | 1)
    closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return closed.astype(np.float32) / 255.0


def face_region(image: Any) -> tuple[Any, str]:
    """(0..1 float mask, method): the face boxes widened (hair above, cheeks around) when the cascade finds a face,
    else the closed skin mask.  The mask covers skin AND its specular holes."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    boxes = _face_boxes(gray)
    if boxes:
        mask = np.zeros((h, w), np.float32)
        for x, y, bw, bh in boxes:
            x0, x1 = max(0, int(x - 0.15 * bw)), min(w, int(x + 1.15 * bw))
            y0, y1 = max(0, int(y - 0.45 * bh)), min(h, int(y + 1.1 * bh))
            mask[y0:y1, x0:x1] = 1.0
        return mask, "FACE_CASCADE"
    return skin_mask(image), "SKIN_MASK"


# ------------------------------------------------------------------------------------------------ metrics
def _lab(image: Any) -> Any:
    """float32 Lab with L in 0..100 and a/b centred on 0."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    return cv2.cvtColor(image.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)


def metrics(image: Any, region: Any | None = None) -> dict[str, Any]:
    """Sheen / sharpness / contrast measurements of one BGR frame (region: 0..1 mask, default face_region)."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    method = "GIVEN"
    if region is None:
        region, method = face_region(image)
    sel = region > 0.5
    h, w = image.shape[:2]
    frac = float(sel.mean())
    if frac < MIN_SKIN_FRACTION:
        sel, method = np.ones((h, w), bool), method + "_EMPTY_WHOLE_FRAME"
    lab = _lab(image)
    L = lab[..., 0]
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    local = gray - cv2.GaussianBlur(gray, (0, 0), 4.0)
    spec = (L >= SPEC_L) & (chroma <= SPEC_CHROMA)
    return {"region": method, "region_fraction": round(float(sel.mean()), 4),
            "specular_fraction": round(float(spec[sel].mean()), 4),
            "laplacian_var": round(float(lap[sel].var()), 2),
            "local_contrast": round(float(np.abs(local[sel]).mean()), 3),
            "l_mean": round(float(L[sel].mean()), 2), "l_std": round(float(L[sel].std()), 2),
            "l_p99": round(float(np.percentile(L[sel], 99)), 2),
            "global_l_std": round(float(L.std()), 2)}


def _ratio(a: float, b: float) -> float:
    return round(float(a) / float(b), 3) if b and b > 1e-6 else 0.0


def compare(subject: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    return {"specular_delta": round(subject["specular_fraction"] - reference["specular_fraction"], 4),
            "sharpness_ratio": _ratio(subject["laplacian_var"], reference["laplacian_var"]),
            "contrast_ratio": _ratio(subject["local_contrast"], reference["local_contrast"])}


def _same_framing(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Both measured on the same kind of region at a comparable size (face share within 2x)."""
    fa, fb = float(a.get("region_fraction") or 0), float(b.get("region_fraction") or 0)
    same_kind = str(a.get("region", "")).split("_EMPTY")[0] == str(b.get("region", "")).split("_EMPTY")[0]
    return same_kind and fa > 0 and fb > 0 and 0.5 <= fa / fb <= 2.0


def drifted(delta: dict[str, Any]) -> list[str]:
    reasons = []
    if delta["specular_delta"] >= DRIFT_SPEC_DELTA:
        reasons.append("SPECULAR_SHEEN")
    if delta["sharpness_ratio"] >= DRIFT_SHARP_RATIO and delta["contrast_ratio"] >= DRIFT_CONTRAST_RATIO:
        reasons.append("OVER_SHARPENED")
    return reasons


def _read(path: Path) -> Any:
    import cv2  # noqa: PLC0415
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode {path}")
    return image


def _fit(anchor: Any, shape: tuple[int, ...]) -> Any:
    import cv2  # noqa: PLC0415
    if anchor.shape[:2] == shape[:2]:
        return anchor
    return cv2.resize(anchor, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------------------------------- normalisation
def normalize_image(tail: Any, anchor: Any, start: Any | None = None) -> tuple[Any, dict[str, Any]]:
    """Pure: the normalised BGR tail and what was done.  Same size, same geometry.  ``start`` (optional) is the image
    the tail's own unit opened on -- the sharpness reference; the anchor is the tone / highlight reference."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    anchor = _fit(anchor, tail.shape)
    sharp_ref = _fit(start, tail.shape) if start is not None else anchor
    region_t, method_t = face_region(tail)
    region_a, method_a = face_region(anchor)
    skin_t, skin_a = skin_mask(tail) > 0.5, skin_mask(anchor) > 0.5
    ops: dict[str, Any] = {"region": method_t, "anchor_region": method_a}
    out = tail.astype(np.float32)

    # 1. sharpening / noise: soften by the measured excess only (region metrics, reference at the tail's size)
    mt, ma = metrics(tail, region_t), metrics(anchor, region_a)
    ms = ma if start is None else metrics(sharp_ref)
    ratio = _ratio(mt["laplacian_var"], ms["laplacian_var"])
    ops["sharpness_reference"] = "START_FRAME" if start is not None else "ANCHOR"
    ops["sharpness_ratio_before"] = ratio
    passes = []
    while ratio > SHARP_RATIO_START and len(passes) < SHARP_MAX_PASSES:
        alpha = float(min(SHARP_BLEND_MAX, (ratio - SHARP_RATIO_START) / 1.5 + 0.2))
        smooth = cv2.bilateralFilter(out, BILATERAL["d"], BILATERAL["sigmaColor"], BILATERAL["sigmaSpace"])
        blurred = cv2.GaussianBlur(smooth, (0, 0), SHARP_BLUR_SIGMA)
        out = out * (1.0 - alpha) + blurred * alpha
        ratio = _ratio(metrics(np.clip(out, 0, 255).astype(np.uint8), region_t)["laplacian_var"], ms["laplacian_var"])
        passes.append({"blend": round(alpha, 3), "ratio_after": ratio})
    if passes:
        ops["desharpen"] = {"passes": passes, "sigma": SHARP_BLUR_SIGMA, "bilateral": BILATERAL}

    # 2. tone: skin statistics when both frames show skin, else whole frame at half strength
    lab = cv2.cvtColor(np.clip(out, 0, 255) / 255.0, cv2.COLOR_BGR2Lab)
    lab_a = _lab(anchor)
    use_skin = skin_t.mean() >= MIN_SKIN_FRACTION and skin_a.mean() >= MIN_SKIN_FRACTION
    sel_t = skin_t if use_skin else np.ones(skin_t.shape, bool)
    sel_a = skin_a if use_skin else np.ones(skin_a.shape, bool)
    strength = TONE_STRENGTH if use_skin else TONE_STRENGTH / 2
    tone: dict[str, Any] = {"basis": "SKIN" if use_skin else "WHOLE_FRAME", "strength": strength}
    for ch, name, max_shift in ((0, "L", 0.0), (1, "a", AB_MEAN_MAX_SHIFT), (2, "b", AB_MEAN_MAX_SHIFT)):
        c = lab[..., ch]
        mu_t, sd_t = float(c[sel_t].mean()), float(c[sel_t].std())
        mu_a, sd_a = float(lab_a[..., ch][sel_a].mean()), float(lab_a[..., ch][sel_a].std())
        shift = float(np.clip((mu_a - mu_t) * strength, -max_shift, max_shift))
        scale = 1.0
        if sd_t > 1e-3 and sd_a < sd_t:  # only ever lower the spread (contrast / chroma drift)
            scale = float(max(STD_SCALE_MIN, 1.0 + (sd_a / sd_t - 1.0) * strength))
        lab[..., ch] = (c - mu_t) * scale + mu_t + shift
        tone[name] = {"shift": round(shift, 3), "scale": round(scale, 4)}
    ops["tone"] = tone

    # 3. specular knee on L inside the face / skin region (soft mask), knee at the anchor's skin highlight level
    knee = float(np.clip(ma["l_p99"], KNEE_FLOOR, 95.0)) if ma["region_fraction"] >= MIN_SKIN_FRACTION else KNEE_DEFAULT
    soft = cv2.GaussianBlur(np.maximum(region_t, skin_t.astype(np.float32)), (0, 0), 3.0)
    L = lab[..., 0]
    over = np.maximum(L - knee, 0.0)
    lab[..., 0] = L - over * (1.0 - KNEE_SLOPE) * soft
    # specular highlights are desaturated: keep their chroma where they were compressed (no painting)
    ops["specular_knee"] = {"knee_L": round(knee, 2), "slope": KNEE_SLOPE,
                            "pixels_compressed": int(((over > 0) & (soft > 0.5)).sum())}
    lab[..., 0] = np.clip(lab[..., 0], 0.0, 100.0)
    result = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2BGR) * 255.0, 0, 255).round().astype(np.uint8)
    return result, ops


def normalize_tail_frame(frame: Path, *, anchor: Path | None, raw_copy: Path, sidecar: Path | None = None,
                         start: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Normalise ``frame`` in place toward ``anchor`` (sharpness capped at ``start``, the image the tail's unit opened
    on, when given); ``raw_copy`` receives the untouched frame.  Never raises."""
    started = time.perf_counter()
    report: dict[str, Any] = {"schema": SCHEMA, "tail_normalized": False,
                              "anchor": str(anchor) if anchor else None,
                              "start_frame": str(start) if start else None}
    try:  # a re-extracted frame must not inherit a stale raw copy
        raw_copy.unlink(missing_ok=True)
    except OSError:
        pass

    def done(status: str, **extra: Any) -> dict[str, Any]:
        report.update(status=status, elapsed_ms=round((time.perf_counter() - started) * 1000, 1), **extra)
        if sidecar is not None:
            try:
                sidecar.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError as exc:
                _warn(f"sidecar {sidecar} not written: {exc}")
        return report

    if not enabled(env):
        return done("SKIPPED_OPT_OUT")
    if anchor is None or not Path(anchor).is_file():
        return done("NO_ANCHOR")
    try:
        import cv2  # noqa: PLC0415
        tail_img, anchor_img = _read(frame), _read(Path(anchor))
        start_img = _read(Path(start)) if start is not None and Path(start).is_file() else None
        before = metrics(tail_img)
        anchor_m = metrics(_fit(anchor_img, tail_img.shape))
        result, ops = normalize_image(tail_img, anchor_img, start_img)
        after = metrics(result)
        shutil.copyfile(frame, raw_copy)
        tmp = frame.with_name(frame.stem + ".norm" + frame.suffix)
        if not cv2.imwrite(str(tmp), result):
            tmp.unlink(missing_ok=True)
            raise OSError(f"cannot write {tmp}")
        os.replace(tmp, frame)
    except Exception as exc:  # noqa: BLE001 - fail-open: keep the frame as it was
        try:
            raw_copy.unlink(missing_ok=True)
        except OSError:
            pass
        _warn(f"tail-frame normalisation skipped for {frame} ({type(exc).__name__}: {exc}); frame kept")
        return done("FAIL_OPEN", error=f"{type(exc).__name__}: {exc}")
    report["tail_normalized"] = True
    return done("NORMALIZED", raw=str(raw_copy), ops=ops,
                stats={"before": before, "after": after, "anchor": anchor_m,
                       "drift_before": compare(before, anchor_m), "drift_after": compare(after, anchor_m)})


def companion_paths(final: Path) -> tuple[Path, Path]:
    """(``<unit>.raw.png``, ``<unit>.tail_normalize.json``) next to the final tail frame."""
    return final.with_name(f"{final.stem}.raw{final.suffix}"), final.with_name(f"{final.stem}.tail_normalize.json")


# ------------------------------------------------------------------------------------------------ detector
def clip_frames(clip: Path, offsets: tuple[str, ...] = ("0.5", "-0.10")) -> list[Any]:
    """Decoded BGR frames of ``clip`` at the given offsets (positive = from start, negative = from end)."""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    try:
        try:
            from tools.media_binary import resolve_media_binary  # noqa: PLC0415
        except ImportError:  # engine tools/ on sys.path (nalu runtime)
            from media_binary import resolve_media_binary  # type: ignore  # noqa: PLC0415
        ffmpeg = str(resolve_media_binary("ffmpeg"))
    except Exception:  # noqa: BLE001
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    frames = []
    with tempfile.TemporaryDirectory(prefix="sheen_") as tmp:
        for i, off in enumerate(offsets):
            dst = Path(tmp) / f"f{i}.png"
            seek = ["-sseof", off] if off.startswith("-") else ["-ss", off]
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *seek, "-i", str(clip),
                            "-frames:v", "1", str(dst)], check=False, timeout=60)
            if dst.is_file() and dst.stat().st_size > 0:
                frames.append(_read(dst))
    return frames


def sheen_drift(clip: Path, references: dict[str, Path | None], *, frames: list[Any] | None = None) -> dict[str, Any]:
    """QA-SKIN-SHEEN-DRIFT measurement of one landed unit: an early and the last frame of the clip vs each
    reference (``start_frame`` = the image the unit opened on, ``anchor`` = the scene's clean keyframe).  Flagged
    when any comparison crosses the drift thresholds.  Advisory, free, never raises."""
    started = time.perf_counter()
    out: dict[str, Any] = {"schema": DRIFT_SCHEMA, "flagged": False, "reasons": [], "comparisons": {}}
    try:
        frames = frames if frames is not None else clip_frames(clip)
        if not frames:
            return {**out, "status": "NO_FRAMES"}
        measured = [metrics(f) for f in frames]
        reasons: set[str] = set()
        for name, ref in references.items():
            if ref is None or not Path(ref).is_file():
                continue
            ref_m = metrics(_fit(_read(Path(ref)), frames[0].shape))
            # a reference of another framing (wide vs close-up) measures the framing, not the skin: skip it
            rows = [compare(m, ref_m) for m in measured if _same_framing(m, ref_m)]
            if not rows:
                out["comparisons"][name] = {"reference": str(ref), "skipped": "FRAMING_DIFFERS"}
                continue
            worst = {"specular_delta": max(r["specular_delta"] for r in rows),
                     "sharpness_ratio": max(r["sharpness_ratio"] for r in rows),
                     "contrast_ratio": max(r["contrast_ratio"] for r in rows)}
            got = sorted({x for r in rows for x in drifted(r)})
            out["comparisons"][name] = {"reference": str(ref), "worst": worst, "reasons": got}
            reasons.update(got)
        measured_any = any("worst" in c for c in out["comparisons"].values())
        out.update(status="MEASURED" if measured_any else "NO_COMPARABLE_REFERENCE", flagged=bool(reasons),
                   reasons=sorted(reasons), frames=measured,
                   thresholds={"specular_delta": DRIFT_SPEC_DELTA, "sharpness_ratio": DRIFT_SHARP_RATIO,
                               "contrast_ratio": DRIFT_CONTRAST_RATIO})
    except Exception as exc:  # noqa: BLE001 - advisory
        out.update(status="ERROR", error=f"{type(exc).__name__}: {str(exc)[:160]}")
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("normalize")
    n.add_argument("frame", type=Path)
    n.add_argument("--anchor", type=Path, required=True)
    n.add_argument("--start-frame", type=Path)
    m = sub.add_parser("metrics")
    m.add_argument("image", type=Path)
    d = sub.add_parser("drift")
    d.add_argument("clip", type=Path)
    d.add_argument("--start-frame", type=Path)
    d.add_argument("--anchor", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "normalize":
        raw, side = companion_paths(args.frame)
        result = normalize_tail_frame(args.frame, anchor=args.anchor, raw_copy=raw, sidecar=side,
                                      start=args.start_frame)
    elif args.cmd == "metrics":
        result = metrics(_read(args.image))
    else:
        result = sheen_drift(args.clip, {"start_frame": args.start_frame, "anchor": args.anchor})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
