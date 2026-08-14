#!/usr/bin/env python3
"""Validate script-locked cinematic shot contracts before image/video generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REQUIRED = {
    "duration_seconds", "shot_scale", "lens_intent", "camera_height", "camera_motion",
    "depth_layers", "scale_anchor", "palette", "key_light", "atmosphere",
    "environmental_motion", "material_detail", "still_prompt_contract",
    "video_motion_contract", "negative_constraints",
}
LOCKED = ("location", "time_of_day", "weather", "event")


def validate(payload: dict) -> dict:
    errors: list[dict] = []
    scene = payload.get("scene_lock") or {}
    for field in LOCKED:
        if not scene.get(field):
            errors.append({"scope": "scene_lock", "field": field, "error": "missing"})

    shots = payload.get("shots") or []
    if not shots:
        errors.append({"scope": "shots", "error": "empty"})
    for index, shot in enumerate(shots, 1):
        missing = sorted(field for field in REQUIRED if shot.get(field) in (None, "", []))
        for field in missing:
            errors.append({"scope": f"shot_{index}", "field": field, "error": "missing"})
        duration = shot.get("duration_seconds")
        if duration is not None and not 4 <= duration <= 15:
            errors.append({"scope": f"shot_{index}", "field": "duration_seconds", "error": "must_be_4_to_15"})
        if len(shot.get("depth_layers") or []) < 3:
            errors.append({"scope": f"shot_{index}", "field": "depth_layers", "error": "minimum_3"})
        palette = shot.get("palette") or {}
        for role in ("dominant", "contrast", "accent"):
            if not palette.get(role):
                errors.append({"scope": f"shot_{index}", "field": f"palette.{role}", "error": "missing"})
        if len(shot.get("material_detail") or []) < 2:
            errors.append({"scope": f"shot_{index}", "field": "material_detail", "error": "minimum_2"})
        if len(shot.get("negative_constraints") or []) < 5:
            errors.append({"scope": f"shot_{index}", "field": "negative_constraints", "error": "minimum_5"})
        for field in LOCKED:
            if field in shot and shot[field] != scene.get(field):
                errors.append({"scope": f"shot_{index}", "field": field, "error": "conflicts_with_scene_lock"})
        night_words = ("night", "moonlight", "夜景", "月光", "深夜")
        locked_time = str(scene.get("time_of_day", "")).lower()
        positive_visual = {key: value for key, value in shot.items() if key != "negative_constraints"}
        combined = json.dumps(positive_visual, ensure_ascii=False).lower()
        if not any(word in locked_time for word in night_words) and any(word in combined for word in night_words):
            errors.append({"scope": f"shot_{index}", "field": "time_of_day", "error": "unmotivated_night_or_moonlight"})

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema": "qingshan.grand_cinematic_visual_gate_report.v1",
        "status": "PASS" if not errors else "FAIL",
        "shot_count": len(shots),
        "error_count": len(errors),
        "errors": errors,
        "input_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = validate(payload)
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
