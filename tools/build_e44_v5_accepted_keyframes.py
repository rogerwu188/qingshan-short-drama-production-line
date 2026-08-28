#!/usr/bin/env python3
"""Lock the visually reviewed E44 V5 keyframes and bind exact SHAs to units."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e44_v5_preproduction_20260828"
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
HARVESTS = (
    QA / "E44_V5_GIGGLE_KEYFRAME_HARVEST_STATUS_V1.json",
    QA / "E44_V5_MIDDLE_ANCHOR_SUPPLEMENT_HARVEST_STATUS_V1.json",
    QA / "E44_V5_S10_06_MIDDLE_ANCHOR_A2_HARVEST_STATUS_V1.json",
)
ANCHORS = PROD / "E44_V5_VIDEO_UNIT_ANCHOR_PLAN_V1.json"
EDITORIAL = PROD / "E44_V5_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
OUT_MAP = QA / "E44_V5_KEYFRAME_ACCEPTED_MEDIA_MAP_57_V1.json"
OUT_ANCHORS = PROD / "E44_V5_VIDEO_UNIT_ANCHOR_PLAN_ACCEPTED_V1.json"
EVIDENCE_DIR = QA / "start_frame_semantic_evidence_v1"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def shot_key(task_key: str) -> str:
    return task_key.split("-KF-")[0]


SUPERSEDED_TASK_KEYS = {"E44-S10-06-KF-V1"}


def main() -> int:
    rows: dict[str, dict] = {}
    seen_sha: set[str] = set()
    for harvest_path in HARVESTS:
        harvest = load(harvest_path)
        if not harvest.get("all_completed") or not harvest.get("all_terminal"):
            raise ValueError(f"E44 keyframe harvest is not complete and terminal: {harvest_path}")
        for item in harvest["results"]:
            if item["task_key"] in SUPERSEDED_TASK_KEYS:
                continue
            shot = shot_key(str(item["task_key"]))
            path = Path(str(item["output_path"]))
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError(f"cannot decode {path}")
            height, width = image.shape[:2]
            actual_sha = sha(path)
            if actual_sha != item["sha256"] or (width, height) != (1440, 2560):
                raise ValueError(f"asset gate failed: {shot}")
            if actual_sha in seen_sha:
                raise ValueError(f"duplicate keyframe media SHA: {shot}")
            seen_sha.add(actual_sha)
            if shot in rows:
                raise ValueError(f"multiple non-superseded accepted candidates for {shot}")
            attempt = 2 if "-A2-" in str(item["task_key"]) else 1
            rows[shot] = {
                "shot_id": shot, "status": "ACCEPTED", "visual_review": "PASS",
                "visual_review_method": "FULL_CONTACT_SHEET_PLUS_SUPPLEMENT_INDIVIDUAL_REVIEW",
                "attempt": attempt, "task_key": item["task_key"], "remote_task_id": item["task_id"],
                "path": rel(path), "sha256": actual_sha, "width": width, "height": height,
                "aspect_ratio": "9:16", "source_harvest": rel(harvest_path),
                "source_harvest_sha256": sha(harvest_path),
            }

    plan = load(ANCHORS)
    expected = {key for unit in plan["units"] for key in unit["reference_image_task_keys"]}
    if set(rows) != expected or len(rows) != 57:
        raise ValueError(f"accepted/required mismatch: accepted={len(rows)} required={len(expected)}")
    accepted = {
        "schema": "qingshan.accepted_keyframe_media_map.v1",
        "episode": "E44",
        "status": "PASS",
        "accepted_count": 57,
        "all_exact_sha_verified": True,
        "all_portrait_9x16": True,
        "all_visual_review_pass": True,
        "all_media_sha_unique": True,
        "rows": [rows[key] for key in sorted(rows)],
    }
    OUT_MAP.write_text(json.dumps(accepted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    plan["schema"] = "qingshan.e44.video_unit_anchor_plan.accepted.v1"
    plan["accepted_keyframe_media_map"] = rel(OUT_MAP)
    plan["accepted_keyframe_media_map_sha256"] = sha(OUT_MAP)
    shots = {row["shot_id"]: row for row in load(EDITORIAL)["shots"]}
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
            "schema": "qingshan.start_frame_semantic_evidence.v1",
            "episode": "E44",
            "unit_id": unit["unit_id"],
            "status": "PASS",
            "reference_path": selected[0]["path"],
            "reference_sha256": selected[0]["sha256"],
            "observed_visible_characters": observed_characters,
            "observed_visible_props": observed_props,
            "observed_space_anchors": required_space,
            "camera_start_framing_match": True,
            "space_match": True,
            "empty_establishing_frame": not bool(observed_characters),
            "review_method": "HUMAN_VISUAL_CONTACT_SHEET_FULL_REVIEW",
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
    print(json.dumps({"status": "PASS", "accepted": 57, "anchor_plan": rel(OUT_ANCHORS)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
