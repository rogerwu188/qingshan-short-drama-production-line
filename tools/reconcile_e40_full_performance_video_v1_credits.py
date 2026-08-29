#!/usr/bin/env python3
"""Persist exact V1 video Pay/Refund and terminalize only bound failures."""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

try:
    from giggle_credit_statements import fetch_task_credit_net_by_task_id
except ModuleNotFoundError:
    from tools.giggle_credit_statements import fetch_task_credit_net_by_task_id


ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_HARVEST_LATEST.json"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_V1_CREDIT_CLASSIFICATION.json"


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    harvest = json.loads(HARVEST.read_text(encoding="utf-8"))
    bound = [row for row in harvest["results"] if row.get("task_id")]
    results = []
    with ThreadPoolExecutor(max_workers=len(bound)) as pool:
        futures = {
            pool.submit(
                fetch_task_credit_net_by_task_id,
                row["task_id"],
                event_description="SingleGenerateVideo",
            ): row
            for row in bound
        }
        for future in as_completed(futures):
            source = futures[future]
            credit = future.result()
            results.append({
                "task_key": source["task_key"],
                "task_id": source["task_id"],
                "provider_status": source["status"],
                "provider_error": ((source.get("terminal_error") or {}).get("data") or {}).get("err_msg"),
                "transaction": source["transaction"],
                "credit": credit,
            })
            if source["status"] == "failed" and credit.get("status") == "PASS_ZERO_REFUNDED":
                transaction = ROOT / source["transaction"]
                row = json.loads(transaction.read_text(encoding="utf-8"))
                row.update({
                    "state": "TERMINAL_FAILED_REFUNDED",
                    "provider_status": "failed",
                    "provider_error": ((source.get("terminal_error") or {}).get("data") or {}).get("err_msg"),
                    "credit_status": "PASS_ZERO_REFUNDED",
                    "paid_credits": credit["paid_credits"],
                    "refunded_credits": credit["refunded_credits"],
                    "net_charged_credits": 0,
                    "terminalized_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "retry_guard": "RETRY_REQUIRES_MATERIAL_TRANSPORT_CHANGE_AND_NEW_TRANSACTION",
                })
                atomic_json(transaction, row)
    results.sort(key=lambda row: row["task_key"])
    ambiguous = [row for row in harvest["results"] if not row.get("task_id")]
    payload = {
        "schema": "qingshan.e40.full_performance_video_v1_credit_classification.v1",
        "episode": "E40",
        "status": "BOUND_TASKS_CLASSIFIED_RESPONSE_LOST_ISOLATED",
        "source_harvest": str(HARVEST.relative_to(ROOT)),
        "source_harvest_sha256": sha(HARVEST),
        "bound_count": len(results),
        "bound_zero_refunded_count": sum(row["credit"].get("status") == "PASS_ZERO_REFUNDED" for row in results),
        "results": results,
        "ambiguous_response_lost": [{
            "task_key": row["task_key"],
            "transaction": row["transaction"],
            "state": row["status"],
            "repost_forbidden": True,
        } for row in ambiguous],
    }
    atomic_json(OUT, payload)
    print(json.dumps({"status": payload["status"], "bound": len(results), "zero_refunded": payload["bound_zero_refunded_count"], "ambiguous": len(ambiguous), "out_sha256": sha(OUT)}, ensure_ascii=False))
    return 0 if payload["bound_zero_refunded_count"] == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
