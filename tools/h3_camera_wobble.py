#!/usr/bin/env python3
"""S6 camera-wobble check of MiniMax-H3 clips (line owner 2026-11-21, Korean live-action line, device ...0080).

"In the latest episode the camera shakes along with a character's small movements -- the person AND the background
move together."  H3 image-to-video sometimes couples the whole frame to the subject: a nod, a gesture or a half step
drags the background with it (fake handheld / whole-frame warp) even when the unit's camera plan is locked off.  The
existing camera metrics (lines/nalu/runtime/tools/camera_motion_metrics.py) fit ONE similarity to the whole frame;
on a medium / close shot the actor dominates the tracked features, so a coupled wobble reads as "the subject moved"
and a mild one (a few pixels back and forth) stays under the LOCKED_OFF thresholds.

This module measures the BACKGROUND on its own, for free (OpenCV + numpy, ~1 s per clip):

* frames sampled at :data:`SAMPLE_FPS`, grey, downscaled to :data:`WORK_WIDTH`;
* the people are masked out: face boxes (OpenCV Haar, sampled frames) grown into body boxes (wide, down to the bottom
  of the frame) and unioned over the clip; with no face found, a central column is masked instead;
* per frame pair: dense optical flow (Farneback); the BACKGROUND motion is the median flow over the unmasked
  pixels, the SUBJECT motion the median magnitude of the flow inside the mask after removing the background motion;
* the background path (cumulative median flow) gives the excursion (peak-to-peak, % of frame width), the jitter
  (path minus its ~1 s moving average, RMS, % width) and the direction reversals per second; the coupling is the
  Pearson correlation between the background speed and the subject motion per frame pair.

Verdict for a unit whose camera plan is static / locked off (:func:`classify`):

  WOBBLE          excursion >= EXCURSION_MIN_PCT and (coupling >= COUPLING_MIN or reversals >= REVERSALS_MIN_S
                  or jitter >= JITTER_MIN_PCT): the background moves, back and forth or with the actor.
                  ``severity`` MILD (excursion <= MILD_MAX_PCT, a <= 5 % lock-off crop can cancel it) or STRONG.
  CLEAN           the background stays put (or drifts once, slowly -- a push-in / drift is the Q2 camera checks'
                  business, not a wobble).
  NOT_MEASURABLE  too little background (< MIN_BACKGROUND_SHARE of the frame) or too few frame pairs.
  FAIL_OPEN       OpenCV / numpy missing or the clip cannot be read: treated as clean by the caller.
  NOT_STATIC_PLAN a unit with a deliberate camera move is not measured (its move is authored).

The S6 wiring (nalu_pipeline.s6_burn_check_landed) retries a WOBBLE take ONCE through the burned-text retry
plumbing (PR #278 / #287: ``s6_burn_retry`` record, parked take, ``h3_burn_retry`` index -> perturbed @Image1) with
the locked-off retry sentence (:data:`RETRY_SENTENCES`); a wobble that survives is kept (best take), marked
``camera_wobble_unresolved``, stabilised in S7 when MILD (clip_lockoff_stabilize, crop <= 5 %) and joins the final
fix round (QA-CAMERA-WOBBLE).  Never a gate.

Env: ``NALU_S6_WOBBLE_RETRY_MAX`` (default 1; 0 disables the wobble retry, the measurement still runs).
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

SCHEMA = "qingshan.s6_camera_wobble_detect.v1"
FLAG = "camera_wobble"  # == h3_burn_retry.WOBBLE_FLAG
UNRESOLVED_FLAG = "camera_wobble_unresolved"
TASK_FIELD = "h3_camera_wobble_retry"
ENV_MAX = "NALU_S6_WOBBLE_RETRY_MAX"
DEFAULT_MAX = 1
SAMPLE_FPS = 12.0
WORK_WIDTH = 240
FACE_SAMPLES = 6
MIN_PAIRS = 8
MIN_BACKGROUND_SHARE = 0.12

#: thresholds (calibrated 2026-11-21 on local H3 clips: locked-off takes and their lock-off-stabilised copies stay
#: under 0.5 % excursion / 0.1 % jitter; a coupled wobble moves the background >= 1 % of the width and back)
EXCURSION_MIN_PCT = 0.8      # background path peak-to-peak, % of frame width (~6 px on a 720-wide clip)
COUPLING_MIN = 0.45          # Pearson(background speed, subject motion) per frame pair
REVERSALS_MIN_S = 0.6        # background direction reversals per second (prominence REVERSAL_PROMINENCE_PCT)
JITTER_MIN_PCT = 0.25        # RMS of the background path around its ~1 s moving average, % width
REVERSAL_PROMINENCE_PCT = 0.3
MILD_MAX_PCT = 3.0           # a wobble whose excursion fits a <= 5 % lock-off crop (both sides) is MILD
STABILIZE_MAX_CROP = 0.05    # S7 stabilisation of a MILD wobble never crops more than this per axis

THRESHOLDS = {"excursion_min_pct": EXCURSION_MIN_PCT, "coupling_min": COUPLING_MIN,
              "reversals_min_per_s": REVERSALS_MIN_S, "jitter_min_pct": JITTER_MIN_PCT,
              "reversal_prominence_pct": REVERSAL_PROMINENCE_PCT, "mild_max_pct": MILD_MAX_PCT,
              "min_background_share": MIN_BACKGROUND_SHARE}

#: retry index -> the locked-off sentence appended to the provider prompt (kept in h3_burn_retry, whose retry
#: plumbing carries it: WOBBLE_RETRY_SENTENCES)
from h3_burn_retry import WOBBLE_RETRY_SENTENCES as RETRY_SENTENCES  # noqa: E402

#: camera-plan motion families that are a locked-off camera
STATIC_FAMILIES = frozenset({"STATIC", "LOCKED", "LOCKED_OFF", "FIXED", "NONE", ""})


def max_retries(env: dict[str, str] | None = None) -> int:
    raw = str((env if env is not None else os.environ).get(ENV_MAX, DEFAULT_MAX)).strip()
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_MAX


def retry_sentence(index: int) -> str:
    if index <= 0:
        return ""
    return RETRY_SENTENCES.get(index) or RETRY_SENTENCES[max(RETRY_SENTENCES)]


def requested(payload: dict[str, Any] | None) -> bool:
    """A task / prompt unit asks for the wobble retry sentence (its latest S6 retry followed a camera wobble)."""
    payload = payload or {}
    return bool(payload.get(TASK_FIELD) or (payload.get("machine_contract") or {}).get(TASK_FIELD))


def _plans(task: dict[str, Any] | None) -> list[dict[str, Any]]:
    task = task or {}
    machine = task.get("machine_contract") or {}
    out: list[dict[str, Any]] = []
    for source in (task, machine):
        for key in ("camera_plans", "per_shot_camera_plans"):
            out += [p for p in source.get(key) or [] if isinstance(p, dict)]
        if isinstance(source.get("camera_plan"), dict):
            out.append(source["camera_plan"])
    for spec in task.get("ordered_prompt_specs") or machine.get("ordered_prompt_specs") or []:
        if isinstance(spec, dict) and isinstance(spec.get("camera_plan"), dict):
            out.append(spec["camera_plan"])
    return out


def static_plan(task: dict[str, Any] | None) -> bool | None:
    """True when every camera plan of a compiled task is locked off (STATIC / LOCKED), False when any plan declares a
    move, None when the task carries no camera plan (unknown: not measured)."""
    plans = _plans(task)
    if not plans:
        return None
    return all(str(p.get("motion_family") or "STATIC").strip().upper() in STATIC_FAMILIES for p in plans)


# --------------------------------------------------------------------------------------------- measurement
#: frame reader: video path, fps -> iterable of (time_s, BGR ndarray)
FrameReader = Callable[[Path, float], Iterable[Any]]


def _cv2_frames(video: Path, fps: float):
    import cv2  # noqa: PLC0415
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open {video}")
    try:
        native = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 24.0
        step = 1.0 / fps
        next_t, index = 0.0, 0
        while True:
            if not cap.grab():
                break
            t = index / native
            index += 1
            if t + 0.5 / native < next_t:
                continue
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                yield round(t, 3), frame
            next_t += step
    finally:
        cap.release()


_FACE_APP: Any = None


def _insightface_boxes(frame_bgr: Any) -> list[tuple[int, int, int, int]] | None:
    """InsightFace face boxes (x, y, w, h) of one frame, or None when InsightFace is not available."""
    global _FACE_APP
    if _FACE_APP is False:
        return None
    try:
        if _FACE_APP is None:
            from insightface.app import FaceAnalysis  # type: ignore  # noqa: PLC0415
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection"])
            app.prepare(ctx_id=-1, det_size=(320, 320))
            _FACE_APP = app
        out = []
        for f in _FACE_APP.get(frame_bgr):
            if float(getattr(f, "det_score", 1.0)) >= 0.5:
                x0, y0, x1, y1 = (int(v) for v in f.bbox)
                out.append((x0, y0, max(1, x1 - x0), max(1, y1 - y0)))
        return out
    except Exception:  # noqa: BLE001 - no InsightFace: Haar or the central fallback
        _FACE_APP = False
        return None


def _face_boxes(colour: list[Any], greys: list[Any]) -> list[tuple[int, int, int, int]]:
    """Face boxes (x, y, w, h at work size) on up to FACE_SAMPLES evenly spaced frames: InsightFace when installed
    (``NALU_S6_WOBBLE_FACES`` auto|haar|off), else OpenCV Haar when this OpenCV build ships it, else []."""
    import cv2  # noqa: PLC0415
    mode = str(os.environ.get("NALU_S6_WOBBLE_FACES") or "auto").strip().lower()
    if mode == "off" or not greys:
        return []
    picks = sorted({round(i * (len(greys) - 1) / max(1, FACE_SAMPLES - 1)) for i in range(FACE_SAMPLES)})
    out: list[tuple[int, int, int, int]] = []
    if mode == "auto" and colour:
        found_any = False
        for i in picks:
            rows = _insightface_boxes(colour[i])
            if rows is None:
                break
            found_any = True
            out += rows
        if found_any:
            return out
    if not hasattr(cv2, "CascadeClassifier"):
        return []
    root = Path(cv2.data.haarcascades) if getattr(cv2, "data", None) else None
    cascades = []
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        path = root / name if root else None
        if path and path.is_file():
            c = cv2.CascadeClassifier(str(path))
            if not c.empty():
                cascades.append(c)
    for i in picks:
        g = greys[i]
        min_side = max(12, int(g.shape[1] * 0.06))
        for c in cascades:
            for (x, y, w, h) in c.detectMultiScale(g, scaleFactor=1.1, minNeighbors=4, minSize=(min_side, min_side)):
                out.append((int(x), int(y), int(w), int(h)))
    return out


def person_mask(shape: tuple[int, int], faces: list[tuple[int, int, int, int]], boxes: list[tuple[float, float, float, float]] | None = None):
    """bool mask (True = person) at work size.  Each face box (x, y, w, h) becomes a HEAD region (0.35 face widths
    to each side, 0.6 face heights above to 1.2 below the face top) and a TORSO region (0.9 face widths to each side,
    from just under the chin to the bottom of the frame); explicit ``boxes`` (fractions x0, y0, x1, y1) are added as
    given; with neither, a central column (x 0.28-0.72, y 0.12-1.0) stands in for the unseen person."""
    import numpy as np  # noqa: PLC0415
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)

    def put(x0: float, y0: float, x1: float, y1: float) -> None:
        mask[max(0, int(y0)):min(h, int(math.ceil(y1))), max(0, int(x0)):min(w, int(math.ceil(x1)))] = True

    for (x, y, fw, fh) in faces:
        put(x - 0.35 * fw, y - 0.6 * fh, x + 1.35 * fw, y + 1.2 * fh)
        put(x - 0.9 * fw, y + 1.0 * fh, x + 1.9 * fw, h)
    for (bx0, by0, bx1, by1) in boxes or []:
        put(bx0 * w, by0 * h, bx1 * w, by1 * h)
    if not faces and not boxes:
        put(0.28 * w, 0.12 * h, 0.72 * w, h)
    return mask


def background_feature_mask(video: Path, *, work_width: int, fps: float = 4.0,
                            frames: FrameReader | None = None) -> tuple[Any, dict[str, Any]]:
    """(uint8 mask at work size, 255 where camera features may be tracked = background, note) for a clip -- the
    complement of :func:`person_mask` over sampled faces, minus a 3 % edge band.  (None, note) when the clip shows
    too little background (< MIN_BACKGROUND_SHARE) or cannot be read.  Used by the S7 lock-off stabiliser and the
    camera metrics so that they track the SET, never the actor (2026-11-21, KO E05: the whole-frame tracker locked
    onto a swaying actor and the "stabilised" clip moved the background with him)."""
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        greys, colour = [], []
        for _t, image in (frames or _cv2_frames)(Path(video), fps):
            hh, ww = image.shape[:2]
            size = (work_width, max(2, int(round(hh * work_width / float(ww)))))
            small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            colour.append(small if small.ndim == 3 else cv2.cvtColor(small, cv2.COLOR_GRAY2BGR))
            greys.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small)
        if not greys:
            return None, {"status": "NO_FRAMES"}
        faces = _face_boxes(colour, greys)
        hh, ww = greys[0].shape
        person = person_mask((hh, ww), faces)
        edge = max(2, int(0.03 * ww))
        valid = np.zeros((hh, ww), dtype=bool)
        valid[edge:hh - edge, edge:ww - edge] = True
        bg = valid & ~person
        share = float(bg.sum()) / float(hh * ww)
        note = {"faces": len(faces), "background_share": round(share, 3)}
        if share < MIN_BACKGROUND_SHARE:
            return None, {**note, "status": "TOO_LITTLE_BACKGROUND"}
        return (bg.astype(np.uint8) * 255), {**note, "status": "OK"}
    except Exception as exc:  # noqa: BLE001
        return None, {"status": "FAIL_OPEN", "error": f"{type(exc).__name__}: {exc}"[:200]}


def _smooth(values: list[float], window: int) -> list[float]:
    if window <= 1 or len(values) < 3:
        return list(values)
    half = window // 2
    return [sum(values[max(0, i - half):i + half + 1]) / len(values[max(0, i - half):i + half + 1])
            for i in range(len(values))]


def count_reversals(path: list[float], prominence: float) -> int:
    """Turning points of ``path`` whose excursion on both sides is >= ``prominence`` (zig-zag pivots).  Pure."""
    if len(path) < 3 or prominence <= 0:
        return 0
    pivots, trend, ext, start = 0, 0, path[0], path[0]
    for v in path[1:]:
        if trend == 0:
            if v - start >= prominence:
                trend, ext = 1, v
            elif start - v >= prominence:
                trend, ext = -1, v
        elif trend == 1:
            if v > ext:
                ext = v
            elif ext - v >= prominence:
                pivots, trend, ext = pivots + 1, -1, v
        else:
            if v < ext:
                ext = v
            elif v - ext >= prominence:
                pivots, trend, ext = pivots + 1, 1, v
    return pivots


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 4:
        return None
    a, b = a[:n], b[:n]
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 1e-12 or vb <= 1e-12:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def measure_series(bg: list[tuple[float, float]], subject: list[float], *, width: int, fps: float) -> dict[str, Any]:
    """The wobble metrics from per-pair background motion (dx, dy in work pixels) and subject motion.  Pure."""
    xs, ys = [0.0], [0.0]
    for dx, dy in bg:
        xs.append(xs[-1] + dx)
        ys.append(ys[-1] + dy)
    scale = 100.0 / float(width)
    px, py = [v * scale for v in xs], [v * scale for v in ys]
    excursion = max(max(px) - min(px), max(py) - min(py))
    window = max(3, int(round(fps)) | 1)
    jitter = 0.0
    for path in (px, py):
        base = _smooth(path, window)
        jitter = max(jitter, math.sqrt(sum((v - m) ** 2 for v, m in zip(path, base)) / len(path)))
    seconds = max(1e-6, len(bg) / fps)
    smooth = max(1, int(round(fps / 6.0)))
    reversals = sum(count_reversals(_smooth(p, smooth), REVERSAL_PROMINENCE_PCT) for p in (px, py))
    speed = [math.hypot(dx, dy) for dx, dy in bg]
    coupling = _pearson(_smooth(speed, 3), _smooth(subject, 3))
    return {"excursion_pct": round(excursion, 3), "jitter_pct": round(jitter, 3),
            "reversals_per_s": round(reversals / seconds, 3), "reversals": reversals,
            "coupling": None if coupling is None else round(coupling, 3),
            "bg_speed_pct_s_median": round(sorted(speed)[len(speed) // 2] * fps * scale, 3) if speed else 0.0,
            "subject_motion_median": round(sorted(subject)[len(subject) // 2], 3) if subject else 0.0,
            "pairs": len(bg), "seconds": round(seconds, 2)}


def classify(metrics: dict[str, Any]) -> dict[str, Any]:
    """WOBBLE (with severity MILD / STRONG and the reasons) or CLEAN from :func:`measure_series` metrics.  Pure."""
    exc = float(metrics.get("excursion_pct") or 0.0)
    reasons = []
    if exc >= EXCURSION_MIN_PCT:
        if (metrics.get("coupling") or 0.0) >= COUPLING_MIN:
            reasons.append("COUPLED_TO_SUBJECT")
        if float(metrics.get("reversals_per_s") or 0.0) >= REVERSALS_MIN_S:
            reasons.append("BACK_AND_FORTH")
        if float(metrics.get("jitter_pct") or 0.0) >= JITTER_MIN_PCT:
            reasons.append("JITTER")
    if not reasons:
        return {"status": "CLEAN"}
    return {"status": "WOBBLE", "severity": "MILD" if exc <= MILD_MAX_PCT else "STRONG", "reasons": reasons}


def detect(video: Path, *, plan_static: bool | None = True, fps: float = SAMPLE_FPS, work_width: int = WORK_WIDTH,
           frames: FrameReader | None = None, boxes: list[tuple[float, float, float, float]] | None = None,
           faces: list[tuple[int, int, int, int]] | None = None) -> dict[str, Any]:
    """Camera wobble of one raw H3 clip.  Never raises.  ``plan_static`` False -> NOT_STATIC_PLAN (not measured);
    None (unknown plan) is measured like a static one but the caller decides what to do with it."""
    started = time.perf_counter()
    out: dict[str, Any] = {"schema": SCHEMA, "video": str(video), "fps": fps, "work_width": work_width,
                           "plan_static": plan_static, "thresholds": THRESHOLDS}
    if plan_static is False:
        out.update(status="NOT_STATIC_PLAN")
        return out
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        greys, colour = [], []
        for _t, image in (frames or _cv2_frames)(Path(video), fps):
            h, w = image.shape[:2]
            size = (work_width, max(2, int(round(h * work_width / float(w)))))
            small = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
            greys.append(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small)
            colour.append(small if small.ndim == 3 else cv2.cvtColor(small, cv2.COLOR_GRAY2BGR))
        if len(greys) < MIN_PAIRS + 1:
            out.update(status="NOT_MEASURABLE", reason="TOO_FEW_FRAMES", frames=len(greys))
            return out
        hh, ww = greys[0].shape
        face_rows = list(faces) if faces is not None else _face_boxes(colour, greys)
        mask = person_mask((hh, ww), face_rows, boxes)
        # a margin band at the frame edge is unreliable for flow (borders, letterbox): ignore 3 %
        edge = max(2, int(0.03 * ww))
        valid = np.zeros((hh, ww), dtype=bool)
        valid[edge:hh - edge, edge:ww - edge] = True
        bg_mask = valid & ~mask
        share = float(bg_mask.sum()) / float(hh * ww)
        out.update(faces=len(face_rows), background_share=round(share, 3), frames=len(greys))
        if share < MIN_BACKGROUND_SHARE:
            out.update(status="NOT_MEASURABLE", reason="TOO_LITTLE_BACKGROUND")
            return out
        person = mask & valid
        bg_series: list[tuple[float, float]] = []
        subject: list[float] = []
        for a, b in zip(greys, greys[1:]):
            flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            fx, fy = flow[..., 0], flow[..., 1]
            # textureless background (sky, plain wall) carries no flow signal: weight by gradient energy
            grad = cv2.Sobel(a, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(a, cv2.CV_32F, 0, 1) ** 2
            textured = bg_mask & (grad > np.percentile(grad[bg_mask], 40))
            sel = textured if textured.sum() >= 50 else bg_mask
            dx, dy = float(np.median(fx[sel])), float(np.median(fy[sel]))
            bg_series.append((dx, dy))
            if person.sum() >= 50:
                rx, ry = fx[person] - dx, fy[person] - dy
                subject.append(float(np.median(np.hypot(rx, ry))))
            else:
                subject.append(0.0)
        metrics = measure_series(bg_series, subject, width=ww, fps=fps)
        verdict = classify(metrics)
        out.update(metrics=metrics, **verdict)
    except Exception as exc:  # noqa: BLE001 - fail-open: never block the line on the detector
        out.update(status="FAIL_OPEN", error=f"{type(exc).__name__}: {exc}"[:300])
    out["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    return out


def wobble_score(detection: dict[str, Any] | None) -> float:
    """A take's wobble size for the best-take choice (0 = no wobble measured)."""
    det = detection or {}
    if det.get("status") != "WOBBLE":
        return 0.0
    return float((det.get("metrics") or {}).get("excursion_pct") or 0.0)


