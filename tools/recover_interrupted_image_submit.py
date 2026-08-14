#!/usr/bin/env python3
"""Recover a partial image submit report from durable per-task receipts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def recover(manifest_path: Path, receipt_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = manifest.get("tasks") or []
    task_by_key = {task["task_key"]: task for task in tasks}
    results: list[dict[str, Any]] = []
    for receipt in sorted(receipt_dir.glob("*_submit_receipt.json")):
        task_key = receipt.name.removesuffix("_submit_receipt.json")
        if task_key not in task_by_key:
            raise ValueError(f"receipt does not belong to manifest: {receipt}")
        response = json.loads(receipt.read_text(encoding="utf-8"))
        task_id = (response.get("data") or {}).get("task_id")
        if not task_id:
            raise ValueError(f"receipt has no task_id: {receipt}")
        task = task_by_key[task_key]
        results.append({
            "task_key": task_key,
            "beat_id": task.get("beat_id"),
            "task_id": str(task_id),
            "status": "submitted",
            "receipt": str(receipt.relative_to(ROOT)),
        })
    submitted_keys = {row["task_key"] for row in results}
    unknown = [
        {
            "task_key": task["task_key"],
            "status": "submission_unknown_no_receipt",
            "credit": "UNKNOWN",
            "credit_status": "UNKNOWN_NO_TASK_ID_DO_NOT_RESUBMIT",
        }
        for task in tasks
        if task["task_key"] not in submitted_keys
    ]
    return {
        "schema": "qingshan.giggle_image_batch_submit_recovery.v1",
        "episode": manifest.get("episode"),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "status": "INTERRUPTED_PARTIAL_RECEIPTS_RECOVERED",
        "submitted": len(results),
        "submission_unknown": len(unknown),
        "failed": 0,
        "results": results,
        "unknown": unknown,
        "credit_reconciliation": None,
        "resubmission_policy": (
            "Do not resubmit unknown rows until the isolated credit window and "
            "remote completion evidence prove that no task was accepted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    manifest_path = resolve(args.manifest)
    receipt_dir = resolve(args.receipt_dir)
    report = recover(manifest_path, receipt_dir)
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "submitted": report["submitted"],
        "submission_unknown": report["submission_unknown"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
