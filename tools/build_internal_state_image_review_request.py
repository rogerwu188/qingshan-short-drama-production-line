#!/usr/bin/env python3
"""Build tier-aware AI review requests for multi-reference internal-shot stills."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


TASK_SUFFIX = re.compile(r"-STILL-(?:(?:V|R)\d+|IDENTITY-R\d+)$")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_key(value: str) -> str:
    """Normalize U01-C1 and U01-C01 to the same lookup key."""
    match = re.fullmatch(r"(.+-U\d+)-C0*(\d+)", value)
    if not match:
        raise ValueError(f"Unsupported internal-shot id: {value}")
    return f"{match.group(1)}-C{int(match.group(2))}"


def task_state_id(task_key: str) -> str:
    base = TASK_SUFFIX.sub("", task_key)
    if base == task_key:
        raise ValueError(f"Unsupported task key: {task_key}")
    return state_key(base)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvest-report", action="append", required=True)
    parser.add_argument("--batch-manifest", action="append", required=True)
    parser.add_argument("--state-plan", required=True)
    parser.add_argument("--production-manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if len(args.harvest_report) != len(args.batch_manifest):
        raise ValueError("Each harvest report must have one matching batch manifest")

    state_plan_path = Path(args.state_plan).resolve()
    production_path = Path(args.production_manifest).resolve()
    state_plan = load_json(state_plan_path)
    production = load_json(production_path)
    policy = production["production_policy"]["image_validation"]
    core_ids = set(policy["core_shot_ids"])

    slots = {state_key(item["internal_shot_id"]): item for item in state_plan["slots"]}
    production_shots = {item["shot_id"]: item for item in production["shots"]}
    batch_tasks: dict[str, dict] = {}
    source_manifests = []
    for manifest_name in args.batch_manifest:
        path = Path(manifest_name).resolve()
        manifest = load_json(path)
        source_manifests.append({"path": str(path), "sha256": file_sha256(path)})
        for task in manifest["tasks"]:
            key = state_key(task["shot_id"])
            if key in batch_tasks:
                raise ValueError(f"Duplicate batch state: {key}")
            batch_tasks[key] = task

    harvested: dict[str, dict] = {}
    source_reports = []
    for report_name in args.harvest_report:
        report_path = Path(report_name).resolve()
        report = load_json(report_path)
        if not report.get("all_completed"):
            raise ValueError(f"Harvest report is not complete: {report_path}")
        source_reports.append({"path": str(report_path), "sha256": file_sha256(report_path)})
        for result in report.get("results", []):
            if result.get("remote_status") != "completed" or not result.get("output_path"):
                continue
            key = task_state_id(result["task_key"])
            if key in harvested:
                raise ValueError(f"Duplicate harvested state: {key}")
            candidate = Path(result["output_path"]).resolve()
            if not candidate.is_file():
                raise FileNotFoundError(candidate)
            actual_sha = file_sha256(candidate)
            if actual_sha != result.get("sha256"):
                raise ValueError(f"Candidate SHA mismatch for {key}")
            harvested[key] = {**result, "candidate": candidate, "sha256": actual_sha}

    items = []
    for key in sorted(harvested):
        if key not in slots or key not in batch_tasks:
            raise ValueError(f"State missing from plan or batch: {key}")
        slot = slots[key]
        task = batch_tasks[key]
        source_shot_id = slot["source_shot_id"]
        source_shot = production_shots[source_shot_id]
        contract = task["prompt_contract"]
        tier = "CORE" if source_shot_id in core_ids else "NON_CORE"
        minimum = policy["core_min_score"] if tier == "CORE" else policy["non_core_min_score"]
        result = harvested[key]
        items.append(
            {
                "path": str(result["candidate"]),
                "scope": "shot",
                "kind": "image",
                "importance": "critical" if tier == "CORE" else "standard",
                "pass_score": minimum / 20.0,
                "clip_id": key,
                "metadata": {
                    "episode": production["episode"],
                    "scene_id": task["scene_id"],
                    "source_shot_id": source_shot_id,
                    "candidate_sha256": result["sha256"],
                    "source_script_sha256": production["source"]["script_sha256"],
                    "image_tier": tier,
                    "minimum_score_100": minimum,
                    "state_id": slot["state_id"],
                    "decisive_moment": slot["decisive_moment"],
                    "visible_characters": contract["visible_characters"],
                    "review_focus": [
                        f"must depict this one decisive internal-shot state: {slot['decisive_moment']}",
                        f"must remain inside source-shot action: {source_shot['action']}",
                        "canonical identity, age, gender, costume and role continuity for every visible character",
                        "single continuous cinematic frame, not a collage, contact sheet or storyboard grid",
                        "no readable or pseudo-readable text, watermark, logo, duplicated identity, fused limbs or extra people",
                    ],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        )

    if len(items) != len(harvested):
        raise RuntimeError("Review item count mismatch")
    output = {
        "schema": "qingshan.internal_state_image_review_request.v1",
        "episode": production["episode"],
        "policy": policy,
        "state_plan": {"path": str(state_plan_path), "sha256": file_sha256(state_plan_path)},
        "production_manifest": {"path": str(production_path), "sha256": file_sha256(production_path)},
        "source_batch_manifests": source_manifests,
        "source_harvest_reports": source_reports,
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
