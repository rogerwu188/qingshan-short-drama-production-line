#!/usr/bin/env python3
"""Validate storyboard-sheet plans and their visual review evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIDE_TOKENS = ("wide", "full", "远景", "全景", "大全景")
CLOSE_TOKENS = ("close", "macro", "特写", "近景")
VALID_FIGHT_MODES = {"A_PHYSICAL", "B_WUXIA_XUANHUAN"}


def episode_number(episode: str | None) -> int | None:
    match = re.fullmatch(r"E(\d+)", str(episode or "").upper())
    return int(match.group(1)) if match else None


def requires_storyboard_sheet_gate(episode: str | None) -> bool:
    number = episode_number(episode)
    return number is not None and number >= 26


def _contains_any(value: object, tokens: tuple[str, ...]) -> bool:
    text = str(value or "").lower()
    return any(token.lower() in text for token in tokens)


def validate_plan(plan: dict) -> dict:
    failures: list[dict] = []
    episode = str(plan.get("episode") or "").upper()
    rows = plan.get("episode_rows") or []
    if len(rows) != 6:
        failures.append({"check": "episode_sheet_row_count", "expected": 6, "actual": len(rows)})

    required_row_fields = {
        "shot_no", "beat_id", "timecode", "visual", "camera", "dialogue_sfx",
        "technique", "composition_signature",
    }
    for index, row in enumerate(rows, start=1):
        missing = sorted(field for field in required_row_fields if not str(row.get(field) or "").strip())
        if missing:
            failures.append({"check": "episode_sheet_row_fields", "row": index, "missing": missing})
    signatures = [str(row.get("composition_signature") or "") for row in rows]
    if len(signatures) != len(set(signatures)):
        failures.append({"check": "episode_sheet_compositions_unique", "signatures": signatures})

    fight = plan.get("fight_sequence") or {}
    mode = str(fight.get("mode") or "")
    if mode not in VALID_FIGHT_MODES:
        failures.append({"check": "fight_mode", "expected": sorted(VALID_FIGHT_MODES), "actual": mode})
    if episode and requires_storyboard_sheet_gate(episode) and mode != "B_WUXIA_XUANHUAN":
        failures.append({"check": "qingshan_primary_fight_mode", "expected": "B_WUXIA_XUANHUAN", "actual": mode})
    fight_rows = fight.get("shots") or []
    if len(fight_rows) != 6:
        failures.append({"check": "fight_shot_count", "expected": 6, "actual": len(fight_rows)})
    required_fight_fields = {
        "shot_no", "phase", "shot_size", "camera", "action", "sfx",
        "power_visualization", "composition_signature",
    }
    for index, row in enumerate(fight_rows, start=1):
        missing = sorted(field for field in required_fight_fields if not str(row.get(field) or "").strip())
        if missing:
            failures.append({"check": "fight_shot_fields", "row": index, "missing": missing})
    fight_signatures = [str(row.get("composition_signature") or "") for row in fight_rows]
    if len(fight_signatures) != len(set(fight_signatures)):
        failures.append({"check": "fight_compositions_unique", "signatures": fight_signatures})
    sizes = [row.get("shot_size") for row in fight_rows]
    if not any(_contains_any(size, CLOSE_TOKENS) for size in sizes):
        failures.append({"check": "fight_requires_close_or_macro", "shot_sizes": sizes})
    if not any(_contains_any(size, WIDE_TOKENS) for size in sizes):
        failures.append({"check": "fight_requires_wide_or_full", "shot_sizes": sizes})
    phases = {str(row.get("phase") or "").upper() for row in fight_rows}
    for required_phase in ("SETUP", "IMPACT", "TABLEAU"):
        if required_phase not in phases:
            failures.append({"check": "fight_breath_phase", "missing": required_phase, "actual": sorted(phases)})

    return {
        "schema": "qingshan.storyboard_sheet_plan_gate.v1",
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "episode_row_count": len(rows),
        "fight_shot_count": len(fight_rows),
        "fight_mode": mode,
        "composition_signatures_unique": len(signatures) == len(set(signatures)),
        "fight_composition_signatures_unique": len(fight_signatures) == len(set(fight_signatures)),
        "failures": failures,
    }


def validate_gate_report(report: dict, episode: str) -> dict:
    failures = []
    if str(report.get("episode") or "").upper() != episode.upper():
        failures.append({"check": "storyboard_gate_episode", "expected": episode.upper(), "actual": report.get("episode")})
    if str(report.get("status") or "").upper() != "PASS":
        failures.append({"check": "storyboard_gate_status", "expected": "PASS", "actual": report.get("status")})
    if not report.get("video_generation_allowed"):
        failures.append({"check": "storyboard_video_generation_allowed", "expected": True, "actual": report.get("video_generation_allowed")})
    return {"status": "PASS" if not failures else "FAIL", "failures": failures}


def finalize(plan: dict, receipt: dict, review: dict) -> dict:
    plan_gate = validate_plan(plan)
    failures = list(plan_gate["failures"])
    tasks = receipt.get("tasks") or []
    expected_kinds = {"episode_sheet", "fight_sheet"}
    actual_kinds = {str(task.get("sheet_kind") or (task.get("metadata") or {}).get("sheet_kind") or "") for task in tasks}
    if str(receipt.get("status") or "").upper() != "BATCH_COMPLETE":
        failures.append({"check": "storyboard_sheet_batch_complete", "actual": receipt.get("status")})
    if not expected_kinds.issubset(actual_kinds):
        failures.append({"check": "storyboard_sheet_kinds", "expected": sorted(expected_kinds), "actual": sorted(actual_kinds)})
    for task in tasks:
        if str(task.get("status") or task.get("state") or "").lower() != "image_pass":
            failures.append({"check": "storyboard_sheet_image_pass", "task_key": task.get("task_key"), "actual": task.get("status") or task.get("state")})
        output = Path(str(task.get("output_path") or ""))
        if not output.is_absolute():
            output = ROOT / output
        if not output.is_file():
            failures.append({"check": "storyboard_sheet_output_exists", "task_key": task.get("task_key"), "path": str(output)})
    if str(review.get("status") or "").upper() != "PASS":
        failures.append({"check": "storyboard_sheet_ai_review", "expected": "PASS", "actual": review.get("status")})
    return {
        "schema": "qingshan.storyboard_sheet_gate.v1",
        "episode": plan_gate["episode"],
        "status": "PASS" if not failures else "FAIL",
        "video_generation_allowed": not failures,
        "plan_gate": plan_gate,
        "sheet_receipt": receipt.get("receipt_path"),
        "ai_review_status": review.get("status"),
        "fight_mode": plan_gate.get("fight_mode"),
        "failures": failures,
        "rollback": "Keep generated source keyframes and prior candidates; regenerate only the failed storyboard sheet or failed review item.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if args.receipt and args.review:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        receipt["receipt_path"] = str(args.receipt)
        review = json.loads(args.review.read_text(encoding="utf-8"))
        result = finalize(plan, receipt, review)
    else:
        result = validate_plan(plan)
        result["video_generation_allowed"] = False
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
