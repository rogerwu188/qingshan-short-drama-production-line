#!/usr/bin/env python3
"""Build a receipt-backed Giggle task ledger without estimating credit spend."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect_receipts(
    roots: list[Path],
    task_prefix: str | None = None,
    receipt_roots: list[Path] | None = None,
    receipt_media_type: str = "video",
) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not root.exists():
            continue
        for submit_path in sorted(root.rglob("submit_response.json")):
            task_dir = submit_path.parent
            if task_prefix and not task_dir.name.startswith(task_prefix):
                continue
            submit = read_json(submit_path)
            query = read_json(task_dir / "last_query_response.json")
            submit_data = submit.get("data") or {}
            query_data = query.get("data") or {}
            task_id = submit_data.get("task_id") or query_data.get("task_id")
            key = str(task_id or submit_path.resolve())
            videos = sorted(task_dir.glob("result_*.mp4"))
            images = sorted(
                path
                for pattern in ("*.jpg", "*.jpeg", "*.png")
                for path in task_dir.glob(pattern)
            )
            assets = query_data.get("asset_info") or []
            asset_urls = " ".join(str(row.get("url") or "") for row in assets)
            if videos or ".mp4" in asset_urls:
                media_type = "video"
            elif images or any(ext in asset_urls for ext in (".jpg", ".jpeg", ".png")):
                media_type = "image"
            else:
                media_type = "unknown"
            row = {
                "task_dir": str(task_dir.resolve()),
                "task_id": task_id,
                "submit_uuid": submit.get("uuid"),
                "submit_code": submit.get("code"),
                "status": query_data.get("status") or "query_receipt_missing",
                "media_type": media_type,
                "local_result_file_count": len(videos) + len(images),
                "asset_count": len(assets),
            }
            if key not in by_key or row["local_result_file_count"] > by_key[key]["local_result_file_count"]:
                by_key[key] = row
    for root in receipt_roots or []:
        if not root.exists():
            continue
        for receipt_path in sorted(root.rglob("*submit_receipt.json")):
            receipt = read_json(receipt_path)
            data = receipt.get("data") or {}
            task_id = receipt.get("task_id") or data.get("task_id")
            if not task_id:
                continue
            source_id = receipt.get("source_id") or receipt_path.name.removesuffix(
                "_submit_receipt.json"
            )
            if task_prefix and not str(source_id).startswith(task_prefix):
                continue
            key = str(task_id)
            row = {
                "task_dir": str(receipt_path.parent.resolve()),
                "source_id": source_id,
                "task_id": task_id,
                "submit_uuid": receipt.get("uuid"),
                "submit_code": receipt.get("code", 200),
                "status": receipt.get("remote_status") or receipt.get("submit_status") or "submitted",
                "media_type": receipt_media_type,
                "local_result_file_count": 0,
                "asset_count": 0,
            }
            if key not in by_key:
                by_key[key] = row
    return sorted(by_key.values(), key=lambda row: row["task_dir"])


def build_report(
    episode: str,
    scope: str,
    roots: list[Path],
    task_prefix: str | None = None,
    receipt_roots: list[Path] | None = None,
    receipt_media_type: str = "video",
) -> dict[str, Any]:
    tasks = collect_receipts(
        roots,
        task_prefix,
        receipt_roots,
        receipt_media_type,
    )
    image_tasks = [row for row in tasks if row["media_type"] == "image"]
    video_tasks = [row for row in tasks if row["media_type"] == "video"]
    unknown_tasks = [row for row in tasks if row["media_type"] == "unknown"]
    return {
        "schema": "qingshan.giggle_credit_ledger.v1",
        "episode": episode,
        "scope": scope,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "BACKFILL_TASK_COUNTS_COMPLETE_CREDITS_PENDING",
        "receipt_roots": [str(root.resolve()) for root in roots],
        "external_receipt_roots": [
            str(root.resolve()) for root in (receipt_roots or [])
        ],
        "submitted_task_count": len(tasks),
        "image_task_count": len(image_tasks),
        "video_task_count": len(video_tasks),
        "unknown_media_task_count": len(unknown_tasks),
        "local_result_file_count": sum(row["local_result_file_count"] for row in tasks),
        "giggle_credit_fields_available_in_api_receipts": False,
        "actual_credits_total": "PENDING_ACCOUNT_RECONCILIATION",
        "balance_before": None,
        "balance_after": None,
        "credit_note": "Task counts are receipt-backed. Actual credits must come from the Giggle bill or a verified before/after balance delta; never estimate from task counts.",
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--scope", choices=("ORIGINAL", "REMAKE"), required=True)
    parser.add_argument("--root", action="append", default=[])
    parser.add_argument("--receipt-root", action="append", default=[])
    parser.add_argument(
        "--receipt-media-type",
        choices=("image", "video", "unknown"),
        default="video",
    )
    parser.add_argument("--task-prefix")
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--md-out", required=True)
    args = parser.parse_args()
    report = build_report(
        args.episode,
        args.scope,
        [Path(value) for value in args.root],
        args.task_prefix,
        [Path(value) for value in args.receipt_root],
        args.receipt_media_type,
    )
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_out.write_text(
        "\n".join(
            [
                f"# {args.episode} {args.scope} Giggle Credit Ledger",
                "",
                f"- Status: `{report['status']}`",
                f"- Submitted tasks: `{report['submitted_task_count']}`",
                f"- Image tasks: `{report['image_task_count']}`",
                f"- Video tasks: `{report['video_task_count']}`",
                f"- Unknown-media tasks: `{report['unknown_media_task_count']}`",
                f"- Local result files: `{report['local_result_file_count']}`",
                "- Actual credits: `PENDING_ACCOUNT_RECONCILIATION`",
                "- Credit rule: use the Giggle bill or verified balance delta; do not estimate.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "episode": args.episode,
                "scope": args.scope,
                "submitted_task_count": report["submitted_task_count"],
                "image_task_count": report["image_task_count"],
                "video_task_count": report["video_task_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
