#!/usr/bin/env python3
"""Reconcile an interrupted E37 provider submit before retrying missing segments."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint
from giggle_api_client import _get
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_MANIFEST_V4.json"
RESPONSES = ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_SUBMIT_V4_20260803_responses"
RECEIPT = ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_SUBMIT_V4_20260803.json"
PENDING = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_PENDING9_MANIFEST_V4.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    ensure_giggle_api_key()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tasks_by_key = {task["task_key"]: task for task in manifest["tasks"]}
    confirmed = []
    for response_path in sorted(RESPONSES.glob("*_submit_response.json")):
        task_key = response_path.name.removesuffix("_submit_response.json")
        response = json.loads(response_path.read_text(encoding="utf-8"))
        task_id = str((response.get("data") or {}).get("task_id") or response.get("task_id") or "")
        if not task_id or task_key not in tasks_by_key:
            continue
        source = tasks_by_key[task_key]
        enriched = {
            **source,
            "tool_type": "video_generation",
            "workflow_credit_scope": manifest["workflow_credit_scope"],
            "model": manifest["model"],
            "aspect_ratio": manifest["aspect_ratio"],
            "resolution": manifest["resolution"],
        }
        enriched.update({
            "generation_fingerprint": generation_fingerprint(enriched),
            "task_id": task_id,
            "state": "remote_running",
            "remote_status": "submitted",
            "submitted_at": utc_now(),
            "submit_response": rel(response_path),
            "credit_attempts": [{
                "attempt": 1,
                "task_id": task_id,
                "success": None,
                "charge_status": "PENDING_REMOTE_RESULT",
                "actual_charged_credits": None,
                "generation_fingerprint": generation_fingerprint(enriched),
            }],
        })
        confirmed.append(enriched)

    statement_response = _get(
        "/api/v1/payment/credit-statements",
        {"credit_type": "Pay", "page": 1, "page_size": 100},
    )
    rows = (statement_response.get("data") or {}).get("list") or []
    confirmed_ids = {task["task_id"] for task in confirmed}
    confirmed_rows = [
        row for row in rows
        if str(row.get("project_id") or "") in confirmed_ids
        and row.get("event_description") == "SingleGenerateVideo"
    ]
    pending_tasks = [task for task in manifest["tasks"] if task["task_key"] not in {row["task_key"] for row in confirmed}]

    receipt = {
        "schema": "qingshan.e37.ambiguous_submit_reconciliation.v1",
        "episode": "E37",
        "recorded_at": utc_now(),
        "status": "PARTIAL_SUBMIT_AMBIGUITY_RECONCILED_NO_DUPLICATE_REPLAY",
        "manifest": rel(MANIFEST),
        "manifest_sha256": sha256(MANIFEST),
        "failure": "CLIENT_WRITE_TIMEOUT_DURING_TEN_WAY_POST",
        "reconciliation": {
            "confirmed_task_count": len(confirmed),
            "confirmed_task_ids": sorted(confirmed_ids),
            "exact_pay_rows": confirmed_rows,
            "unconfirmed_task_count": len(pending_tasks),
            "rule": "Only tasks with neither returned task_id nor exact post-window pay row may be resubmitted.",
        },
        "submitted": len(confirmed),
        "total": len(manifest["tasks"]),
        "tasks": confirmed,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pending = {
        **manifest,
        "schema": "qingshan.e37.remaining_u03_u07.pfm_v2_overhead_reveal_pending_manifest.v4",
        "recorded_at": utc_now(),
        "status": "PASS_READY_FOR_FAILED_TRANSPORT_ONLY_RESUBMISSION",
        "retry_of": rel(RECEIPT),
        "retry_policy": "TRANSPORT_UNCONFIRMED_ONLY; EXCLUDES_CONFIRMED_TASK_IDS; NO_UNCHANGED_PAID_DUPLICATE",
        "counts": {
            "tasks": len(pending_tasks),
            "confirmed_excluded": len(confirmed),
            "u03": sum(task["unit_id"] == "U03" for task in pending_tasks),
            "u07": sum(task["unit_id"] == "U07" for task in pending_tasks),
            "canonical_lines": sum(len(task.get("canonical_lines") or []) for task in pending_tasks),
        },
        "tasks": pending_tasks,
    }
    PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "confirmed": len(confirmed),
        "pending": len(pending_tasks),
        "receipt": rel(RECEIPT),
        "pending_manifest": rel(PENDING),
        "pending_manifest_sha256": sha256(PENDING),
    }, ensure_ascii=False))
    return 0 if confirmed and pending_tasks else 2


if __name__ == "__main__":
    raise SystemExit(main())
