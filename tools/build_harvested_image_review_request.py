#!/usr/bin/env python3
"""Build one tier-aware AI image review request from harvested Giggle batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shot_id_from_task_key(task_key: str) -> str:
    marker = "-STILL-"
    if marker in task_key:
        return task_key.split(marker, 1)[0]
    raise ValueError(f"Unsupported task key: {task_key}")


def video_unit_id_from_state_id(state_id: str) -> str:
    return re.sub(r"-C\d+$", "", state_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvest-report", action="append", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--scene-state", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    scene_state_path = Path(args.scene_state).resolve()
    manifest = load_json(manifest_path)
    scene_state = load_json(scene_state_path)
    shots = {item["shot_id"]: item for item in manifest["shots"]}
    scenes = {item["scene_id"]: item for item in scene_state["scene_state"]}
    policy = manifest["production_policy"]["image_validation"]
    core_ids = set(policy["core_shot_ids"])

    harvested: dict[str, dict] = {}
    source_reports: list[str] = []
    for report_name in args.harvest_report:
        report_path = Path(report_name).resolve()
        report = load_json(report_path)
        if not args.allow_partial and not report.get("all_completed"):
            raise ValueError(f"Harvest report is not complete: {report_path}")
        source_reports.append(str(report_path))
        for result in report.get("results", []):
            if result.get("remote_status") != "completed" or not result.get("output_path"):
                continue
            shot_id = shot_id_from_task_key(result["task_key"])
            if shot_id in harvested:
                raise ValueError(f"Duplicate harvested shot: {shot_id}")
            candidate = Path(result["output_path"]).resolve()
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            actual_sha = file_sha256(candidate)
            if actual_sha != result.get("sha256"):
                raise ValueError(f"Candidate SHA mismatch for {shot_id}")
            harvested[shot_id] = {**result, "candidate": candidate, "sha256": actual_sha}

    items = []
    for shot_id in sorted(harvested):
        video_unit_id = video_unit_id_from_state_id(shot_id)
        if video_unit_id not in shots:
            raise ValueError(f"Unknown shot in harvest: {shot_id}")
        shot = shots[video_unit_id]
        scene = scenes[shot["scene_id"]]
        tier = "CORE" if video_unit_id in core_ids else "NON_CORE"
        minimum = policy["core_min_score"] if tier == "CORE" else policy["non_core_min_score"]
        result = harvested[shot_id]
        items.append(
            {
                "path": str(result["candidate"]),
                "scope": "shot",
                "kind": "image",
                "importance": "critical" if tier == "CORE" else "standard",
                "pass_score": minimum / 20.0,
                "clip_id": shot_id,
                "metadata": {
                    "episode": manifest["episode"],
                    "source_shot_id": video_unit_id,
                    "video_unit_id": video_unit_id,
                    "state_id": shot_id,
                    "scene_id": shot["scene_id"],
                    "candidate_sha256": result["sha256"],
                    "source_script_sha256": manifest["source"]["script_sha256"],
                    "image_tier": tier,
                    "minimum_score_100": minimum,
                    "review_focus": [
                        f"location must read as {scene['location']}",
                        f"time of day must read as {scene['time_of_day']}",
                        f"weather/environment must read as {scene['weather']}",
                        f"story action must clearly depict: {shot['action']}",
                        "canonical character identity, age, gender and costume continuity",
                        "single continuous cinematic frame, not a collage, contact sheet or storyboard grid",
                        "no readable or pseudo-readable text, watermark, logo, duplicated identity, fused limbs or extra people",
                    ],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        )

    output = {
        "schema": "qingshan.harvested_image_review_request.v1",
        "episode": manifest["episode"],
        "policy": policy,
        "manifest": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "source_harvest_reports": source_reports,
        "partial_harvest_allowed": args.allow_partial,
        "item_count": len(items),
        "items": items,
    }
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": "PASS", "items": len(items), "out": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
