#!/usr/bin/env python3
"""S7 push-in compensation (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-10-26, lab Holmes E06).

MiniMax-H3 still pushes in on many locked-camera units (E06: face width 0.41 -> 0.81 of the frame on a
"Locked camera" unit).  The strict camera-lock prompt reduces it; this free post step removes what is left.

For each locked-camera unit of a stamped episode, the largest face is measured with the engine's own
InsightFace (``character_identity_admission_gate.InsightFaceBackend``) on ``SAMPLES`` frames of the clip
*as it is used in the cut* (after the dialogue head/tail trims).  A unit is compensated when

- at least ``MIN_FACE_SAMPLES`` samples have a face (else ``SKIPPED_FEW_FACES``);
- no two consecutive face samples differ in width by more than ``CUT_JUMP`` (that is a cut, not a push:
  ``SKIPPED_INTERNAL_CUT``);
- the face grows by more than ``GROWTH_MIN`` from the first to the last measured sample (else ``NO_PUSH_IN``)
  and the growth is monotonic-ish (a non-decreasing least-squares fit explains it: else ``SKIPPED_NOT_MONOTONIC``).

H3 pushed in, so the outside of the late frames does not exist; the push is removed by zooming the EARLY frames
in instead: the face keeps the END size all along.  Per frame the crop factor is ``c(t) = w_end / w(t)`` (w = the
monotone fit, interpolated between samples), the crop window keeps the face where it sits in the last frame, and
the cropped frame is scaled back to the clip's own resolution with Lanczos.  The crop never exceeds ``MAX_CROP``:
a bigger push is compensated only partially, ``c(t) = (w_end / w(t)) ** k`` with ``k`` chosen so the first frame
is exactly ``MAX_CROP`` (the remaining push is a slower, even one; ``cap_hit``).  Frame count, duration and the
audio stream (copied bit-exact) are unchanged.

The S7 caller (nalu_pipeline.s7_push_in_compensation) writes ``<EP>_PUSH_IN_COMPENSATION.json`` and hands it to the
AgentCut build (``--push-in-compensation``), which swaps the compensated clip in for both the picture and the native
sound of that unit (same file, same in/out points).  Any failure only skips the step; S7 never blocks on it.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any, Callable

SCHEMA = "nalu.push_in_compensation.v1"
SAMPLES = 9
MIN_FACE_SAMPLES = 6
GROWTH_MIN = 0.25
CUT_JUMP = 0.40
MAX_CROP = 1.6
#: residual of the monotone fit, relative to the mean face width, above which the curve is not a push-in
MONOTONE_RESIDUAL_MAX = 0.12
#: same face filter as video_q2_builder's face count (FACE_COUNT_MIN_DET_SCORE / FACE_COUNT_MIN_HEIGHT_RATIO)
MIN_DET_SCORE = 0.6
MIN_FACE_HEIGHT_RATIO = 0.04
LOCKED_FAMILIES = {"STATIC", "LOCKED"}


# --------------------------------------------------------------------------------------------------------------
# pure analysis
# --------------------------------------------------------------------------------------------------------------
def sample_times(t_in: float, t_out: float, n: int = SAMPLES) -> list[float]:
    """``n`` evenly spaced times inside [t_in, t_out], ~2 frames inside both ends (a seek to the very last frame
    of a clip decodes nothing)."""
    span = max(0.0, t_out - t_in)
    margin = min(0.1, span / 20.0)
    a, b = t_in + margin, t_out - margin
    if n <= 1 or b <= a:
        return [round(t_in + span / 2.0, 4)]
    return [round(a + (b - a) * i / (n - 1), 4) for i in range(n)]


def monotone_fit(values: list[float]) -> list[float]:
    """Least-squares non-decreasing fit (pool adjacent violators)."""
    blocks: list[list[float]] = []  # [mean, weight]
    for v in values:
        blocks.append([float(v), 1.0])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            m2, w2 = blocks.pop()
            m1, w1 = blocks.pop()
            blocks.append([(m1 * w1 + m2 * w2) / (w1 + w2), w1 + w2])
    out: list[float] = []
    for mean, weight in blocks:
        out.extend([mean] * int(weight))
    return out


def _smooth(values: list[float]) -> list[float]:
    if len(values) < 3:
        return list(values)
    return [values[0]] + [(values[i - 1] + values[i] + values[i + 1]) / 3.0
                          for i in range(1, len(values) - 1)] + [values[-1]]


def analyze(samples: list[dict[str, Any]], *, max_crop: float = MAX_CROP) -> dict[str, Any]:
    """Decide and plan one unit from its face samples [{t, width, cx, cy}] (width/cx/cy as fractions of the frame
    width/height; width None = no face).  Returns {status, ...}; status COMPENSATE carries ``curve``."""
    faces = [s for s in samples if s.get("width")]
    out: dict[str, Any] = {"face_samples": len(faces), "samples": len(samples),
                           "widths": [None if not s.get("width") else round(float(s["width"]), 4) for s in samples]}
    if len(faces) < MIN_FACE_SAMPLES:
        return {**out, "status": "SKIPPED_FEW_FACES"}
    widths = [float(s["width"]) for s in faces]
    jumps = [abs(widths[i] / widths[i - 1] - 1.0) for i in range(1, len(widths))]
    out["max_step_change"] = round(max(jumps), 4) if jumps else 0.0
    out["start_width"], out["end_width"] = round(widths[0], 4), round(widths[-1], 4)
    growth = widths[-1] / widths[0] - 1.0
    out["growth"] = round(growth, 4)
    if jumps and max(jumps) > CUT_JUMP:
        return {**out, "status": "SKIPPED_INTERNAL_CUT"}
    if growth <= GROWTH_MIN:
        return {**out, "status": "NO_PUSH_IN"}
    fit = monotone_fit(widths)
    mean = sum(widths) / len(widths)
    residual = math.sqrt(sum((a - b) ** 2 for a, b in zip(widths, fit)) / len(widths)) / mean
    out["monotone_residual"] = round(residual, 4)
    if residual > MONOTONE_RESIDUAL_MAX or fit[-1] / fit[0] - 1.0 <= GROWTH_MIN:
        return {**out, "status": "SKIPPED_NOT_MONOTONIC"}
    full = [fit[-1] / w for w in fit]  # >= 1, 1 at the end
    exponent = 1.0
    if full[0] > max_crop:
        exponent = math.log(max_crop) / math.log(full[0])
    crops = [f ** exponent for f in full]
    cx, cy = _smooth([float(s["cx"]) for s in faces]), _smooth([float(s["cy"]) for s in faces])
    curve = [{"t": round(float(s["t"]), 4), "fit_width": round(w, 4), "crop": round(c, 4),
              "cx": round(x, 4), "cy": round(y, 4)}
             for s, w, c, x, y in zip(faces, fit, crops, cx, cy)]
    return {**out, "status": "COMPENSATE", "curve": curve, "anchor": {"cx": curve[-1]["cx"], "cy": curve[-1]["cy"]},
            "max_crop": round(max(crops), 4), "cap_hit": exponent < 1.0, "crop_exponent": round(exponent, 4),
            "predicted_residual_growth": round(fit[-1] / (fit[0] * crops[0]) - 1.0, 4)}


def _interp(t: float, xs: list[float], ys: list[float]) -> float:
    if t <= xs[0]:
        return ys[0]
    if t >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if t <= xs[i]:
            span = xs[i] - xs[i - 1]
            a = (t - xs[i - 1]) / span if span > 0 else 1.0
            return ys[i - 1] + (ys[i] - ys[i - 1]) * a
    return ys[-1]


def crop_window(t: float, plan: dict[str, Any], width: int, height: int) -> tuple[float, float, float]:
    """(crop factor, x0, y0) of the frame at ``t`` (seconds in the source clip): a ``width/c x height/c`` window
    that keeps the face where it sits in the last frame (``anchor``), clamped inside the frame."""
    curve = plan["curve"]
    ts = [p["t"] for p in curve]
    c = max(1.0, _interp(t, ts, [p["crop"] for p in curve]))
    cx = _interp(t, ts, [p["cx"] for p in curve]) * width
    cy = _interp(t, ts, [p["cy"] for p in curve]) * height
    cw, ch = width / c, height / c
    x0 = min(max(cx - plan["anchor"]["cx"] * cw, 0.0), width - cw)
    y0 = min(max(cy - plan["anchor"]["cy"] * ch, 0.0), height - ch)
    return c, x0, y0


def locked_camera_unit(unit: dict[str, Any]) -> bool:
    """Every camera plan of a grouping unit is a locked camera (STATIC / LOCKED)."""
    plans = [unit.get("camera_plan")] + [row.get("camera_plan", row) for row in unit.get("per_shot_camera_plans") or []
                                         if isinstance(row, dict)]
    plans = [p for p in plans if isinstance(p, dict)]
    return bool(plans) and all(str(p.get("motion_family") or "STATIC").upper() in LOCKED_FAMILIES for p in plans)


def cut_windows(units: list[str], clip_seconds: dict[str, float], tail_report: dict[str, Any] | None,
                head_report: dict[str, Any] | None) -> dict[str, tuple[float, float]]:
    """unit -> (source in, source out) as the AgentCut build cuts it (dialogue head / tail trim reports)."""
    tail = {str(r.get("unit_id")): r for r in (tail_report or {}).get("units") or []}
    head = {str(r.get("unit_id")): r for r in (head_report or {}).get("units") or []}
    out = {}
    for uid in units:
        end = float(clip_seconds.get(uid) or 0.0)
        kept = (tail.get(uid) or {}).get("kept_seconds")
        if kept:
            end = min(end, float(kept)) if end else float(kept)
        start = 0.0
        row = head.get(uid) or {}
        if row.get("trimmed") and row.get("head_cut_seconds"):
            start = float(row["head_cut_seconds"])
        out[uid] = (start, end)
    return out


# --------------------------------------------------------------------------------------------------------------
# media (InsightFace + ffmpeg/OpenCV)
# --------------------------------------------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path, ffprobe: str = "ffprobe") -> dict[str, Any]:
    run = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_read_packets:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    data = json.loads(run.stdout)
    stream = data["streams"][0]
    num, den = (stream.get("r_frame_rate") or "24/1").split("/")
    return {"width": int(stream["width"]), "height": int(stream["height"]), "fps": float(num) / float(den or 1),
            "frames": int(stream.get("nb_read_packets") or 0), "duration": float(data["format"]["duration"])}


def face_backend() -> Any:
    """The engine's own FaceAnalysis (buffalo_l, CPU) - the same one Q2 uses."""
    try:
        from tools.character_identity_admission_gate import InsightFaceBackend
    except ModuleNotFoundError:  # pragma: no cover - flat sys.path deployments
        from character_identity_admission_gate import InsightFaceBackend  # type: ignore
    return InsightFaceBackend("buffalo_l")._app  # noqa: SLF001 - engine's own FaceAnalysis instance


