#!/usr/bin/env python3
"""Build a minimal exact-SHA state pool while preserving every raw QA decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


HARD_STOP_CHECKS = {"canonical_identity_continuity", "native_anatomy"}
RISK_WEIGHTS = {
    "story_action_clarity": 1,
    "no_text_or_pseudotext": 2,
    "scene_authority": 3,
    "no_extra_or_duplicated_bodies": 4,
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def raw_failure_checks(row: dict) -> list[str]:
    analysis = (row.get("capabilities") or {}).get("image_analysis") or {}
    checks = analysis.get("checks") or {}
    return sorted(key for key, value in checks.items() if str(value).upper() != "PASS")


def candidate_rank(row: dict) -> tuple:
    failures = row["raw_failure_checks"]
    risk = sum(RISK_WEIGHTS.get(check, 8) for check in failures)
    return (risk, len(failures), -row["confidence"], -row["score"], row["state_task_key"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--review", required=True, action="append", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    plan = load(args.plan)
    episode = args.episode.upper()
    if plan.get("episode") != episode:
        raise ValueError("episode mismatch")

    candidates: dict[str, dict] = {}
    invalid_wrapper_rows: dict[str, dict] = {}
    source_reviews: list[str] = []
    for review_path in args.review:
        source_reviews.append(relative_or_absolute(review_path, root))
        for row in load(review_path).get("items", []):
            metadata = (row.get("agentcut") or {}).get("metadata") or {}
            state_id = metadata.get("state_id")
            if not state_id:
                continue
            state_key = f"{state_id}-STILL-V1"
            if row.get("required_capability_failures"):
                invalid_wrapper_rows[state_key] = {
                    "row": row,
                    "review_path": review_path,
                    "metadata": metadata,
                }
                continue
            media = Path(row.get("media_path") or "")
            if not media.is_file():
                continue
            actual_sha = sha256(media)
            if actual_sha != row.get("media_sha256") or actual_sha != metadata.get("candidate_sha256"):
                continue
            failures = raw_failure_checks(row)
            analysis = (row.get("capabilities") or {}).get("image_analysis") or {}
            candidate = {
                "state_task_key": state_key,
                "state_id": state_id,
                "source_shot_id": re.sub(r"-C\d+$", "", state_id),
                "path": relative_or_absolute(media, root),
                "absolute_path": str(media.resolve()),
                "sha256": actual_sha,
                "review_id": row.get("review_id"),
                "source_review": relative_or_absolute(review_path, root),
                "raw_status": row.get("status"),
                "raw_failure_checks": failures,
                "raw_issues": row.get("issues") or [],
                "score": float((row.get("scoring") or {}).get("score") or 0),
                "confidence": float(analysis.get("confidence") or 0),
                "hard_stop_failure": bool(HARD_STOP_CHECKS.intersection(failures)),
            }
            previous = candidates.get(state_key)
            if previous is None or candidate["review_id"] != previous["review_id"]:
                candidates[state_key] = candidate

    # A successful standalone visual invocation may have populated the exact-SHA
    # cache before the batch wrapper was repaired. Admit that evidence only when
    # every required visual/OCR check is an explicit PASS.
    if args.cache_dir:
        for state_key, fallback in invalid_wrapper_rows.items():
            if state_key in candidates:
                continue
            row = fallback["row"]
            metadata = fallback["metadata"]
            media = Path(row.get("media_path") or "")
            expected_sha = row.get("media_sha256")
            cache_path = args.cache_dir / f"{expected_sha}.json"
            if not media.is_file() or sha256(media) != expected_sha or not cache_path.is_file():
                continue
            cache = load(cache_path)
            checks = cache.get("checks") or ((cache.get("evidence") or [{}])[0].get("checks") or {})
            required = {
                "canonical_identity_continuity", "scene_authority", "story_action_clarity",
                "no_text_or_pseudotext", "no_extra_or_duplicated_bodies", "native_anatomy",
            }
            if cache.get("status") != "PASS" or any(checks.get(key) != "PASS" for key in required):
                continue
            state_id = metadata["state_id"]
            candidates[state_key] = {
                "state_task_key": state_key,
                "state_id": state_id,
                "source_shot_id": re.sub(r"-C\d+$", "", state_id),
                "path": relative_or_absolute(media, root),
                "absolute_path": str(media.resolve()),
                "sha256": expected_sha,
                "review_id": "EXACT_SHA_RUNTIME_CACHE",
                "source_review": relative_or_absolute(fallback["review_path"], root),
                "source_visual_cache": relative_or_absolute(cache_path, root),
                "raw_status": "PASS",
                "raw_failure_checks": [],
                "raw_issues": [],
                "score": 5.0,
                "confidence": float(cache.get("confidence") or 0),
                "hard_stop_failure": False,
                "wrapper_history": {
                    "status": row.get("status"),
                    "required_capability_failures": row.get("required_capability_failures"),
                    "preserved": True,
                },
            }

    selected_keys: set[str] = set()
    units_out: list[dict] = []
    unselected_failures: list[dict] = []
    failures: list[str] = []

    for unit in plan.get("units", []):
        expected_keys = unit.get("state_task_keys") or []
        rows = [candidates[key] for key in expected_keys if key in candidates]
        missing = sorted(set(expected_keys) - set(candidates))
        if missing:
            failures.append(f"{unit['unit_id']}:missing_valid_qa:{','.join(missing)}")
        eligible = [row for row in rows if not row["hard_stop_failure"]]
        chosen = [row for row in eligible if row["raw_status"] == "PASS"]

        # Every editorial shot must have at least one state before video compilation.
        for shot_id in unit.get("editorial_shot_ids") or []:
            if any(row["source_shot_id"] == shot_id for row in chosen):
                continue
            options = [
                row for row in eligible
                if row["source_shot_id"] == shot_id and row not in chosen
            ]
            if not options:
                failures.append(f"{unit['unit_id']}:no_usable_state_for_shot:{shot_id}")
                continue
            chosen.append(min(options, key=candidate_rank))

        minimum = 3 if unit.get("action_unit") else 2
        for row in sorted((row for row in eligible if row not in chosen), key=candidate_rank):
            if len(chosen) >= minimum:
                break
            chosen.append(row)
        if len(chosen) < minimum:
            failures.append(f"{unit['unit_id']}:state_minimum:{len(chosen)}<{minimum}")

        order = {key: index for index, key in enumerate(expected_keys)}
        chosen.sort(key=lambda row: order[row["state_task_key"]])
        selections = []
        for row in chosen:
            selected_keys.add(row["state_task_key"])
            conditional = row["raw_status"] != "PASS"
            selections.append({
                **row,
                "admission": "CONDITIONAL_MACHINE_ADMISSION" if conditional else "PASS",
                "selection_reason": (
                    "Needed to preserve source-shot coverage or the unit state minimum; selected as the lowest-risk exact-SHA candidate after targeted QA."
                    if conditional else
                    "Exact-SHA candidate passed the required image-analysis and OCR capabilities."
                ),
                "rollback_point": row["sha256"],
                "replacement_condition": (
                    "Replace only with a later exact-script, exact-identity candidate that passes all remaining checks."
                    if conditional else None
                ),
            })
        units_out.append({
            "unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "action_unit": bool(unit.get("action_unit")),
            "editorial_shot_ids": unit.get("editorial_shot_ids") or [],
            "required_state_count": minimum,
            "selected_state_count": len(selections),
            "selected_states": selections,
        })

    for row in sorted(candidates.values(), key=lambda item: item["state_task_key"]):
        if row["raw_status"] != "PASS" and row["state_task_key"] not in selected_keys:
            unselected_failures.append(row)

    all_selected = [row for unit in units_out for row in unit["selected_states"]]
    conditional_count = sum(row["admission"] == "CONDITIONAL_MACHINE_ADMISSION" for row in all_selected)
    output = {
        "schema": "qingshan.video_unit_state_pool_admission.v1",
        "episode": episode,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "BLOCKED" if failures else ("PASS_WITH_CONDITIONAL_ADMISSION" if conditional_count else "PASS"),
        "source_plan": relative_or_absolute(args.plan, root),
        "source_plan_sha256": sha256(args.plan),
        "source_reviews": source_reviews,
        "policy": {
            "preserve_all_direct_passes": True,
            "conditional_failures_are_not_rewritten": True,
            "every_editorial_shot_requires_state": True,
            "minimum_states_per_unit": 2,
            "minimum_states_per_action_unit": 3,
            "selection": "minimum additional FAIL candidates, ranked by reversible risk",
        },
        "unit_count": len(units_out),
        "selected_state_count": len(all_selected),
        "direct_pass_count": len(all_selected) - conditional_count,
        "conditional_admission_count": conditional_count,
        "unselected_raw_fail_count": len(unselected_failures),
        "failures": failures,
        "units": units_out,
        "unselected_raw_failures": unselected_failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": output["status"],
        "units": output["unit_count"],
        "selected": output["selected_state_count"],
        "direct_pass": output["direct_pass_count"],
        "conditional": output["conditional_admission_count"],
        "unselected_fail": output["unselected_raw_fail_count"],
        "failures": failures,
    }, ensure_ascii=False))
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
