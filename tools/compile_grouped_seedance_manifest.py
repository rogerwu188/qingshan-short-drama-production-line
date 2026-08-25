#!/usr/bin/env python3
"""Compile editorial Seedance rows into scene-local grouped video-unit preflight rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def compile_manifest(grouping: dict[str, Any], anchors: dict[str, Any], editorial: dict[str, Any]) -> dict[str, Any]:
    anchor_by_unit = {row["unit_id"]: row for row in anchors.get("units") or []}
    shot_by_id = {row["shot_id"]: row for row in editorial.get("shots") or []}
    units: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        unit_id = unit["unit_id"]
        anchor = anchor_by_unit.get(unit_id)
        if not anchor:
            raise ValueError(f"{unit_id} missing anchor decision")
        paths = anchor.get("reference_image_paths") or []
        if len(paths) != int(anchor.get("planned_reference_image_count", -1)):
            raise ValueError(f"{unit_id} anchor count mismatch")
        references = []
        for value in paths:
            path = resolve(value)
            if not path.is_file():
                raise ValueError(f"{unit_id} anchor missing: {value}")
            references.append({"path": value, "sha256": digest(path), "role": "SCENE_START_ANCHOR"})
        shots = [shot_by_id[shot_id] for shot_id in unit["editorial_shot_ids"]]
        if any(row.get("model") != "seedance-2.0-fast" for row in shots):
            raise ValueError(f"{unit_id} contains forbidden model")
        if any(row.get("resolution") != "720p" for row in shots):
            raise ValueError(f"{unit_id} contains forbidden resolution")
        prompt_specs = [row.get("prompt_spec") or {} for row in shots]
        units.append({
            "unit_id": unit_id,
            "scene_id": unit["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "model": "seedance-2.0-fast",
            "resolution": "720p",
            "editorial_shot_ids": unit["editorial_shot_ids"],
            "narrative_beat": unit["narrative_beat"],
            "reference_images": references,
            "ordered_prompt_specs": prompt_specs,
            "native_audio_contract": "SAME_VIDEO_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_ACTION_SOUND",
            "submission_status": "NOT_AUTHORIZED_UNTIL_REGISTERED_GROUPED_PREFLIGHT_PASS",
            "paid_attempt": 0,
            "remote_task_id": None,
        })
    if len(units) != int(grouping.get("video_unit_count", -1)):
        raise ValueError("compiled unit count mismatch")
    runtime = round(sum(float(row["duration_seconds"]) for row in units), 6)
    if runtime != round(float(grouping.get("runtime_seconds", -1)), 6):
        raise ValueError("compiled runtime mismatch")
    return {
        "schema": "qingshan.grouped_seedance_manifest.v1",
        "episode": grouping.get("episode"),
        "video_unit_count": len(units),
        "runtime_seconds": runtime,
        "grouping_plan_sha256": None,
        "anchor_plan_sha256": None,
        "editorial_seedance_manifest_sha256": None,
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouping-plan", type=Path, required=True)
    parser.add_argument("--anchor-plan", type=Path, required=True)
    parser.add_argument("--editorial-seedance-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compile_manifest(load(args.grouping_plan), load(args.anchor_plan), load(args.editorial_seedance_manifest))
    result["grouping_plan_sha256"] = digest(args.grouping_plan)
    result["anchor_plan_sha256"] = digest(args.anchor_plan)
    result["editorial_seedance_manifest_sha256"] = digest(args.editorial_seedance_manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(result["units"]), "runtime_seconds": result["runtime_seconds"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