def largest_face(app: Any, image: Any) -> dict[str, float] | None:
    height, width = image.shape[:2]
    best = None
    for face in app.get(image):
        x1, y1, x2, y2 = (float(v) for v in face.bbox[:4])
        if float(getattr(face, "det_score", 0.0)) < MIN_DET_SCORE or (y2 - y1) < MIN_FACE_HEIGHT_RATIO * height:
            continue
        if best is None or (x2 - x1) > best["px"]:
            best = {"px": x2 - x1, "width": (x2 - x1) / width, "cx": (x1 + x2) / 2 / width, "cy": (y1 + y2) / 2 / height}
    return best


def frame_at(path: Path, t: float, ffmpeg: str = "ffmpeg") -> Any:
    import cv2
    import numpy as np
    for at in (t, max(0.0, t - 0.1)):  # past the last decodable frame: one step back
        run = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{at:.4f}", "-i", str(path), "-frames:v", "1",
                              "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=False)
        if run.returncode == 0 and run.stdout:
            return cv2.imdecode(np.frombuffer(run.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None


def measure(path: Path, times: list[float], app: Any, ffmpeg: str = "ffmpeg") -> list[dict[str, Any]]:
    rows = []
    for t in times:
        image = frame_at(path, t, ffmpeg)
        face = largest_face(app, image) if image is not None else None
        rows.append({"t": t, **({k: round(v, 5) for k, v in face.items() if k != "px"} if face else {"width": None})})
    return rows


def _audio_md5(path: Path, ffmpeg: str) -> str | None:
    run = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy", "-f", "md5", "-"],
                         capture_output=True, text=True, check=False)
    return run.stdout.strip() if run.returncode == 0 and run.stdout.strip() else None


def render(source: Path, out: Path, plan: dict[str, Any], *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
           crf: int = 14) -> dict[str, Any]:
    """Write the compensated clip: every frame cropped by ``crop_window`` and scaled back (Lanczos) to the source
    resolution; same frame rate and frame count, audio stream copied.  Returns {frames, duration, audio_bit_exact}."""
    import cv2
    import numpy as np
    info = probe(source, ffprobe)
    width, height, fps = info["width"], info["height"], info["fps"]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.mp4")
    decode = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(source), "-map", "0:v:0", "-f", "rawvideo",
                               "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE)
    encode = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                               "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-", "-i", str(source),
                               "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "medium",
                               "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
                               str(tmp)], stdin=subprocess.PIPE)
    size = width * height * 3
    frames = 0
    try:
        while True:
            buf = decode.stdout.read(size)
            if len(buf) < size:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 3)
            c, x0, y0 = crop_window(frames / fps, plan, width, height)
            if c > 1.0 + 1e-4:
                matrix = np.float32([[c, 0, -x0 * c], [0, c, -y0 * c]])
                frame = cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_LANCZOS4,
                                       borderMode=cv2.BORDER_REPLICATE)
            encode.stdin.write(np.ascontiguousarray(frame).tobytes())
            frames += 1
    finally:
        encode.stdin.close()
        decode.stdout.close()
        decode.wait()
        encode.wait()
    if encode.returncode != 0 or decode.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"PUSH_IN_RENDER_FAILED:{source.name}")
    after = probe(tmp, ffprobe)
    audio_src, audio_out = _audio_md5(source, ffmpeg), _audio_md5(tmp, ffmpeg)
    checks = {"frames": after["frames"] == info["frames"] == frames,
              "duration": abs(after["duration"] - info["duration"]) <= 1.0 / fps + 1e-3,
              "audio_bit_exact": audio_src == audio_out}
    if not all(checks.values()):
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"PUSH_IN_RENDER_CHECK_FAILED:{source.name}:{checks}")
    tmp.replace(out)
    return {"frames": frames, "duration": after["duration"], "audio_bit_exact": True,
            "source_resolution": [width, height]}


