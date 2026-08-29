#!/usr/bin/env python3
"""Submit a SHA-bound character-asset plan concurrently to Giggle."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from giggle_api_client import _request
from giggle_credit_statements import fetch_pay_statements, reconcile_rows


ROOT = Path(__file__).resolve().parents[1]


class DuplicateSubmissionBlocked(RuntimeError):
    """A prior charged or unresolved character-asset intent cannot be repeated."""


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def submission_fingerprint(row: dict, model: str, resolution: str) -> str:
    contract = {
        "character_id": row.get("id"),
        "prompt_sha256": row.get("prompt_sha256"),
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


def transaction_path(transaction_dir: Path, row: dict, model: str, resolution: str) -> Path:
    fingerprint = submission_fingerprint(row, model, resolution)
    return transaction_dir / f"{row['id']}__{fingerprint[:16]}.json"


def prior_submission(row: dict, transaction_dir: Path, model: str, resolution: str) -> dict | None:
    path = transaction_path(transaction_dir, row, model, resolution)
    if not path.is_file():
        return None
    transaction = json.loads(path.read_text(encoding="utf-8"))
    if transaction.get("submission_fingerprint") != submission_fingerprint(row, model, resolution):
        raise DuplicateSubmissionBlocked(f"{row['id']} transaction fingerprint mismatch")
    if transaction.get("state") == "SUBMITTED_TASK_ID_BOUND" and transaction.get("task_id"):
        return {
            "task_key": row["id"], "character_id": row["id"],
            "task_id": transaction["task_id"], "status": "SUBMITTED",
            "receipt": transaction.get("receipt"),
            "transaction": str(path.relative_to(ROOT)), "recovered_from_transaction": True,
        }
    if transaction.get("state") in {
        "INTENT_RECORDED", "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
        "CHARGED_TASK_ID_MISSING", "CHARGE_STATE_UNRESOLVED_BATCH",
    }:
        raise DuplicateSubmissionBlocked(
            f"{row['id']} duplicate submit blocked by {transaction.get('state')}"
        )
    return None


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def resolved_reference_images(row: dict) -> list[Path]:
    values = list(row.get("reference_images") or [])
    expected = list(row.get("reference_image_sha256s") or [])
    if len(values) != len(expected):
        raise ValueError(f"{row['id']} reference image path/SHA count mismatch")
    if len(values) > 9:
        raise ValueError(f"{row['id']} has more than 9 reference images")
    paths = [resolve(str(value)) for value in values]
    for path, wanted in zip(paths, expected):
        if not path.is_file():
            raise ValueError(f"{row['id']} missing reference image: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != str(wanted):
            raise ValueError(f"{row['id']} reference image SHA mismatch: {path}")
    return paths


def submit(row: dict, output_dir: Path, transaction_dir: Path, model: str, resolution: str) -> dict:
    recovered = prior_submission(row, transaction_dir, model, resolution)
    if recovered:
        return recovered
    prompt_path = resolve(row["prompt_file"])
    actual_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if actual_sha != row["prompt_sha256"]:
        raise ValueError(f"{row['id']} prompt SHA mismatch")
    references = resolved_reference_images(row)
    payload = {
        "prompt": prompt_path.read_text(encoding="utf-8"),
        "generate_count": 1,
        "model": model,
        "aspect_ratio": "9:16",
        "resolution": resolution,
        "watermark": False,
    }
    endpoint = "/api/v1/generation/text-to-image"
    if references:
        endpoint = "/api/v1/generation/image-to-image"
        payload["reference_images"] = [
            {"base64": base64.b64encode(path.read_bytes()).decode("ascii")}
            for path in references
        ]
    transaction = transaction_path(transaction_dir, row, model, resolution)
    intent = {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "episode": str(row.get("episode") or "UNKNOWN"), "task_key": row["id"], "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": submission_fingerprint(row, model, resolution),
        "state": "INTENT_RECORDED", "intent_recorded_at": utc_now(),
        "model": model, "prompt_sha256": row["prompt_sha256"],
        "reference_image_sha256s": list(row.get("reference_image_sha256s") or []),
        "endpoint": endpoint,
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    atomic_json(transaction, intent)
    previous_context = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
    try:
        response = _request(endpoint, payload)
    except (Exception, SystemExit) as exc:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": str(exc), "response_lost_at": utc_now()})
        atomic_json(transaction, intent)
        raise
    finally:
        if previous_context is None:
            os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        else:
            os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous_context
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "error": "response has no task_id", "response_lost_at": utc_now()})
        atomic_json(transaction, intent)
        raise RuntimeError(f"{row['id']} response has no task_id")
    receipt_path = output_dir / f"{row['id']}_submit_response.json"
    atomic_json(receipt_path, response)
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id, "receipt": str(receipt_path.relative_to(ROOT)), "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    return {"task_key": row["id"], "character_id": row["id"], "task_id": task_id, "status": "SUBMITTED", "receipt": str(receipt_path.relative_to(ROOT)), "transaction": str(transaction.relative_to(ROOT)), "recovered_from_transaction": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--precheck-only", action="store_true")
    args = parser.parse_args()
    plan_path = resolve(args.plan)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    rows = plan.get("new_asset_groups") or []
    if not rows:
        raise SystemExit("character asset plan contains zero new_asset_groups")
    if plan.get("quality") != "pro":
        raise SystemExit("character asset plan must use pro quality")
    for row in rows:
        row.setdefault("episode", plan.get("episode"))
    gate_paths = plan.get("machine_gate_reports") or []
    if not gate_paths:
        raise SystemExit("character asset plan has no machine_gate_reports")
    for gate_value in gate_paths:
        gate_path = resolve(gate_value)
        if not gate_path.is_file() or json.loads(gate_path.read_text(encoding="utf-8")).get("status") != "PASS":
            raise SystemExit(f"character asset gate is not PASS: {gate_value}")
    for row in rows:
        prompt_path = resolve(row.get("prompt_file", ""))
        if not prompt_path.is_file() or hashlib.sha256(prompt_path.read_bytes()).hexdigest() != row.get("prompt_sha256"):
            raise SystemExit(f"invalid prompt binding: {row.get('id')}")
        try:
            resolved_reference_images(row)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if not args.precheck_only and not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY is not set")
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt_dir = out.parent / f"{out.stem}_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    episode_key = str(plan.get("episode") or "UNKNOWN").replace("/", "-")
    transaction_dir = ROOT / "workflow" / "tasks" / "giggle_submit_transactions" / episode_key
    transaction_dir.mkdir(parents=True, exist_ok=True)
    results, failures = [], []
    submit_started_at = datetime.now(timezone.utc)
    if args.precheck_only:
        results = [{"character_id": row["id"], "status": "PRECHECK_PASS"} for row in rows]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {pool.submit(submit, row, receipt_dir, transaction_dir, "gpt-image-2-pro", "2K"): row for row in rows}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except (Exception, SystemExit) as exc:
                    row = futures[future]
                    failures.append({"character_id": row["id"], "status": "SUBMIT_FAILED", "error": str(exc), "transaction": str(transaction_path(transaction_dir, row, "gpt-image-2-pro", "2K").relative_to(ROOT))})
    credit_reconciliation = None
    ambiguity_resolution = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_submitted = sum(not row.get("recovered_from_transaction") for row in results)
        recovered = sum(bool(row.get("recovered_from_transaction")) for row in results)
        maximum_possible = newly_submitted + len(failures)
        if maximum_possible == 0:
            credit_reconciliation = {"status": "PASS_REUSED_TRANSACTIONS", "matched_count": 0, "charged_credits": 0}
            matched = 0
        else:
            for attempt in range(7):
                credit_reconciliation = reconcile_rows(fetch_pay_statements(), start=submit_started_at - timedelta(seconds=10), end=datetime.now(timezone.utc) + timedelta(seconds=10), expected_count=maximum_possible, event_description="SingleGenerateImage", model="gpt-image-2-pro")
                matched = int(credit_reconciliation.get("matched_count", 0))
                if matched >= newly_submitted or attempt == 6:
                    break
                time.sleep(5)
            if newly_submitted <= matched <= maximum_possible:
                credit_reconciliation["status"] = "PASS_BOUNDED"
        extra_charges = matched - newly_submitted
        if failures and extra_charges == 0:
            ambiguity_resolution = "ALL_RESPONSE_LOSSES_VERIFIED_NOT_CHARGED"
            failure_state = "VERIFIED_ZERO_RETRYABLE"
        elif failures:
            ambiguity_resolution = "CHARGED_OR_UNRESOLVED_RESPONSE_LOSS_QUARANTINED"
            failure_state = "CHARGE_STATE_UNRESOLVED_BATCH"
        else:
            ambiguity_resolution = "NO_AMBIGUOUS_SUBMISSIONS"
            failure_state = None
        for failure in failures:
            path = resolve(failure["transaction"])
            transaction = json.loads(path.read_text(encoding="utf-8"))
            transaction.update({"state": failure_state, "ledger_reconciled_at": utc_now(), "batch_known_task_ids": newly_submitted, "batch_ledger_pay_rows": matched})
            atomic_json(path, transaction)
        atomic_json(out.parent / f"{out.stem}_credit_statement.json", credit_reconciliation)
    generation_pass = len(results) == len(rows) and not failures
    cost_pass = args.precheck_only or (credit_reconciliation or {}).get("status") in {"PASS", "PASS_BOUNDED", "PASS_REUSED_TRANSACTIONS"}
    report = {
        "schema": "qingshan.character_asset_submit.v1",
        "episode": plan.get("episode"),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "plan": str(plan_path.relative_to(ROOT)),
        "model": "gpt-image-2-pro",
        "resolution": "2K",
        "concurrency": max(1, args.concurrency),
        "precheck_only": args.precheck_only,
        "status": "PASS" if generation_pass and cost_pass else "FAIL",
        "results": sorted(results, key=lambda row: row["character_id"]),
        "failures": sorted(failures, key=lambda row: row["character_id"]),
        "credit_reconciliation": credit_reconciliation,
        "ambiguity_resolution": ambiguity_resolution,
        "transaction_dir": str(transaction_dir.relative_to(ROOT)),
        "duplicate_submit_policy": "TASK_FINGERPRINT_TRANSACTION_GUARD",
        "credits": {"pay": (credit_reconciliation or {}).get("charged_credits", 0) if not args.precheck_only else 0, "refund": 0, "net": (credit_reconciliation or {}).get("charged_credits", 0) if not args.precheck_only else 0, "cap": 10000}
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "result_count": len(results), "failure_count": len(failures)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
