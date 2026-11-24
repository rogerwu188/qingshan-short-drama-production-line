#!/usr/bin/env python3
"""Benchmark craft metrics of a final cut (CHANGE_SPEC WP7) -- report only, never a gate.

Owner 2026-11-23 (Bilibili benchmark ep2 + ep3): measure what the redesign is meant to move, against the band the
two benchmark episodes set, on every BILI_V1 episode at S7.  Ported from the lab scripts
(``~/nalu_lab/bili_work/scripts/{shots,stats,speech}.py`` + the pause-loudness snippet):

* picture (OpenCV + numpy; insightface's face detector when installed): shot cuts (ffmpeg ``scdet`` >= 10 union a
  local frame-difference spike), shot length distribution, per-shot camera motion (LK flow, similarity fit) and the
  share of moving shots, faces at 25/50/75 % of each shot -> time with two or more people in frame and faceless
  object shots;
* sound: speech coverage and pauses from the unit ASR windows (``<EP>_FINAL_CUT_ASR_WINDOWS.json``), ``ebur128``
  momentary loudness -> speech vs pause loudness gap and music presence in the pauses;
* script (generation contract): two-or-more-in-frame plan time (incl. over-the-shoulder backs), reaction share and
  dedicated reaction shots, reaction after each PAYOFF, props declared per scene, touches per two-person scene,
  camera-move share of the plan, fallback-template share of the action fields, ledger counts.

Every measurement that cannot run (no OpenCV, no insightface, no ffmpeg, no ASR windows) is ``NOT_MEASURED``; the
report is still written.  ``python3 tools/craft_metrics.py --video final.mp4 --contract C.json
--asr-windows W.json --release-timeline T.json --episode E25 --out E25_CRAFT_METRICS.json --md E25_CRAFT_METRICS.md``
always exits 0 (unless the arguments are malformed).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics as st
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA = "nalu.craft_metrics.v1"
TOOL_ID = "tools/craft_metrics.py"
#: ep2 / ep3 measured values and the target band for our ~110 s vertical episodes (CHANGE_SPEC WP7)
BAND: dict[str, dict[str, Any]] = {
    "multi_person_time_pct": {"ep2": 46, "ep3": 39, "min": 35, "label": "two or more in frame (incl. OTS back)"},
    "speech_coverage_pct": {"ep2": 62, "ep3": 58, "min": 55, "max": 70, "label": "speech coverage"},
    "pauses_gt3s": {"ep2": 8, "ep3": 17, "min": 2, "label": "pauses > 3 s"},
    "pause_vs_speech_lu": {"ep2": 0.4, "ep3": 1.6, "max": 6, "label": "pause vs speech loudness (LU)"},
    "camera_moving_pct": {"ep2": 85, "ep3": 83, "min": 30, "label": "camera moving (share of shots)"},
    "fallback_share_pct": {"max": 10, "label": "fallback-template share of action fields"},
    "props_per_scene": {"min": 2, "label": "props declared per scene"},
}
FALLBACK_FIELDS = ("motion_direction", "physical_causality", "microexpression_design", "physical_action_design",
                   "contact_point")
OTS_EXTENTS = ("BACK_AND_SHOULDERS_ONLY", "BACK_OF_HEAD", "OVER_THE_SHOULDER", "OTS")
WORK_SIDE = 360
MOTION_FPS = 12.0
SPEECH_MERGE_GAP = 0.35
PAUSE_SECONDS = 3.0
MUSIC_FLOOR_LUFS = -45.0


# --------------------------------------------------------------------------- small helpers
def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _read_json(path: Path | None) -> Any:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pct(part: float, whole: float) -> float | None:
    return round(100.0 * part / whole, 1) if whole > 0 else None


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _run(argv: list[str], timeout: float = 600) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
    return (proc.stdout or "") + (proc.stderr or "")


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


# --------------------------------------------------------------------------- picture
def scdet_scores(video: Path, fps: float) -> dict[int, float]:
    """frame index -> ffmpeg scene-change score (``scdet``), {} without ffmpeg."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return {}
    import tempfile  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "scd.txt"
        _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(video), "-vf",
              f"scale=640:-2,scdet=threshold=0:sc_pass=0,metadata=mode=print:key=lavfi.scd.score:file={out}",
              "-an", "-f", "null", "-"])
        text = out.read_text(encoding="utf-8", errors="replace") if out.is_file() else ""
    return {int(round(float(a) * fps)): float(b)
            for a, b in re.findall(r"pts_time:([\d.]+)\s*\n?lavfi.scd.score=([\d.]+)", text)}


