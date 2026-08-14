#!/usr/bin/env python3
"""Build a receipt-backed, non-speculative Giggle credit ledger for an episode."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_stage(root: Path, stage: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for submit_path in sorted((root / stage).glob("*/submit_response.json")):
        task_dir = submit_path.parent
        submit = read_json(submit_path)
        query_path = task_dir / "last_query_response.json"
        query = read_json(query_path) if query_path.exists() else {}
        submit_data = submit.get("data") or {}
        query_data = query.get("data") or {}
        asset_info = query_data.get("asset_info") or []
        if stage == "static":
            local_files = sorted(
                p for pattern in ("*.jpg", "*.jpeg", "*.png") for p in task_dir.glob(pattern)
            )
        else:
            local_files = sorted(task_dir.glob("result_*.mp4"))
        rows.append(
            {
                "dir": str(task_dir),
                "uuid": submit.get("uuid"),
                "task_id": submit_data.get("task_id") or query_data.get("task_id"),
                "submit_code": submit.get("code"),
                "submit_message": submit.get("msg"),
                "status": query_data.get("status", "query_receipt_missing"),
                "error": query_data.get("err_msg", ""),
                "local_result_files": len(local_files),
                "asset_count": len(asset_info),
                "asset_duration_seconds": round(
                    sum(float(asset.get("duration") or 0) for asset in asset_info), 3
                ),
            }
        )
    return rows


def collect_ui_fallback(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for receipt_path in sorted((root / "ui_fallback").glob("*/submit_receipt.json")):
        receipt = read_json(receipt_path)
        media_type = receipt.get("media_type", "image")
        pattern = "candidate_*.jpg" if media_type == "image" else "result_*.mp4"
        rows.append(
            {
                "dir": str(receipt_path.parent),
                "shot_id": receipt.get("shot_id"),
                "channel": receipt.get("channel"),
                "media_type": media_type,
                "model": receipt.get("model"),
                "status": receipt.get("status", "unknown"),
                "local_result_files": len(list(receipt_path.parent.glob(pattern))),
                "observed_interval_delta": receipt.get("observed_interval_delta"),
                "credit_attribution": receipt.get("credit_attribution"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--assets-root", required=True, type=Path)
    parser.add_argument("--pending-b-plan", type=Path)
    parser.add_argument("--pending-repair-plan", type=Path)
    parser.add_argument("--account-balance", type=int)
    parser.add_argument("--account-balance-observed-at")
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--md-out", required=True, type=Path)
    args = parser.parse_args()

    static_tasks = collect_stage(args.assets_root, "static")
    video_tasks = collect_stage(args.assets_root, "videos")
    ui_fallback_tasks = collect_ui_fallback(args.assets_root)
    b_plan = read_json(args.pending_b_plan) if args.pending_b_plan else {}
    repair_plan = read_json(args.pending_repair_plan) if args.pending_repair_plan else {}
    pending_b = len(b_plan.get("clips") or [])
    pending_repairs = sum(
        1
        for job in repair_plan.get("jobs") or []
        if str(job.get("status", "PENDING_GENERATION")).startswith("PENDING")
    )

    all_tasks = static_tasks + video_tasks
    ui_image_tasks = [row for row in ui_fallback_tasks if row["media_type"] == "image"]
    ui_video_tasks = [row for row in ui_fallback_tasks if row["media_type"] == "video"]
    status_counts = Counter(row["status"] for row in all_tasks)
    ui_status_counts = Counter(row["status"] for row in ui_fallback_tasks)
    report = {
        "schema": "qingshan.giggle_credit_ledger.v1",
        "episode": args.episode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "LIVE_NOT_FINAL",
        "assets_root": str(args.assets_root.resolve()),
        "submitted_task_count": len(all_tasks) + len(ui_fallback_tasks),
        "image_task_count": len(static_tasks) + len(ui_image_tasks),
        "image_local_candidate_file_count": sum(row["local_result_files"] for row in static_tasks + ui_image_tasks),
        "video_task_count": len(video_tasks) + len(ui_video_tasks),
        "video_local_result_file_count": sum(row["local_result_files"] for row in video_tasks + ui_video_tasks),
        "video_receipt_duration_seconds": round(
            sum(row["asset_duration_seconds"] for row in video_tasks), 3
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "ui_fallback_status_counts": dict(sorted(ui_status_counts.items())),
        "pending_remote_running_task_count": status_counts.get("running", 0),
        "planned_not_submitted": {
            "b_coverage_source_count": pending_b,
            "targeted_repair_job_count": pending_repairs,
            "total": pending_b + pending_repairs,
        },
        "giggle_credit_fields_available_in_api_receipts": False,
        "actual_credits_total": "PENDING_ACCOUNT_RECONCILIATION",
        "account_balance_snapshot": (
            {
                "credits": args.account_balance,
                "observed_at": args.account_balance_observed_at,
                "source": "authenticated Giggle web account balance",
                "use": "baseline for future verified deltas; not a retroactive episode total",
            }
            if args.account_balance is not None
            else None
        ),
        "credit_note": (
            "Submit/query receipts do not expose per-task credit fields. Reconcile from the "
            "Giggle account bill or a verified balance delta; do not estimate from task counts."
        ),
        "static_tasks": static_tasks,
        "video_tasks": video_tasks,
        "ui_fallback_tasks": ui_fallback_tasks,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = [row for row in all_tasks if row["status"] == "failed"]
    running = [row for row in all_tasks if row["status"] == "running"]
    lines = [
        f"# {args.episode} Giggle Credit Live Ledger",
        "",
        "- Status: `LIVE_NOT_FINAL`",
        f"- Submitted tasks: `{len(all_tasks) + len(ui_fallback_tasks)}` (`{len(static_tasks) + len(ui_image_tasks)}` image + `{len(video_tasks) + len(ui_video_tasks)}` video)",
        f"- Local image candidate files: `{report['image_local_candidate_file_count']}`",
        f"- Local video result files: `{report['video_local_result_file_count']}`",
        f"- Video duration reported by receipts: `{report['video_receipt_duration_seconds']:.3f}s`",
        f"- Receipt statuses: `{json.dumps(report['status_counts'], ensure_ascii=False)}`",
        f"- Planned but not submitted: `{pending_b + pending_repairs}` (`{pending_b}` B coverage + `{pending_repairs}` targeted repairs)",
        "- Actual Giggle credits total: `PENDING_ACCOUNT_RECONCILIATION`",
        "- Rule: do not infer credits from task count; use the Giggle bill or verified balance delta.",
        "",
        "## Failed Tasks",
        "",
    ]
    if args.account_balance is not None:
        lines.insert(
            11,
            f"- Authenticated account balance snapshot: `{args.account_balance}` at `{args.account_balance_observed_at}`; baseline only, not retroactive E16 spend.",
        )
    lines.extend(
        f"- `{row['dir']}` task_id=`{row['task_id']}` error=`{row['error']}`" for row in failed
    )
    lines.extend(["", "## Running Tasks", ""])
    lines.extend(f"- `{row['dir']}` task_id=`{row['task_id']}`" for row in running)
    args.md_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
