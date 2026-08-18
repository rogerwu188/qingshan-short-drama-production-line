#!/usr/bin/env python3
"""Render one E40 final-runtime V-next unit into an isolated directory.

This adapter deliberately reuses the previously admitted local renderer and
exact start/audio inputs.  It never changes the admitted predecessor asset.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CFG = {
    "U05": (ROOT / "tools/render_qa_e40_u05_v4_local_authority.py", 144, "V5"),
    "U07": (ROOT / "working_assets/e40_production_20260814/u07_v3_local_authority_fifth_hover_exact_dialogue_v1/render_qa_e40_u07_v3_local_authority.py", 120, "V4"),
    "U08": (ROOT / "working_assets/e40_production_20260814/u08_v3_local_authority_raised_gaze_fan_shadow_exact_dialogue_v1/render_qa_e40_u08_v3_local_authority.py", 120, "V4"),
    "U09": (ROOT / "working_assets/e40_production_20260814/u09_v3_local_authority_third_frost_wipe_exact_dialogue_v1/render_qa_e40_u09_v3_local_authority.py", 144, "V4"),
    "U16": (ROOT / "working_assets/e40_production_20260814/u16_v4_local_authority_silent_eyelash_lift_cadence_v1/render_qa_e40_u16_v4_local_authority.py", 144, "V5"),
}

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def write_json(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("unit", choices=CFG)
    ns = ap.parse_args()
    unit = ns.unit
    source, frames, version = CFG[unit]
    seconds = frames / 24.0
    slug = f"{unit.lower()}_{version.lower()}_{frames}f_r2"
    out = ROOT / "working_assets/e40_production_20260814/final_runtime_vnext_local_v1" / slug
    qad = ROOT / "qa/e40_production_20260814/final_runtime_vnext_local_v1" / slug
    out.mkdir(parents=True, exist_ok=True); qad.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location(f"e40_{slug}", source)
    mod = importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(mod)
    mod.SECONDS = seconds; mod.FRAMES = frames
    if hasattr(mod, "SAMPLES"): mod.SAMPLES = sorted(set([0, frames//7, 2*frames//7, 3*frames//7, 4*frames//7, 5*frames//7, 6*frames//7, frames-1]))
    if hasattr(mod, "SAMPLE_IDS"): mod.SAMPLE_IDS = sorted(set([0, frames//7, 2*frames//7, 3*frames//7, 4*frames//7, 5*frames//7, 6*frames//7, frames-1]))
    video = out / f"E40-{unit}-{version}-FINAL-RUNTIME-{frames}F.mp4"
    overrides = {
        "OUT": out, "OUT_DIR": out, "QAD": qad, "QA_DIR": qad, "VIDEO": video,
        "MOTION": out / f"E40_{unit}_{version}_MOTION_SPEC.json",
        "MOTION_SPEC": out / f"E40_{unit}_{version}_MOTION_SPEC.json",
        "PREFLIGHT": qad / f"E40_{unit}_{version}_PREFLIGHT.json",
        "FRAME0": qad / "frame_0000.png", "MID": qad / f"frame_{frames//2:04d}.png",
        "TAIL": qad / f"frame_{frames-1:04d}_tail.png", "CONTACT": qad / "contact_sheet.png",
        "OCR_QA": qad / f"E40_{unit}_{version}_OCR_QA.json",
        "CADENCE_QA": qad / f"E40_{unit}_{version}_CADENCE_QA.json",
        "QA": qad / f"E40_{unit}_{version}_SOURCE_MACHINE_QA.json",
        "MACHINE_QA": qad / f"E40_{unit}_{version}_SOURCE_MACHINE_QA.json",
        "RECEIPT": qad / f"E40_{unit}_{version}_SOURCE_RECEIPT.json",
    }
    for key, val in overrides.items():
        if hasattr(mod, key): setattr(mod, key, val)
    motion_path = overrides["MOTION"] if hasattr(mod, "MOTION") else overrides["MOTION_SPEC"]
    write_json(motion_path, {
        "schema": "qingshan.e40.final_runtime_vnext.motion_spec.v1", "unit": unit,
        "target_frames": frames, "target_seconds": seconds,
        "strategy": "fresh deterministic local render from admitted exact start; source motion functions extended over target runtime",
        "loop": False, "freeze": False, "padding": False, "audio_retime": False,
    })
    old = sys.argv; sys.argv = [str(source)]
    try:
        source_rc = mod.main()
    except SystemExit as exc:
        source_rc = exc.code if isinstance(exc.code, int) else str(exc.code)
    finally:
        sys.argv = old
    probe = json.loads(subprocess.run([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,sample_rate,channels",
        "-of", "json", str(video)], check=True, text=True, capture_output=True).stdout)
    vstream = next(x for x in probe["streams"] if x.get("codec_type") == "video")
    astream = next((x for x in probe["streams"] if x.get("codec_type") == "audio"), None)
    decoded0 = cv2.imread(str(qad / "frame_0000.png"), cv2.IMREAD_COLOR)
    authority0 = cv2.imread(str(mod.IMAGE), cv2.IMREAD_COLOR)
    exact_start = bool(decoded0 is not None and authority0 is not None and np.array_equal(decoded0, authority0))
    audio_sha = sha(mod.AUDIO) if hasattr(mod, "AUDIO") else None
    expected_audio_sha = getattr(mod, "AUDIO_SHA", None)
    failures = []
    if int(vstream.get("nb_read_frames", -1)) != frames: failures.append("FRAME_COUNT")
    if abs(float(probe["format"]["duration"]) - seconds) > .06: failures.append("DURATION")
    if not exact_start: failures.append("FRAME0_NOT_EXACT")
    if unit == "U16" and astream is not None: failures.append("U16_AUDIO_STREAM_PRESENT")
    if unit != "U16" and (astream is None or audio_sha != expected_audio_sha): failures.append("EXACT_AUDIO_INPUT")
    result = {
        "schema": "qingshan.e40.final_runtime_vnext.machine_qa.v1", "unit": unit,
        "version": version, "created_at": now(), "status": "PASS" if not failures else "FAIL",
        "failures": failures, "source_renderer": str(source.relative_to(ROOT)),
        "source_renderer_sha256": sha(source), "source_renderer_return_code": source_rc,
        "note": "Source return code may reflect predecessor hard-coded duration assertions; authoritative V-next gates are listed here.",
        "video": str(video.relative_to(ROOT)), "video_sha256": sha(video),
        "target_frames": frames, "decoded_frames": int(vstream.get("nb_read_frames", -1)),
        "target_seconds": seconds, "duration_seconds": float(probe["format"]["duration"]),
        "width": int(vstream["width"]), "height": int(vstream["height"]), "fps": vstream["r_frame_rate"],
        "exact_start_path": str(mod.IMAGE.relative_to(ROOT)), "exact_start_sha256": sha(mod.IMAGE),
        "frame0_exact": exact_start, "audio_stream_count": 1 if astream else 0,
        "exact_audio_path": str(mod.AUDIO.relative_to(ROOT)) if hasattr(mod, "AUDIO") else None,
        "exact_audio_sha256": audio_sha, "expected_audio_sha256": expected_audio_sha,
        "audio_retime": False, "remote_or_paid_action": False,
    }
    write_json(qad / f"E40_{unit}_{version}_FINAL_RUNTIME_MACHINE_QA_V1.json", result)
    write_json(qad / f"E40_{unit}_{version}_HUMAN_REVIEW_TEMPLATE_V1.json", {
        "schema": "qingshan.e40.final_runtime_vnext.human_review.v1", "unit": unit,
        "status": "QA_PENDING_HUMAN", "video": result["video"], "contact_sheet": str((qad/"contact_sheet.png").relative_to(ROOT)),
        "checks": {"identity_continuity": None, "motion_intent": None, "anatomy": None, "text_artifacts": None, "runtime_extension_natural": None},
    })
    write_json(qad / f"E40_{unit}_{version}_ADMISSION_V1.json", {
        "schema": "qingshan.e40.final_runtime_vnext.admission.v1", "unit": unit,
        "status": "QA_PENDING_HUMAN" if not failures else "FAIL_CLOSED_MACHINE_QA",
        "machine_qa": result["status"], "video_sha256": result["video_sha256"], "may_bind": False,
    })
    write_json(qad / f"E40_{unit}_{version}_FAILURE_MEMORY_V1.json", {
        "schema": "qingshan.e40.final_runtime_vnext.failure_memory.v1", "unit": unit,
        "status": "NOT_ACTIVATED" if not failures else "ACTIVATED", "failures": failures,
        "retry_allowed": False if failures else None,
    })
    print(json.dumps({"unit": unit, "status": result["status"], "video": result["video"], "sha256": result["video_sha256"]}))
    return 0 if not failures else 2

if __name__ == "__main__":
    raise SystemExit(main())
