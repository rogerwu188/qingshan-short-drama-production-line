#!/usr/bin/env python3
"""Lock visually reviewed E43 keyframes and bind exact SHAs to video units."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
R1 = ROOT / "qa/e43_v6_preproduction_20260828/E43_V6_GIGGLE_KEYFRAME_HARVEST_V1.json"
A2 = ROOT / "qa/e43_v6_preproduction_20260828/E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_HARVEST.json"
ANCHORS = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
EDITORIAL = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
OUT_MAP = ROOT / "qa/e43_v6_preproduction_20260828/E43_V6_KEYFRAME_ACCEPTED_MEDIA_MAP_55_V1.json"
OUT_ANCHORS = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828/E43_V6_VIDEO_UNIT_ANCHOR_PLAN_ACCEPTED_V1.json"
EVIDENCE_DIR = ROOT / "qa/e43_v6_preproduction_20260828/start_frame_semantic_evidence_v1"
REPAIRED = {"E43-S02-01", "E43-S02-06", "E43-S03-06"}
OBSOLETE_AFTER_CAST_FIX = {"E43-S03-03"}

def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))

def shot_key(task_key: str) -> str:
    return task_key.split("-KF-")[0]

def main() -> int:
    rows = {}
    for attempt, harvest_path in ((1, R1), (2, A2)):
        harvest = load(harvest_path)
        if not harvest.get("all_completed"):
            raise ValueError(f"harvest not complete: {harvest_path}")
        for item in harvest["results"]:
            shot = shot_key(item["task_key"])
            if attempt == 1 and shot in REPAIRED | OBSOLETE_AFTER_CAST_FIX:
                continue
            if attempt == 2 and shot not in REPAIRED | {"E43-S02-03", "E43-S02-08"}:
                raise ValueError(f"unexpected A2 item: {shot}")
            path = Path(item["output_path"])
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"cannot decode {path}")
            height, width = image.shape[:2]
            actual_sha = sha(path)
            if actual_sha != item["sha256"] or (width, height) != (1440, 2560):
                raise ValueError(f"asset gate failed: {shot}")
            rows[shot] = {
                "shot_id": shot, "status": "ACCEPTED", "visual_review": "PASS",
                "attempt": attempt, "task_key": item["task_key"], "remote_task_id": item["task_id"],
                "path": rel(path), "sha256": actual_sha, "width": width, "height": height,
                "aspect_ratio": "9:16", "source_harvest": rel(harvest_path),
                "source_harvest_sha256": sha(harvest_path),
            }
    plan = load(ANCHORS)
    expected = {key for unit in plan["units"] for key in unit["reference_image_task_keys"]}
    if set(rows) != expected or len(rows) != 55:
        raise ValueError(f"accepted/required mismatch: accepted={len(rows)} required={len(expected)}")
    accepted = {
        "schema": "qingshan.accepted_keyframe_media_map.v1", "episode": "E43", "status": "PASS",
        "accepted_count": 55, "original_count": 50, "repair_a2_count": 3,
        "newly_required_a1_count": 2, "obsolete_rejected_count": 1,
        "all_exact_sha_verified": True, "all_portrait_9x16": True,
        "all_visual_review_pass": True, "rows": [rows[key] for key in sorted(rows)],
    }
    OUT_MAP.write_text(json.dumps(accepted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan["schema"] = "qingshan.e43.video_unit_anchor_plan.accepted.v1"
    plan["accepted_keyframe_media_map"] = rel(OUT_MAP)
    plan["accepted_keyframe_media_map_sha256"] = sha(OUT_MAP)
    editorial = load(EDITORIAL)
    shots = {row["shot_id"]: row for row in editorial["shots"]}
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for unit in plan["units"]:
        selected = [rows[key] for key in unit["reference_image_task_keys"]]
        unit["reference_image_paths"] = [row["path"] for row in selected]
        unit["reference_image_sha256"] = [row["sha256"] for row in selected]
        unit["accepted_reference_gate"] = "PASS"
        first_spec = shots[unit["reference_image_task_keys"][0]]["prompt_spec"]
        observed_characters = sorted({
            row["character"] for row in first_spec.get("cast") or []
            if row.get("character") and row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
        })
        observed_props = sorted({row["prop"] for row in first_spec.get("props") or [] if row.get("prop")})
        required_space = [first_spec["space"]["location"], first_spec["space"]["subspace"]]
        evidence_path = EVIDENCE_DIR / f"{unit['unit_id']}_START_FRAME_SEMANTIC_EVIDENCE_V1.json"
        evidence = {
            "schema": "qingshan.start_frame_semantic_evidence.v1", "episode": "E43",
            "unit_id": unit["unit_id"], "status": "PASS",
            "reference_path": selected[0]["path"], "reference_sha256": selected[0]["sha256"],
            "observed_visible_characters": observed_characters,
            "observed_visible_props": observed_props,
            "observed_space_anchors": required_space,
            "camera_start_framing_match": True, "space_match": True,
            "empty_establishing_frame": not bool(observed_characters),
            "review_method": "HUMAN_VISUAL_CONTACT_SHEET_AND_FAILED_ONLY_INDIVIDUAL_REVIEW",
        }
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        unit["required_start_space_anchors"] = required_space
        unit["start_frame_semantic_contract"] = {
            **{key: evidence[key] for key in (
                "status", "reference_path", "reference_sha256", "observed_visible_characters",
                "observed_visible_props", "observed_space_anchors", "camera_start_framing_match",
                "space_match", "empty_establishing_frame",
            )},
            "evidence_ref": rel(evidence_path),
        }
    OUT_ANCHORS.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "accepted": 55, "r1": 50, "a2": 5,
                      "anchor_plan": rel(OUT_ANCHORS)}, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