def _face_detector() -> Callable[[Any], list[tuple[float, float, float, float, float]]] | None:
    """insightface's detector alone (buffalo_l/det_10g.onnx, on every device for the identity QA); None if absent."""
    if str(os.environ.get("NALU_CRAFT_METRICS_FACES") or "").strip().lower() in ("off", "0", "false"):
        return None
    root = Path(os.environ.get("INSIGHTFACE_HOME") or Path.home() / ".insightface").expanduser()
    det = root / "models" / "buffalo_l" / "det_10g.onnx"
    if not det.is_file():
        return None
    try:
        from insightface.model_zoo import get_model  # type: ignore  # noqa: PLC0415
        model = get_model(str(det), providers=["CPUExecutionProvider"])
        model.prepare(ctx_id=-1, input_size=(640, 640), det_thresh=0.6)
    except Exception:  # noqa: BLE001
        return None

    def detect(frame: Any) -> list[tuple[float, float, float, float, float]]:
        boxes, _ = model.detect(frame, input_size=(640, 640))
        return [tuple(float(v) for v in b[:5]) for b in boxes if float(b[4]) >= 0.6]
    return detect


def _framing(height_ratio: float | None) -> str:
    if height_ratio is None:
        return "noface"
    return ("ECU" if height_ratio > 0.5 else "CU" if height_ratio > 0.28 else "MCU" if height_ratio > 0.2
            else "MS" if height_ratio > 0.125 else "WS")


def _motion_kind(shot: dict[str, Any]) -> str:
    dur = max(float(shot["dur"]), 0.1)
    speed = (abs(shot["pan_pct"]) + abs(shot["tilt_pct"])) / dur
    zoom = shot["zoom_pct"] / dur
    return ("zoom_in" if zoom > 0.8 else "zoom_out" if zoom < -0.8 else "pan/tilt" if speed > 2.0
            else "drift" if speed > 0.5 else "static")