def summary(detection: dict[str, Any] | None) -> dict[str, Any]:
    """The compact record kept in the S6 wave state."""
    det = detection or {}
    m = det.get("metrics") or {}
    return {k: v for k, v in {"status": det.get("status"), "severity": det.get("severity"),
                              "reasons": det.get("reasons"), "excursion_pct": m.get("excursion_pct"),
                              "jitter_pct": m.get("jitter_pct"), "reversals_per_s": m.get("reversals_per_s"),
                              "coupling": m.get("coupling"), "background_share": det.get("background_share"),
                              "faces": det.get("faces"), "reason": det.get("reason"), "error": det.get("error"),
                              "elapsed_ms": det.get("elapsed_ms")}.items() if v is not None}


def plan(record: dict[str, Any] | None, detection: dict[str, Any], *, retry_max: int, total_max: int,
         headroom: int | None, cost: int, owner_accepted: bool = False) -> dict[str, Any]:
    """What to do with a take the burned-text check found CLEAN but this check found WOBBLE.  Pure.

    ``record`` is the unit's ``s6_burn_retry`` record: wobble retries are counted from its attempts flagged
    :data:`FLAG`; ``total_max`` is the burned-text retry cap (a unit never gets more S6 retries in all)."""
    attempts = list((record or {}).get("attempts") or [])
    wobble_done = sum(1 for a in attempts if isinstance(a, dict) and a.get(FLAG))
    if detection.get("status") != "WOBBLE":
        return {"action": "KEEP", "reason": "NO_WOBBLE", "retry": len(attempts)}
    if retry_max <= 0:
        return {"action": "KEEP_BEST", "reason": "WOBBLE_RETRY_DISABLED", "retry": len(attempts)}
    if owner_accepted:
        return {"action": "KEEP_BEST", "reason": "LINE_OWNER_ACCEPTED_THIS_CLIP", "retry": len(attempts)}
    if wobble_done >= retry_max:
        return {"action": "KEEP_BEST", "reason": "WOBBLE_RETRY_MAX_REACHED", "retry": len(attempts)}
    if len(attempts) >= max(0, int(total_max)):
        return {"action": "KEEP_BEST", "reason": "S6_RETRY_MAX_REACHED", "retry": len(attempts)}
    if headroom is None:
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_UNKNOWN", "retry": len(attempts), "cost": cost}
    if cost > int(headroom):
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_SHORT", "retry": len(attempts), "cost": cost,
                "headroom": int(headroom)}
    return {"action": "RETRY", "reason": "CAMERA_WOBBLE_DETECTED", "retry": len(attempts) + 1, "cost": cost}


def main(argv: list[str] | None = None) -> int:
    import argparse  # noqa: PLC0415
    import json  # noqa: PLC0415
    ap = argparse.ArgumentParser(description="S6 camera-wobble check of raw H3 clips (local, free)")
    ap.add_argument("videos", nargs="+", type=Path)
    args = ap.parse_args(argv)
    for video in args.videos:
        result = detect(video)
        print(json.dumps({"video": str(video), **summary(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
