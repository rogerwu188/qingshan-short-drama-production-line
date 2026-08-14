#!/usr/bin/env python3
"""Resume and submit the approved E28 V3 multi-reference video batch once."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from episode_video_generation_guard import (
    credit_report_path,
    evaluate_episode_credit_gate,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from giggle_api_client import _get, generate_omni_video
from giggle_credit_statements import reconcile_rows
from submit_giggle_task_manifest import ensure_giggle_api_key
from upload_giggle_asset import upload as upload_asset


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONFIG_SHA = "06008fd69744c51badde1580d895b46f8eaa107280b79fd0e40cfe9e2f45a674"
EXPECTED_GATE_SHA = "652e927211811d1b8576c6732e1d2dc2e8814b669706ca2bb4c949bda243cc24"
RECOVERED_TASKS = {
    "E28-CW-U08": {
        "task_id": "3660972c-a2e5-4993-bdd5-c75f3970e066",
        "actual_charged_credits": 260,
        "statement_created_at": "2026-07-22 00:32:31",
    },
    "E28-CW-U10": {
        "task_id": "3c222053-47a2-4576-9220-01420d5f0eb3",
        "actual_charged_credits": 280,
        "statement_created_at": "2026-07-22 00:32:07",
    },
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(value: str | Path) -> dict:
    return json.loads(resolve(value).read_text(encoding="utf-8"))


def register_audio(path_value: str) -> tuple[str, dict]:
    path = resolve(path_value)
    response = upload_asset(path, True)
    data = response.get("data") or response
    asset_id = data.get("asset_id")
    if not asset_id:
        raise RuntimeError(f"audio asset_id missing for {path}")
    return path_value, {
        "path": path_value,
        "sha256": sha256(path),
        "asset_id": str(asset_id),
        "credit_scope": "NOT_APPLICABLE_ASSET_REGISTRATION",
    }


def submit_task(task: dict, audio_registry: dict[str, dict], receipt_dir: Path) -> dict:
    enriched = dict(task)
    enriched["duration"] = int(task["duration_seconds"])
    enriched["resolved_reference_audio_asset_ids"] = [
        audio_registry[path]["asset_id"] for path in task.get("reference_audios", [])
    ]
    enriched["generation_fingerprint"] = generation_fingerprint(enriched)
    existing = find_existing_paid_candidate("E28", enriched)
    if existing:
        return {
            "task_key": task["task_key"],
            "unit_id": task["unit_id"],
            "state": "tool_blocked",
            "block_code": "BLOCK_UNCHANGED_VIDEO_REGENERATION",
            "existing_candidate": existing,
            "generation_fingerprint": enriched["generation_fingerprint"],
        }
    args = SimpleNamespace(
        prompt="",
        prompt_file=str(resolve(task["prompt_file"])),
        model=task["model"],
        duration=int(task["duration_seconds"]),
        aspect_ratio=task["aspect_ratio"],
        resolution=task["resolution"],
        count=1,
        reference_image=[str(resolve(path)) for path in task["reference_images"]],
        audio=None,
        audio_asset_id=enriched["resolved_reference_audio_asset_ids"],
        video=None,
        video_asset_id=None,
    )
    response = generate_omni_video(args)
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    receipt_path = receipt_dir / f"{task['task_key']}_submit_response.json"
    receipt_path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not task_id:
        raise RuntimeError(f"{task['task_key']} response missing task_id")
    return {
        **enriched,
        "task_id": str(task_id),
        "state": "remote_running",
        "remote_status": "submitted",
        "submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "submit_response": str(receipt_path),
        "credit_attempts": [{
            "attempt": 1,
            "task_id": str(task_id),
            "success": None,
            "charge_status": "PENDING_REMOTE_RESULT",
            "actual_charged_credits": None,
            "generation_fingerprint": enriched["generation_fingerprint"],
        }],
    }


def fetch_recent_pay_statements() -> list[dict]:
    def fetch(page: int) -> list[dict]:
        response = _get(
            "/api/v1/payment/credit-statements",
            {"credit_type": "Pay", "page": page, "page_size": 10, "project_id": ""},
        )
        if response.get("code") != 200:
            raise RuntimeError(f"credit statement page {page} failed")
        return list((response.get("data") or {}).get("list") or [])

    with ThreadPoolExecutor(max_workers=3) as pool:
        return [row for page in pool.map(fetch, (1, 2, 3, 4, 5)) for row in page]


def attach_exact_statement_credits(tasks: list[dict], rows: list[dict]) -> dict:
    statements = {
        str(row.get("project_id")): row
        for row in rows
        if row.get("event_description") == "SingleGenerateVideo"
        and row.get("model") == "seedance-2.0-pro"
        and row.get("project_id")
    }
    missing = []
    for task in tasks:
        statement = statements.get(str(task["task_id"]))
        if not statement:
            missing.append(task["task_id"])
            continue
        credit = abs(int(statement["credit"]))
        task["credit_attempts"][0].update({
            "returned_credit": credit,
            "credit_response_path": "/api/v1/payment/credit-statements",
            "charge_status": "EXACT_TASK_ID_STATEMENT_MATCH",
            "actual_charged_credits": credit,
            "statement_created_at": statement.get("created_at"),
            "statement_project_id": statement.get("project_id"),
            "evidence": "credit_statement_project_id_equals_task_id",
        })
    return {
        "status": "PASS" if not missing else "INCOMPLETE",
        "missing_task_ids": missing,
        "exact_task_count": len(tasks) - len(missing),
    }


def enforce_standard_video_credit_gate() -> dict:
    gate = evaluate_episode_credit_gate("E28")
    report_path = credit_report_path("E28")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if gate.get("status") != "PASS":
        raise RuntimeError(
            "E28 standard video credit gate blocked: "
            f"status={gate.get('status')} "
            f"actual={gate.get('actual_charged_credits_known_total')} "
            f"effective_limit={gate.get('effective_limit_credits')} "
            f"approval_valid={(gate.get('approval') or {}).get('valid')}"
        )
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--prompt-gate", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    config_path = resolve(args.config)
    gate_path = resolve(args.prompt_gate)
    approval_path = resolve(args.approval)
    receipt_path = resolve(args.receipt)
    if sha256(config_path) != EXPECTED_CONFIG_SHA:
        raise RuntimeError("V3 config SHA mismatch")
    if sha256(gate_path) != EXPECTED_GATE_SHA or load(gate_path).get("status") != "PASS":
        raise RuntimeError("V3 prompt gate is not the accepted PASS artifact")
    approval = load(approval_path)
    if approval.get("status") != "EXEMPTED_BY_ROGER_FOR_THIS_EPISODE" or approval.get("approved_batch_config_sha256") != EXPECTED_CONFIG_SHA:
        raise RuntimeError("Roger E28 exact-batch exemption is missing")
    enforce_standard_video_credit_gate()
    if ensure_giggle_api_key() in {"MISSING", "UNSAFE_FILE_PERMISSIONS"}:
        raise RuntimeError("Giggle API key unavailable")

    config = load(config_path)
    tasks = list(config.get("tasks") or [])
    if len(tasks) != 13 or sum(len(task.get("reference_images") or []) for task in tasks) != 38:
        raise RuntimeError("expected 13 tasks and 38 ordered image references")
    if any(len(task.get("reference_images") or []) > 9 for task in tasks):
        raise RuntimeError("Giggle reference-image limit exceeded")
    for task in tasks:
        prompt_path = resolve(task["prompt_file"])
        if sha256(prompt_path) != task["prompt_sha256"]:
            raise RuntimeError(f"prompt SHA mismatch: {task['task_key']}")
        for ref in task["reference_image_sequence"]:
            path = resolve(ref["path"])
            if ref.get("qa_decision") == "CONDITIONAL_MACHINE_ADMISSION" or sha256(path) != ref["sha256"]:
                raise RuntimeError(f"reference admission/SHA failure: {task['task_key']} {ref['state_id']}")

    audio_paths = sorted({path for task in tasks for path in task.get("reference_audios", [])})
    audio_registry: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(audio_paths))) as pool:
        futures = [pool.submit(register_audio, path) for path in audio_paths]
        for future in as_completed(futures):
            path, row = future.result()
            audio_registry[path] = row

    receipt_dir = receipt_path.parent / f"{receipt_path.stem}_responses"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    submitted: list[dict] = []
    failures: list[dict] = []
    recovered: list[dict] = []
    pending_tasks = []
    for task in tasks:
        prior = RECOVERED_TASKS.get(task["unit_id"])
        if not prior:
            pending_tasks.append(task)
            continue
        recovered.append({
            **task,
            "task_id": prior["task_id"],
            "state": "remote_completed_recovered_not_resubmitted",
            "remote_status": "completed",
            "submission_action": "REUSED_ACCEPTED_V2_TASK",
            "credit_attempts": [{
                "attempt": 1,
                "task_id": prior["task_id"],
                "success": True,
                "charge_status": "EXACT_TASK_ID_STATEMENT_MATCH",
                "actual_charged_credits": prior["actual_charged_credits"],
                "statement_created_at": prior["statement_created_at"],
                "statement_project_id": prior["task_id"],
                "evidence": "credit_statement_project_id_equals_task_id",
            }],
        })
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(submit_task, task, audio_registry, receipt_dir): task for task in pending_tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                row = future.result()
                if row.get("task_id"):
                    submitted.append(row)
                else:
                    failures.append(row)
            except BaseException as exc:
                failures.append({
                    "task_key": task["task_key"],
                    "unit_id": task["unit_id"],
                    "state": "submit_failed_terminal_no_orchestration_retry",
                    "error": str(exc),
                    "credit": 0,
                })
    submitted.sort(key=lambda row: row["task_key"])
    failures.sort(key=lambda row: row["task_key"])
    finished = datetime.now(timezone.utc)

    statement_rows: list[dict] = []
    assignment = {"status": "PASS", "missing_task_ids": [], "exact_task_count": 0}
    if submitted:
        for attempt in range(7):
            try:
                statement_rows = fetch_recent_pay_statements()
                assignment = attach_exact_statement_credits(submitted, statement_rows)
            except BaseException as exc:
                assignment = {"status": "INCOMPLETE", "error": str(exc), "missing_task_ids": [row["task_id"] for row in submitted]}
            if assignment.get("status") == "PASS" or attempt == 6:
                break
            time.sleep(5)
    all_tasks = sorted(recovered + submitted, key=lambda row: row["unit_id"])
    exact_credits = [
        attempt.get("actual_charged_credits")
        for task in all_tasks
        for attempt in task.get("credit_attempts", [])[:1]
    ]
    known_total = sum(exact_credits) if len(exact_credits) == len(all_tasks) and all(value is not None for value in exact_credits) else None
    receipt = {
        "schema": "qingshan.e28.cl2x517.video_batch_v3_resume_submit.v1",
        "episode": "E28",
        "status": "REMOTE_RUNNING_OR_COMPLETED" if len(all_tasks) == 13 and not failures else "SUBMITTED_WITH_ISOLATED_FAILURES",
        "config": str(config_path),
        "config_sha256": sha256(config_path),
        "prompt_gate": str(gate_path),
        "prompt_gate_sha256": sha256(gate_path),
        "approval": str(approval_path),
        "approval_sha256": sha256(approval_path),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "submitted_at": finished.isoformat().replace("+00:00", "Z"),
        "parallel_submission": True,
        "requested_count": 13,
        "recovered_not_resubmitted_count": len(recovered),
        "newly_submitted_count": len(submitted),
        "submitted_count": len(all_tasks),
        "failed_count": len(failures),
        "active_task_count": len([task for task in all_tasks if task.get("remote_status") != "completed"]),
        "active_task_ids": [task["task_id"] for task in all_tasks if task.get("remote_status") != "completed"],
        "all_task_ids": [task["task_id"] for task in all_tasks],
        "audio_asset_registry": audio_registry,
        "tasks": all_tasks,
        "failures": failures,
        "prior_v2_attempt_audit": {
            "accepted_and_reused_units": ["E28-CW-U08", "E28-CW-U10"],
            "explicit_validation_failure_zero_charge_units": ["E28-CW-U02", "E28-CW-U06", "E28-CW-U07"],
            "timeout_without_task_id_or_credit_statement_units": [
                "E28-CW-U01", "E28-CW-U03", "E28-CW-U04", "E28-CW-U05",
                "E28-CW-U09", "E28-CW-U11", "E28-CW-U12", "E28-CW-U13",
            ],
            "resubmission_rule": "Only U08/U10 count as accepted. They are never resubmitted. Every remaining unit is submitted once under V3; no orchestration retry follows a V3 timeout.",
        },
        "credit_statement_rows": [
            row for row in statement_rows
            if str(row.get("project_id")) in {task["task_id"] for task in submitted}
        ],
        "credit_assignment": assignment,
        "credit_summary": {
            "actual_charged_credits_known_total": known_total,
            "actual_total_complete": known_total is not None,
            "failed_zero_charge_count": len([row for row in failures if row.get("credit") == 0]),
            "policy": "Giggle credit-statements is authoritative; no missing value is estimated.",
        },
        "retry_policy": "NO_AUTOMATIC_RETRY; failed-only requires changed generation input and a new approval/gate pass.",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "submitted": len(submitted),
        "failed": len(failures),
        "credit": known_total,
        "receipt": str(receipt_path),
    }, ensure_ascii=False))
    return 0 if len(all_tasks) == 13 and not failures and known_total is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