def measure_picture(video: Path, *, end: float | None = None, faces: bool = True) -> dict[str, Any]:
    """Shots, camera motion and faces of the cut (``status: NOT_MEASURED`` without OpenCV)."""
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError as exc:
        return {"status": "NOT_MEASURED", "reason": f"opencv/numpy unavailable: {exc}"}
    cap = cv2.VideoCapture(str(video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0) or 24.0
    width, height = int(cap.get(3) or 0), int(cap.get(4) or 0)
    if not width or not height:
        return {"status": "NOT_MEASURED", "reason": "video unreadable"}
    scale = WORK_SIDE / max(width, height)
    w, h = max(1, int(width * scale)), max(1, int(height * scale))
    last_frame = int(end * fps) if end else None
    greys, smalls = [], []
    while True:
        ok, frame = cap.read()
        if not ok or (last_frame is not None and len(greys) >= last_frame):
            break
        grey = cv2.cvtColor(cv2.resize(frame, (w, h)), cv2.COLOR_BGR2GRAY)
        greys.append(grey)
        smalls.append(cv2.resize(grey[int(h * 0.12):int(h * 0.70)], (32, 24)).astype(np.float32))
    cap.release()
    n = len(greys)
    if n < 2:
        return {"status": "NOT_MEASURED", "reason": "too few frames"}
    diff = np.array([0.0] + [float(np.abs(smalls[i] - smalls[i - 1]).mean()) for i in range(1, n)])
    cuts = {i for i, score in scdet_scores(video, fps).items() if score >= 10 and 0 < i < n}
    for i in range(3, n - 3):
        around = np.concatenate([diff[max(1, i - 6):i], diff[i + 1:i + 7]])
        if diff[i] > 22 and diff[i] > 4 * (float(np.median(around)) + 2):
            cuts.add(i)
    merged: list[int] = []
    for c in sorted(cuts):
        if merged and c - merged[-1] < int(0.25 * fps):
            continue  # flashes / double hits
        merged.append(c)
    bounds = [0, *merged, n]
    detect = _face_detector() if faces else None
    cap = cv2.VideoCapture(str(video)) if detect else None
    step = max(1, int(round(fps / MOTION_FPS)))
    shots = []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        steps = []
        for i in range(a + step, b, step):
            p0 = cv2.goodFeaturesToTrack(greys[i - step], 300, 0.01, 8)
            if p0 is None or len(p0) < 12:
                steps.append((0.0, 0.0, 1.0))
                continue
            p1, status, _ = cv2.calcOpticalFlowPyrLK(greys[i - step], greys[i], p0, None)
            g0, g1 = p0[status[:, 0] == 1], p1[status[:, 0] == 1]
            if len(g0) < 12:
                steps.append((0.0, 0.0, 1.0))
                continue
            matrix, _ = cv2.estimateAffinePartial2D(g0, g1, method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if matrix is None:
                steps.append((0.0, 0.0, 1.0))
                continue
            steps.append((float(matrix[0, 2]), float(matrix[1, 2]), float(np.hypot(matrix[0, 0], matrix[1, 0]))))
        arr = np.array(steps) if steps else np.array([[0.0, 0.0, 1.0]])
        shot = {"i": k, "start": round(a / fps, 3), "end": round(b / fps, 3), "dur": round((b - a) / fps, 3),
                "pan_pct": round(float(arr[:, 0].sum()) / w * 100, 2),
                "tilt_pct": round(float(arr[:, 1].sum()) / h * 100, 2),
                "zoom_pct": round((float(np.prod(arr[:, 2])) - 1) * 100, 2)}
        shot["motion"] = _motion_kind(shot)
        if detect and cap is not None:
            counts, heights = [], []
            for q in (0.25, 0.5, 0.75):
                cap.set(cv2.CAP_PROP_POS_FRAMES, a + int((b - a) * q))
                ok, frame = cap.read()
                if not ok:
                    continue
                try:
                    boxes = detect(frame)
                except Exception:  # noqa: BLE001
                    boxes = []
                counts.append(len(boxes))
                if q == 0.5:
                    heights = [(box[3] - box[1]) / height for box in boxes]
            shot["faces"] = max(counts) if counts else 0
            shot["framing"] = _framing(max(heights) if heights else None)
        shots.append(shot)
    if cap is not None:
        cap.release()
    duration = n / fps
    lengths = [s["dur"] for s in shots]
    moving = [s for s in shots if s["motion"] != "static"]
    out: dict[str, Any] = {
        "status": "MEASURED", "fps": round(fps, 3), "duration_s": round(duration, 2), "shots": len(shots),
        "cuts_per_min": round((len(shots) - 1) / duration * 60, 1) if duration else None,
        "shot_length": {"asl": round(duration / len(shots), 2), "median": round(st.median(lengths), 2),
                        "p10": round(_percentile(lengths, 0.1), 2), "p90": round(_percentile(lengths, 0.9), 2),
                        "pct_lt2s": round(100 * sum(x < 2 for x in lengths) / len(lengths)),
                        "pct_gt5s": round(100 * sum(x > 5 for x in lengths) / len(lengths))},
        "camera_moving_pct": round(100 * len(moving) / len(shots), 1),
        "motion_pct": {kind: round(100 * sum(s["motion"] == kind for s in shots) / len(shots))
                       for kind in sorted({s["motion"] for s in shots})},
        "faces": "MEASURED" if detect else "NOT_MEASURED",
        "per_shot": shots,
    }
    if detect:
        two = sum(s["dur"] for s in shots if s.get("faces", 0) >= 2)
        none = [s for s in shots if s.get("faces", 0) == 0]
        out["faces_2plus_time_pct"] = _pct(two, duration)
        out["faceless_shots"] = len(none)
        out["faceless_time_pct"] = _pct(sum(s["dur"] for s in none), duration)
        framing: dict[str, int] = {}
        for s in shots:
            framing[s.get("framing") or "noface"] = framing.get(s.get("framing") or "noface", 0) + 1
        out["framing_pct"] = {k: round(100 * v / len(shots)) for k, v in sorted(framing.items())}
    return out


# --------------------------------------------------------------------------- sound
def speech_intervals(windows: Any, end: float) -> list[list[float]]:
    """Merged [start, end] speech intervals from ASR windows ([{start, end}] or {segments: [...]})."""
    rows = windows.get("segments") if isinstance(windows, dict) else windows
    spans = sorted((float(r["start"]), float(r["end"])) for r in rows or []
                   if isinstance(r, dict) and _num(r.get("start")) is not None and _num(r.get("end")) is not None
                   and float(r["start"]) < end and float(r["end"]) > float(r["start"]))
    merged: list[list[float]] = []
    for s, e in spans:
        e = min(e, end)
        if merged and s - merged[-1][1] < SPEECH_MERGE_GAP:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def measure_speech(windows: Any, end: float) -> dict[str, Any]:
    if windows is None:
        return {"status": "NOT_MEASURED", "reason": "no ASR windows"}
    merged = speech_intervals(windows, end)
    covered = sum(e - s for s, e in merged)
    gaps = [merged[i + 1][0] - merged[i][1] for i in range(len(merged) - 1)]
    return {"status": "MEASURED", "speech_coverage_pct": _pct(covered, end), "utterances": len(merged),
            "utterances_per_min": round(len(merged) / end * 60, 1) if end else None,
            "gaps_gt1s": sum(g > 1 for g in gaps), "pauses_gt3s": sum(g > PAUSE_SECONDS for g in gaps),
            "longest_gap_s": round(max(gaps), 1) if gaps else 0.0,
            "first_word_s": round(merged[0][0], 2) if merged else None, "intervals": merged}


def momentary_loudness(video: Path) -> list[tuple[float, float]]:
    """[(t, momentary LUFS)] from ffmpeg ebur128 (silence -inf rows dropped); [] without ffmpeg / audio."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return []
    text = _run([ffmpeg, "-hide_banner", "-nostats", "-v", "verbose", "-i", str(video), "-filter_complex",
                 "ebur128=framelog=verbose", "-f", "null", "-"])
    return [(float(t), float(m)) for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-inf)", text)
            if m != "-inf"]


def measure_pause_loudness(loudness: list[tuple[float, float]], speech: list[list[float]], end: float
                           ) -> dict[str, Any]:
    """Speech vs pause loudness (median momentary, pauses > 1 s) and music presence in the pauses."""
    if not loudness or not speech:
        return {"status": "NOT_MEASURED", "reason": "no loudness or no speech intervals"}

    def inside(t: float, spans: list[list[float]]) -> bool:
        return any(s <= t <= e for s, e in spans)
    pauses = [[speech[i][1], speech[i + 1][0]] for i in range(len(speech) - 1) if speech[i + 1][0] - speech[i][1] > 1]
    # momentary loudness integrates 400 ms: keep 0.4 s clear of each speech edge
    pause_core = [[s + 0.4, e - 0.4] for s, e in pauses if e - s > 0.8]
    speech_m = [m for t, m in loudness if t <= end and inside(t, speech)]
    pause_m = [m for t, m in loudness if t <= end and inside(t, pause_core)]
    if not speech_m or not pause_m:
        return {"status": "NOT_MEASURED", "reason": "no pause long enough to measure"}
    speech_lufs, pause_lufs = st.median(speech_m), st.median(pause_m)
    return {"status": "MEASURED", "speech_lufs": round(speech_lufs, 1), "pause_lufs": round(pause_lufs, 1),
            "pause_vs_speech_lu": round(speech_lufs - pause_lufs, 1), "pauses_measured": len(pause_core),
            "music_in_pauses_pct": round(100 * sum(m > MUSIC_FLOOR_LUFS for m in pause_m) / len(pause_m)),
            "music_floor_lufs": MUSIC_FLOOR_LUFS}


# --------------------------------------------------------------------------- script / plan
def _visible_cast(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in spec.get("cast") or [] if isinstance(m, dict)
            and str(m.get("face_visibility") or "") != "OFFSCREEN_VOICE_ONLY"]


def _authored(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_authored(v) for v in value.values())
    return bool(str(value or "").strip())


def measure_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(contract, dict) or not contract.get("shots"):
        return {"status": "NOT_MEASURED", "reason": "no generation contract"}
    shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
    total = sum(_num(s.get("target_seconds")) or 0.0 for s in shots)
    multi = 0.0
    dialogue = reacted = dedicated = moving = 0
    fallback = slots = 0
    scenes: dict[str, dict[str, Any]] = {}
    payoffs: list[int] = []
    for index, shot in enumerate(shots):
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
        seconds = _num(shot.get("target_seconds")) or 0.0
        cast = _visible_cast(spec)
        if len(cast) >= 2:
            multi += seconds
        scene = scenes.setdefault(str(shot.get("scene_id") or "?"), {"props": set(), "people": set(), "touches": 0})
        scene["people"].update(str(m.get("character_id") or m.get("character") or "") for m in cast)
        for prop in spec.get("props") or []:
            if isinstance(prop, dict) and (prop.get("prop_id") or prop.get("prop")):
                scene["props"].add(str(prop.get("prop_id") or prop.get("prop")))
        if _authored(action.get("contact_point")) or str(action.get("interaction_mode") or "").upper() == "CONTACT":
            scene["touches"] += 1
        has_line = bool(str(spec.get("dialogue") or "").strip())
        reaction = any(_authored(action.get(k)) for k in ("listener_reaction", "listener_reaction_en",
                                                          "lead_in_reaction", "lead_in_reaction_en"))
        role = str(spec.get("beat_role") or "").upper()
        mode = str(((spec.get("internal_transition_authoring") or {}).get("transition_mode")) or "").upper()
        is_dedicated = not has_line and (role == "REACTION" or mode == "REACTION_CUT")
        if has_line:
            dialogue += 1
            reacted += 1 if reaction else 0
        dedicated += 1 if is_dedicated else 0
        if role == "PAYOFF":
            payoffs.append(index)
        camera = spec.get("camera_plan") if isinstance(spec.get("camera_plan"), dict) else {}
        family = str(camera.get("motion_family") or "").upper()
        moving += 1 if family and family not in ("LOCKED", "STATIC", "NONE") else 0
        for field in FALLBACK_FIELDS:
            if field == "contact_point" and not _authored(action.get(field)):
                continue  # an absent contact is no contact, not a template
            slots += 1
            fallback += 0 if _authored(action.get(field)) else 1
    after_payoff = 0
    for index in payoffs:
        nxt = [shots[j] for j in (index, index + 1) if j < len(shots)]
        if any(_authored(((s.get("prompt_spec") or {}).get("action") or {}).get(k))
               for s in nxt for k in ("listener_reaction_en", "listener_reaction", "lead_in_reaction_en"))\
                or any(str((s.get("prompt_spec") or {}).get("beat_role") or "").upper() == "REACTION" for s in nxt):
            after_payoff += 1
    two_person = [s for s in scenes.values() if len([p for p in s["people"] if p]) >= 2]
    ledger = {key: len(contract[key]) for key in ("setup_payoff_ledger", "ledger", "dramatic_ironies",
                                                  "dramatic_irony", "signature_business")
              if isinstance(contract.get(key), (list, dict))}
    return {
        "status": "MEASURED", "plan_seconds": round(total, 1), "shots": len(shots), "scenes": len(scenes),
        "multi_person_plan_pct": _pct(multi, total),
        "dialogue_shots": dialogue, "reaction_share_pct": _pct(reacted, dialogue),
        "dedicated_reaction_shots": dedicated,
        "payoffs": len(payoffs), "reaction_after_payoff_pct": _pct(after_payoff, len(payoffs)),
        "props_per_scene": round(sum(len(s["props"]) for s in scenes.values()) / len(scenes), 2) if scenes else None,
        "touches_per_two_person_scene": (round(sum(s["touches"] for s in two_person) / len(two_person), 2)
                                         if two_person else None),
        "camera_move_plan_pct": _pct(moving, len(shots)),
        "fallback_share_pct": _pct(fallback, slots),
        "ledger": ledger,
    }


# --------------------------------------------------------------------------- band + report
def _band_row(key: str, value: Any, source: str) -> dict[str, Any]:
    spec = BAND[key]
    row = {"metric": key, "label": spec["label"], "value": value, "source": source,
           "benchmark": {k: spec[k] for k in ("ep2", "ep3") if k in spec},
           "target": {k: spec[k] for k in ("min", "max") if k in spec}}
    if value is None:
        row["status"] = "NOT_MEASURED"
    else:
        ok = (spec.get("min") is None or value >= spec["min"]) and (spec.get("max") is None or value <= spec["max"])
        row["status"] = "IN_BAND" if ok else "OUT_OF_BAND"
    return row


def band(picture: dict[str, Any], speech: dict[str, Any], loud: dict[str, Any], plan: dict[str, Any]
         ) -> list[dict[str, Any]]:
    multi, multi_src = picture.get("faces_2plus_time_pct"), "picture_faces"
    if plan.get("multi_person_plan_pct") is not None and (multi is None or plan["multi_person_plan_pct"] > multi):
        # an over-the-shoulder back has no detectable face: the plan's declared two-in-frame time counts it
        multi, multi_src = plan["multi_person_plan_pct"], "plan_cast_incl_ots"
    moving, moving_src = picture.get("camera_moving_pct"), "picture_flow"
    if moving is None:
        moving, moving_src = plan.get("camera_move_plan_pct"), "plan_camera"
    return [
        _band_row("multi_person_time_pct", multi, multi_src),
        _band_row("speech_coverage_pct", speech.get("speech_coverage_pct"), "asr_windows"),
        _band_row("pauses_gt3s", speech.get("pauses_gt3s"), "asr_windows"),
        _band_row("pause_vs_speech_lu", loud.get("pause_vs_speech_lu"), "ebur128"),
        _band_row("camera_moving_pct", moving, moving_src),
        _band_row("fallback_share_pct", plan.get("fallback_share_pct"), "contract"),
        _band_row("props_per_scene", plan.get("props_per_scene"), "contract"),
    ]


def content_end(timeline: Any, fallback: float | None) -> float | None:
    """Story runtime of the cut (release timeline ``content_runtime_seconds``: the end card is not story)."""
    if isinstance(timeline, dict):
        value = _num(timeline.get("content_runtime_seconds"))
        if value:
            return value
        ends = [_num(s.get("output_end")) for s in timeline.get("segments") or [] if isinstance(s, dict)]
        ends = [e for e in ends if e]
        if ends:
            return max(ends)
    return fallback


def summary_line(report: dict[str, Any]) -> str:
    """One line for the fleet note / final-review report: ``in_band/measured`` + the out-of-band metrics."""
    rows = report.get("band") or []
    measured = [r for r in rows if r["status"] != "NOT_MEASURED"]
    out = [r for r in measured if r["status"] == "OUT_OF_BAND"]
    head = f"CRAFT_METRICS {len(measured) - len(out)}/{len(measured)} in band"
    if out:
        head += " · out: " + ", ".join(f"{r['metric']}={r['value']}" for r in out)
    return head


def markdown(report: dict[str, Any]) -> str:
    lines = [f"### Craft metrics vs Bilibili benchmark (report only) — {report.get('episode') or ''}".rstrip(" —"),
             "", summary_line(report), "", "| metric | value | target | ep2 | ep3 | status |", "|---|---|---|---|---|---|"]
    for row in report.get("band") or []:
        target = " ".join(f"{'≥' if k == 'min' else '≤'}{v}" for k, v in row["target"].items())
        bench = row["benchmark"]
        lines.append(f"| {row['label']} | {row['value'] if row['value'] is not None else '—'} | {target} | "
                     f"{bench.get('ep2', '—')} | {bench.get('ep3', '—')} | {row['status']} |")
    picture, plan, loud = report.get("picture") or {}, report.get("script") or {}, report.get("pause_loudness") or {}
    extra = []
    if picture.get("status") == "MEASURED":
        sl = picture["shot_length"]
        extra.append(f"shots {picture['shots']}, ASL {sl['asl']} s (median {sl['median']}, p10 {sl['p10']}, "
                     f"p90 {sl['p90']}), <2 s {sl['pct_lt2s']} %, >5 s {sl['pct_gt5s']} %")
        if picture.get("faceless_shots") is not None:
            extra.append(f"faceless object shots {picture['faceless_shots']} ({picture.get('faceless_time_pct')} % of time)")
    if loud.get("status") == "MEASURED":
        extra.append(f"music in pauses {loud['music_in_pauses_pct']} % (> {loud['music_floor_lufs']} LUFS)")
    if plan.get("status") == "MEASURED":
        extra.append(f"reaction share {plan.get('reaction_share_pct')} % of dialogue shots, dedicated reaction shots "
                     f"{plan.get('dedicated_reaction_shots')}, reaction after payoff {plan.get('reaction_after_payoff_pct')} %, "
                     f"touches per two-person scene {plan.get('touches_per_two_person_scene')}")
    if extra:
        lines += [""] + [f"* {x}" for x in extra]
    return "\n".join(lines) + "\n"


def build_report(*, video: Path | None, contract: Any = None, asr_windows: Any = None, timeline: Any = None,
                 episode: str = "", faces: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    picture: dict[str, Any] = {"status": "NOT_MEASURED", "reason": "no video"}
    if video and Path(video).is_file():
        try:
            picture = measure_picture(Path(video), end=content_end(timeline, None), faces=faces)
        except Exception as exc:  # noqa: BLE001 - report only
            picture = {"status": "NOT_MEASURED", "reason": f"{type(exc).__name__}: {exc}"}
    end = content_end(timeline, picture.get("duration_s"))
    speech = measure_speech(asr_windows, end) if end else {"status": "NOT_MEASURED", "reason": "no runtime"}
    loud: dict[str, Any] = {"status": "NOT_MEASURED", "reason": "no video or speech"}
    if video and Path(video).is_file() and speech.get("status") == "MEASURED" and end:
        try:
            loud = measure_pause_loudness(momentary_loudness(Path(video)), speech["intervals"], end)
        except Exception as exc:  # noqa: BLE001
            loud = {"status": "NOT_MEASURED", "reason": f"{type(exc).__name__}: {exc}"}
    plan = measure_contract(contract)
    report = {"schema": SCHEMA, "tool": TOOL_ID, "episode": episode, "report_only": True, "never_blocks": True,
              "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "video": str(video) if video else None, "content_seconds": end,
              "band": band(picture, speech, loud, plan),
              "picture": {k: v for k, v in picture.items() if k != "per_shot"},
              "shots": picture.get("per_shot") or [],
              "speech": {k: v for k, v in speech.items() if k != "intervals"},
              "pause_loudness": loud, "script": plan,
              "elapsed_s": round(time.monotonic() - started, 1)}
    report["summary"] = summary_line(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--asr-windows", type=Path)
    parser.add_argument("--release-timeline", type=Path)
    parser.add_argument("--episode", default="")
    parser.add_argument("--no-faces", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--md", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_report(video=args.video, contract=_read_json(args.contract),
                              asr_windows=_read_json(args.asr_windows), timeline=_read_json(args.release_timeline),
                              episode=args.episode, faces=not args.no_faces)
    except Exception as exc:  # noqa: BLE001 - report only: a crash still leaves a report
        report = {"schema": SCHEMA, "tool": TOOL_ID, "episode": args.episode, "report_only": True,
                  "status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "band": [], "summary": "CRAFT_METRICS error"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.md:
        args.md.write_text(markdown(report), encoding="utf-8")
    print(report.get("summary", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
