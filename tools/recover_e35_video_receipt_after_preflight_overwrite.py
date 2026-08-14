#!/usr/bin/env python3
"""Recover E35 terminal task evidence after a destructive preflight overwrite."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from giggle_api_client import _get
from giggle_credit_statements import STATEMENT_PATH


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
BASE_CONFIG = PROD / "video_performance_v1/E35_VIDEO_STREAMING_PERFORMANCE_V1.json"
REPAIR1_CONFIG = PROD / "video_performance_v1/E35_VIDEO_STREAMING_PERFORMANCE_V1_U01_REPAIR1.json"
SPLIT_CONFIG = PROD / "video_performance_v1/E35_VIDEO_STREAMING_PERFORMANCE_V1_U01_SPLIT_REPAIR2.json"
OUTPUT_DIR = PROD / "video_performance_v1/outputs"
QA_DIR = ROOT / "qa/e35_v1_streaming_video_compile_20260723/video_runtime"
RECEIPT = ROOT / "workflow/tasks/E35_V1_VIDEO_STREAMING_RECEIPT_R2_20260723.json"
CORRUPTED = ROOT / "workflow/tasks/E35_V1_VIDEO_STREAMING_RECEIPT_R2_PREFLIGHT_OVERWRITE_CORRUPTED_20260723.json"
ORIGINAL_U01_TASK_ID = "526ed36c-04ac-43b9-b3e8-ca3f86e50006"
REPAIR1_U01_TASK_ID = "232ab784-3174-48ee-b08a-1d78a128011f"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_id_from_output(path: Path) -> str:
    match = re.search(r"_([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.mp4$", path.name)
    if not match:
        raise SystemExit(f"cannot recover task id from {path}")
    return match.group(1)


def credit_attempt(task_id: str, success: bool, fingerprint: str, statement_rows: list[dict]) -> tuple[dict, int]:
    rows = [
        row for row in statement_rows
        if str(row.get("project_id") or "") == task_id
        and row.get("event_description") == "SingleGenerateVideo"
        and row.get("event_type") in {"Pay", "Refund"}
    ]
    paid = sum((abs(Decimal(str(row["credit"]))) for row in rows if row["event_type"] == "Pay"), Decimal("0"))
    refunded = sum((abs(Decimal(str(row["credit"]))) for row in rows if row["event_type"] == "Refund"), Decimal("0"))
    net = paid - refunded
    statement = {
        "status": "PASS_ZERO_REFUNDED" if paid > 0 and net == 0 else "PASS_CHARGED" if paid > 0 and net > 0 else "INCOMPLETE",
        "endpoint": STATEMENT_PATH,
        "method": "SINGLE_RECENT_LEDGER_FETCH_FILTERED_BY_EXACT_PROJECT_ID",
        "task_id": task_id,
        "event_description": "SingleGenerateVideo",
        "paid_credits": int(paid),
        "refunded_credits": int(refunded),
        "net_charged_credits": int(net),
        "matched_count": len(rows),
        "invalid_credit_rows": 0,
        "statement_rows": rows,
    }
    expected = "PASS_CHARGED" if success else "PASS_ZERO_REFUNDED"
    if statement.get("status") != expected:
        raise SystemExit(f"{task_id}: credit statement {statement.get('status')} != {expected}")
    net = int(statement["net_charged_credits"])
    return ({
        "attempt": 1,
        "task_id": task_id,
        "tool_type": "video_generation",
        "returned_credit": net if success else None,
        "credit_response_path": "/api/v1/payment/credit-statements",
        "charge_status": "EXACT_TASK_ID_STATEMENT_MATCH" if success else "FAILED_ZERO_NET_AFTER_REFUND",
        "actual_charged_credits": net,
        "success": success,
        "evidence": "credit_statement_project_id_equals_task_id" if success else "credit_statement_pay_minus_refund",
        "generation_fingerprint": fingerprint,
        "credit_statement_reconciliation": statement,
        "settled_at": datetime.now(timezone.utc).isoformat(),
    }, net)


def main() -> int:
    if RECEIPT.is_file():
        shutil.copy2(RECEIPT, CORRUPTED)
    base = load(BASE_CONFIG)
    repair1 = load(REPAIR1_CONFIG)
    statement_response = _get(STATEMENT_PATH, {"page": 1, "page_size": 100, "project_id": ""})
    if statement_response.get("code") != 200:
        raise SystemExit(f"credit statement fetch failed: {statement_response}")
    statement_rows = (statement_response.get("data") or {}).get("list") or []
    tasks = []
    known_total = 0
    for template in base["tasks"]:
        if template["unit_id"] == "E35-CW-U01":
            continue
        matches = sorted(OUTPUT_DIR.glob(f"E35_{template['task_key']}_*.mp4"))
        if len(matches) != 1:
            raise SystemExit(f"{template['task_key']}: expected one output, found {len(matches)}")
        output = matches[0]
        task_id = task_id_from_output(output)
        ocr_path = QA_DIR / f"{template['task_key']}_ocr.json"
        cadence_path = QA_DIR / f"{template['task_key']}_frame_cadence.json"
        if not ocr_path.is_file() or not cadence_path.is_file():
            raise SystemExit(f"{template['task_key']}: missing runtime QA")
        ocr = load(ocr_path)
        cadence = load(cadence_path)
        if cadence.get("status") != "PASS":
            raise SystemExit(f"{template['task_key']}: cadence is not PASS")
        state = "qa_pass" if ocr.get("status") == "PASS" else "qa_failed_terminal"
        row = copy.deepcopy(template)
        row.update({
            "task_id": task_id,
            "remote_status": "completed",
            "state": state,
            "status": state,
            "output_path": str(output),
            "sha256": sha(output),
            "size_bytes": output.stat().st_size,
            "qa_evidence": {"frame_cadence": str(cadence_path), "ocr": str(ocr_path)},
            "failure_evidence": [] if state == "qa_pass" else [{"check": "full_motion_ocr", "returncode": 1}],
            "recovered_from_local_output": True,
        })
        attempt, charged = credit_attempt(task_id, True, row["generation_fingerprint"], statement_rows)
        row["credit_attempts"] = [attempt]
        known_total += charged
        tasks.append(row)

    for config, task_id, label in (
        (base, ORIGINAL_U01_TASK_ID, "ORIGINAL_9_SECOND_FAILURE"),
        (repair1, REPAIR1_U01_TASK_ID, "REPAIR1_13_SECOND_FAILURE"),
    ):
        template = copy.deepcopy(next(row for row in config["tasks"] if row["unit_id"] == "E35-CW-U01"))
        if label.startswith("REPAIR1"):
            template["task_key"] = "E35-CW-U01-PERFORMANCE-V1-REPAIR1"
        template.update({
            "task_id": task_id,
            "remote_status": "failed",
            "state": "remote_failed_terminal",
            "status": "remote_failed_terminal",
            "failure_reason": "failed",
            "recovery_label": label,
            "recovered_from_credit_statement": True,
        })
        attempt, charged = credit_attempt(task_id, False, template["generation_fingerprint"], statement_rows)
        template["credit_attempts"] = [attempt]
        known_total += charged
        tasks.append(template)

    tasks.sort(key=lambda row: (row["unit_id"], row["task_key"]))
    payload = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E35",
        "status": "BATCH_COMPLETE_WITH_ISOLATED_FAILURES",
        "config": str(SPLIT_CONFIG),
        "output_dir": str(OUTPUT_DIR.relative_to(ROOT)),
        "qa_dir": str(QA_DIR.relative_to(ROOT)),
        "local_pid": None,
        "active_task_ids": [],
        "max_retries": 0,
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "supported_tool_types": ["agentcut", "ai_review", "image_generation", "video_generation"],
        "actual_charged_credits_known_total": known_total,
        "actual_total_complete": True,
        "recovery": {
            "status": "PASS",
            "reason": "Preflight block overwrote the receipt before atomic_blocked_receipt was introduced.",
            "corrupted_receipt": str(CORRUPTED),
            "source_evidence": ["local MP4 SHA-256", "runtime cadence/OCR reports", "exact task-id credit statements"],
            "recovered_terminal_task_count": len(tasks),
        },
        "tasks": tasks,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "recovered_tasks": len(tasks),
        "qa_pass": sum(row["state"] == "qa_pass" for row in tasks),
        "qa_failed_terminal": sum(row["state"] == "qa_failed_terminal" for row in tasks),
        "remote_failed_terminal": sum(row["state"] == "remote_failed_terminal" for row in tasks),
        "known_video_credits": known_total,
        "receipt": str(RECEIPT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