def plan_units(units: dict[str, Path], windows: dict[str, tuple[float, float]], *,
               measure_fn: Callable[[Path, list[float]], list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """unit -> analysis row (no rendering): measured on the cut window of each clip."""
    rows = {}
    for uid, clip in sorted(units.items()):
        start, end = windows.get(uid) or (0.0, 0.0)
        if end - start < 0.5:
            rows[uid] = {"status": "SKIPPED_NO_CUT_WINDOW", "cut_window": [start, end]}
            continue
        samples = measure_fn(clip, sample_times(start, end))
        rows[uid] = {"cut_window": [round(start, 4), round(end, 4)], **analyze(samples), "face_samples_raw": samples}
    return rows


def build_report(episode: str, grouping: dict[str, Any], clips: dict[str, Path],
                 windows: dict[str, tuple[float, float]], out_dir: Path, *,
                 measure_fn: Callable[[Path, list[float]], list[dict[str, Any]]],
                 render_fn: Callable[[Path, Path, dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Plan (and, with ``render_fn``, render) every locked-camera unit with a clip.  Never raises per unit: a unit
    that fails is recorded as SKIPPED_ERROR and keeps its original clip."""
    locked = {str(u.get("unit_id")) for u in grouping.get("units") or [] if locked_camera_unit(u)}
    rows: dict[str, dict[str, Any]] = {}
    for uid in sorted(clips):
        if uid not in locked:
            rows[uid] = {"status": "SKIPPED_MOVING_CAMERA"}
    candidates = {uid: path for uid, path in clips.items() if uid in locked}
    for uid, clip in sorted(candidates.items()):
        try:
            row = plan_units({uid: clip}, windows, measure_fn=measure_fn)[uid]
        except Exception as exc:  # noqa: BLE001 - one unit never blocks the others
            rows[uid] = {"status": f"SKIPPED_ERROR:{type(exc).__name__}:{exc}"}
            continue
        if row["status"] == "COMPENSATE" and render_fn is not None:
            target = out_dir / f"{uid}.mp4"
            try:
                rendered = render_fn(clip, target, row)
                row.update(status="APPLIED", source=str(clip), source_sha256=sha256_file(clip),
                           output=str(target), output_sha256=sha256_file(target), render=rendered)
            except Exception as exc:  # noqa: BLE001
                row["status"] = f"SKIPPED_RENDER_ERROR:{type(exc).__name__}:{exc}"
        rows[uid] = row
    applied = sorted(uid for uid, row in rows.items() if row.get("status") == "APPLIED")
    return {"schema": SCHEMA, "episode": episode, "samples": SAMPLES, "growth_min": GROWTH_MIN,
            "cut_jump": CUT_JUMP, "min_face_samples": MIN_FACE_SAMPLES, "max_crop": MAX_CROP,
            "compensated_units": applied, "units": rows}


def applied_sources(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """unit -> APPLIED row whose output file still exists with the recorded sha (for the AgentCut build)."""
    out = {}
    for uid, row in (report.get("units") or {}).items():
        if row.get("status") != "APPLIED":
            continue
        target = Path(str(row.get("output") or ""))
        if target.is_file() and sha256_file(target) == row.get("output_sha256"):
            out[str(uid)] = row
    return out
