#!/usr/bin/env python3
"""Submit a batch of Giggle image tasks concurrently with gate evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from giggle_api_client import _image_list, _request
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from shot_space_camera_constraint_gate import evaluate_task as evaluate_spatial_task
    from global_space_layout_gate import evaluate_batch as evaluate_global_space_map
    from shot_media_admission_gate import precheck_submission_inputs
    from image_model_adapter import require_paid_image_model_contract
    from retry_cap_gate import validate_submission_attempt
except ModuleNotFoundError:  # Imported as tools.submit_giggle_image_manifest.
    from tools.giggle_api_client import _image_list, _request
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.shot_space_camera_constraint_gate import evaluate_task as evaluate_spatial_task
    from tools.global_space_layout_gate import evaluate_batch as evaluate_global_space_map
    from tools.shot_media_admission_gate import precheck_submission_inputs
    from tools.image_model_adapter import require_paid_image_model_contract
    from tools.retry_cap_gate import validate_submission_attempt


ROOT = Path(__file__).resolve().parents[1]


def portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


class DuplicateSubmissionBlocked(RuntimeError):
    """Raised when a prior charged or unresolved intent cannot be resubmitted safely."""


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def submission_fingerprint(task: dict[str, Any]) -> str:
    contract = {
        "task_key": task.get("task_key"),
        "prompt_sha256": task.get("prompt_sha256"),
        "references": [row.get("sha256") for row in task.get("reference_bindings") or []],
        "model": task.get("model", "gpt-image-2-pro"),
        "aspect_ratio": task.get("aspect_ratio", "9:16"),
        "resolution": task.get("resolution", "1K"),
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


def transaction_path(transaction_dir: Path, task: dict[str, Any]) -> Path:
    fingerprint = submission_fingerprint(task)
    return transaction_dir / f"{task['task_key']}__{fingerprint[:16]}.json"


def prior_submission_result(task: dict[str, Any], transaction_dir: Path) -> dict[str, Any] | None:
    path = transaction_path(transaction_dir, task)
    if not path.is_file():
        return None
    transaction = json.loads(path.read_text(encoding="utf-8"))
    if transaction.get("submission_fingerprint") != submission_fingerprint(task):
        raise DuplicateSubmissionBlocked(
            f"{task['task_key']} has a transaction with a different submission fingerprint"
        )
    state = transaction.get("state")
    if state == "SUBMITTED_TASK_ID_BOUND" and transaction.get("task_id"):
        return {
            "task_key": task["task_key"],
            "beat_id": task.get("beat_id"),
            "task_id": transaction["task_id"],
            "status": "submitted",
            "receipt": transaction.get("receipt"),
            "transaction": portable_path(path),
            "recovered_from_transaction": True,
        }
    if state in {
        "INTENT_RECORDED",
        "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
        "CHARGED_TASK_ID_MISSING",
        "CHARGE_STATE_UNRESOLVED_BATCH",
    }:
        raise DuplicateSubmissionBlocked(
            f"{task['task_key']} duplicate submit blocked by transaction state {state}"
        )
    return None


def resolve(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def validate_gate(path: str) -> dict[str, Any]:
    report_path = resolve(path)
    if not report_path.is_file():
        raise ValueError(f"Missing gate report: {path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise ValueError(f"Gate is not PASS: {path}")
    return {
        "path": path,
        "status": "PASS",
        "schema": report.get("schema"),
        "gate_id": report.get("gate_id"),
        "reviewed_manifest_sha256": report.get("reviewed_manifest_sha256"),
    }


def validate_submission_authority(
    manifest: dict[str, Any],
    tasks: list[dict[str, Any]],
    gates: list[dict[str, Any]],
    manifest_path: Path,
) -> None:
    """Fail closed before paid POST when a precheck-only manifest is misused."""
    if manifest.get("provider_post_allowed") is not True:
        raise ValueError("manifest provider_post_allowed must be true for paid submission")
    maximum = manifest.get("maximum_new_submissions")
    if not isinstance(maximum, int) or maximum < len(tasks):
        raise ValueError("manifest maximum_new_submissions is below the selected task count")
    if not manifest.get("authorization_ref"):
        raise ValueError("manifest authorization_ref is required for paid submission")
    for task in tasks:
        if task.get("status") != "READY_TO_SUBMIT":
            raise ValueError(f"{task.get('task_key')} is not READY_TO_SUBMIT")
        if task.get("provider_post_allowed") is not True:
            raise ValueError(f"{task.get('task_key')} provider_post_allowed must be true")
        if task.get("maximum_new_submissions") != 1:
            raise ValueError(f"{task.get('task_key')} maximum_new_submissions must equal 1")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    budget_gates = [gate for gate in gates if gate.get("gate_id") == "GIGGLE-REROLL-COST-GUARD"]
    if len(budget_gates) != 1:
        raise ValueError("paid submission requires exactly one registered GIGGLE-REROLL-COST-GUARD report")
    if budget_gates[0].get("reviewed_manifest_sha256") != manifest_sha:
        raise ValueError("GIGGLE-REROLL-COST-GUARD does not bind the exact submission manifest SHA")


def validate_anchor_count_gate_requirement(
    manifest: dict[str, Any], gates: list[dict[str, Any]]
) -> None:
    tasks = manifest.get("tasks") or []
    if not any(task.get("video_unit_id") for task in tasks):
        return
    if not any(gate.get("schema") == "qingshan.video_unit_anchor_count_gate.v1" for gate in gates):
        raise ValueError(
            "Video-unit image batches require a passing qingshan.video_unit_anchor_count_gate.v1 report; "
            "anchor count must be justified per unit, never fixed to one or fixed to multiple images."
        )

    consumer = manifest.get("consumer_contract") or {}
    planned = consumer.get("planned_anchor_count")
    if not isinstance(planned, int) or planned <= len(tasks):
        return
    dependent = manifest.get("dependent_anchor_specs") or []
    if len(dependent) != planned - len(tasks):
        raise ValueError(
            "Partial anchor batches must declare every dependent anchor before initial submit"
        )
    initial_keys = {task.get("task_key") for task in tasks}
    dependent_keys = {row.get("task_key") for row in dependent}
    if None in dependent_keys or len(dependent_keys) != len(dependent):
        raise ValueError("Dependent anchor task keys must be present and unique")
    if any(row.get("depends_on_task_key") not in initial_keys for row in dependent):
        raise ValueError("Every dependent anchor must name an initial task dependency")
    if set(manifest.get("blocked_tasks") or []) != dependent_keys:
        raise ValueError("blocked_tasks must exactly match declared dependent anchors")


def validate_mask_transport(task: dict[str, Any]) -> None:
    """Fail closed when a manifest claims mask semantics the endpoint cannot enforce.

    The current Giggle image-to-image request carries every input through
    ``reference_images``. A binding named ``edit_mask`` is therefore only a
    visual reference; its SHA does not make it a provider-native edit mask.
    """
    mask_bindings = [
        row for row in task.get("reference_bindings") or []
        if row.get("role") == "edit_mask"
    ]
    if not mask_bindings:
        return
    transport = task.get("mask_transport") or {}
    if transport.get("mode") != "provider_native":
        raise ValueError(
            f"{task.get('task_key', 'UNKNOWN')} edit_mask is reference-only; "
            "exact mask submission requires provider-native mask transport"
        )
    raise ValueError(
        f"{task.get('task_key', 'UNKNOWN')} provider-native mask transport is not implemented "
        "for /api/v1/generation/image-to-image"
    )


def validate_task(task: dict[str, Any]) -> None:
    retry_failures = validate_submission_attempt(task)
    if retry_failures:
        raise ValueError(
            f"{task.get('task_key')} BLOCK_RETRY_CAP_GATE: {','.join(retry_failures)}"
        )
    episode_match = re.match(r"E(\d+)", str(task.get("episode") or "").upper())
    for field in ("task_key", "prompt_file", "reference_images"):
        if not task.get(field):
            raise ValueError(f"{task.get('task_key', 'UNKNOWN')} missing {field}")
    if task.get("tool_type") != "image_generation":
        raise ValueError(f"{task['task_key']} is not an image_generation task")
    validate_mask_transport(task)
    prompt_path = resolve(task["prompt_file"])
    if not prompt_path.is_file():
        raise ValueError(f"Missing prompt: {task['prompt_file']}")
    actual_prompt_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if actual_prompt_sha != task.get("prompt_sha256"):
        raise ValueError(f"{task['task_key']} prompt SHA mismatch")
    contract = task.get("prompt_contract") or {}
    if contract.get("schema") != "qingshan.image_prompt_contract.v2" or contract.get("status") != "PASS":
        raise ValueError(f"{task['task_key']} prompt contract is not PASS v2")
    if contract.get("shot_id") != task.get("shot_id") or contract.get("source_script_sha256") != task.get("source_script_sha256"):
        raise ValueError(f"{task['task_key']} prompt contract source binding mismatch")
    if contract.get("source_action_sha256") != hashlib.sha256(str(contract.get("source_action", "")).encode("utf-8")).hexdigest():
        raise ValueError(f"{task['task_key']} source action SHA mismatch")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if episode_match and int(episode_match.group(1)) >= 40:
        require_paid_image_model_contract(
            task, str(task.get("episode")), prompt_text=prompt_text
        )
    if contract.get("source_action") not in prompt_text:
        raise ValueError(f"{task['task_key']} prompt omits exact source action")
    spatial = evaluate_spatial_task(task, prompt_text)
    if spatial["status"] != "PASS":
        codes = ", ".join(row["code"] for row in spatial["failures"])
        raise ValueError(f"{task['task_key']} spatial/camera gate failed: {codes}")
    bindings = task.get("reference_bindings") or []
    if bindings != contract.get("reference_bindings"):
        raise ValueError(f"{task['task_key']} reference bindings differ from prompt contract")
    character_ids = [row.get("entity_id") for row in bindings if row.get("role") == "character"]
    visible_characters = list(contract.get("visible_characters") or [])
    if character_ids != visible_characters:
        raise ValueError(f"{task['task_key']} visible-character/reference mismatch")
    if any(row.get("qa_status") != "PASS" for row in bindings if row.get("role") == "character"):
        raise ValueError(f"{task['task_key']} has an unverified character identity asset")
    if len([row for row in bindings if row.get("role") in {"scene", "destination_scene"}]) != 1:
        raise ValueError(f"{task['task_key']} must have exactly one scene reference")
    for binding in bindings:
        path = resolve(binding["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != binding.get("sha256"):
            raise ValueError(f"{task['task_key']} reference binding SHA mismatch: {binding.get('path')}")
    transport_rows = task.get("reference_image_sequence") or bindings
    bound_transport_paths = list(dict.fromkeys(row["path"] for row in transport_rows))
    if task.get("reference_images") != bound_transport_paths:
        raise ValueError(f"{task['task_key']} reference image order differs from bound contract")
    input_precheck = precheck_submission_inputs(task)
    if input_precheck["status"] != "PASS":
        missing = input_precheck["missing_characters"] + input_precheck["missing_props"]
        raise ValueError(
            f"{task['task_key']} submission input precheck failed: "
            + ", ".join(missing or input_precheck["failures"])
        )


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    recovered = prior_submission_result(task, transaction_dir)
    if recovered:
        return recovered
    # Re-run immediately before transaction creation/provider POST.  A batch
    # may sit between manifest validation and dispatch, so this is deliberately
    # not treated as a one-time compile check.
    input_precheck = precheck_submission_inputs(task)
    if input_precheck["status"] != "PASS":
        missing = input_precheck["missing_characters"] + input_precheck["missing_props"]
        raise ValueError(
            f"{task['task_key']} submission input precheck failed before POST: "
            + ", ".join(missing or input_precheck["failures"])
        )
    prompt = resolve(task["prompt_file"]).read_text(encoding="utf-8")
    episode_match = re.match(r"E(\d+)", str(task.get("episode") or "").upper())
    if episode_match and int(episode_match.group(1)) >= 40:
        # Repeat at the paid boundary. A prior batch-level validation is not
        # sufficient because manifests may wait before dispatch.
        require_paid_image_model_contract(
            task, str(task.get("episode")), prompt_text=prompt
        )
    references = [str(resolve(path)) for path in task["reference_images"]]
    payload = {
        "prompt": prompt,
        "reference_images": _image_list(references),
        "generate_count": 1,
        "model": task.get("model", "gpt-image-2-pro"),
        "aspect_ratio": task.get("aspect_ratio", "9:16"),
        "resolution": task.get("resolution", "1K"),
        "watermark": False,
    }
    transaction = transaction_path(transaction_dir, task)
    intent = {
        "schema": "qingshan.giggle_submit_transaction.v1",
        "task_key": task["task_key"],
        "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": submission_fingerprint(task),
        "state": "INTENT_RECORDED",
        "intent_recorded_at": utc_now(),
        "model": payload["model"],
        "prompt_sha256": task.get("prompt_sha256"),
        "reference_sha256": [row.get("sha256") for row in task.get("reference_bindings") or []],
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    atomic_json(transaction, intent)
    previous_context = os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT")
    os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = "1"
    try:
        response = _request("/api/v1/generation/image-to-image", payload)
    except (Exception, SystemExit) as exc:
        intent.update({
            "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
            "response_lost_at": utc_now(),
            "error": str(exc),
        })
        atomic_json(transaction, intent)
        raise
    finally:
        if previous_context is None:
            os.environ.pop("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", None)
        else:
            os.environ["QINGSHAN_DURABLE_SUBMITTER_CONTEXT"] = previous_context
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        intent.update({
            "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
            "response_lost_at": utc_now(),
            "error": "Submit response missing data.task_id",
        })
        atomic_json(transaction, intent)
        raise RuntimeError("Submit response missing data.task_id")
    receipt = receipt_dir / f"{task['task_key']}_submit_receipt.json"
    atomic_json(receipt, response)
    intent.update({
        "state": "SUBMITTED_TASK_ID_BOUND",
        "response_recorded_at": utc_now(),
        "task_id": task_id,
        "receipt": str(receipt.relative_to(ROOT)),
    })
    atomic_json(transaction, intent)
    return {
        "task_key": task["task_key"],
        "beat_id": task.get("beat_id"),
        "task_id": task_id,
        "status": "submitted",
        "receipt": str(receipt.relative_to(ROOT)),
        "transaction": portable_path(transaction),
        "recovered_from_transaction": False,
    }


def submit_all(
    tasks: list[dict[str, Any]], receipt_dir: Path, transaction_dir: Path, concurrency: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Submit every item and preserve isolated client exits as item failures."""
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(submit_one, task, receipt_dir, transaction_dir): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                results.append(future.result())
            except (Exception, SystemExit) as exc:
                failures.append({
                    "task_key": task["task_key"],
                    "status": "submit_response_lost",
                    "credit": None,
                    "credit_status": "PENDING_LEDGER_RECONCILIATION",
                    "error": str(exc),
                    "transaction": portable_path(transaction_path(transaction_dir, task)),
                })
    return results, failures


def classify_ambiguous_failures(
    failures: list[dict[str, Any]],
    *,
    known_submitted: int,
    matched_ledger_rows: int,
    transaction_dir: Path,
) -> str:
    """Classify response-loss rows without pretending that an HTTP timeout means zero cost."""
    ambiguous = len(failures)
    extra_charges = matched_ledger_rows - known_submitted
    if ambiguous == 0:
        return "NO_AMBIGUOUS_SUBMISSIONS"
    if extra_charges == 0:
        state = "NOT_CHARGED_RETRYABLE"
        status = "FAILED_ZERO_VERIFIED"
        credit = 0
        summary = "ALL_RESPONSE_LOSSES_VERIFIED_NOT_CHARGED"
    elif ambiguous == 1 and extra_charges == 1:
        state = "CHARGED_TASK_ID_MISSING"
        status = "CHARGED_TASK_ID_MISSING"
        credit = None
        summary = "ONE_CHARGED_RESPONSE_LOSS_REQUIRES_TASK_HISTORY_RECOVERY"
    else:
        state = "CHARGE_STATE_UNRESOLVED_BATCH"
        status = "CHARGE_STATE_UNRESOLVED_BATCH"
        credit = None
        summary = "BATCH_RESPONSE_LOSSES_QUARANTINED_PENDING_TASK_HISTORY_RECOVERY"
    for failure in failures:
        failure["status"] = "submit_failed" if state == "NOT_CHARGED_RETRYABLE" else "submit_quarantined"
        failure["credit"] = credit
        failure["credit_status"] = status
        path = transaction_dir / Path(failure["transaction"]).name
        transaction = json.loads(path.read_text(encoding="utf-8"))
        transaction.update({
            "state": state,
            "ledger_reconciled_at": utc_now(),
            "batch_known_task_ids": known_submitted,
            "batch_ledger_pay_rows": matched_ledger_rows,
            "batch_unmapped_pay_rows": max(0, extra_charges),
            "retry_guard": (
                "RETRY_ALLOWED_NEW_ATTEMPT" if state == "NOT_CHARGED_RETRYABLE"
                else "DO_NOT_RESUBMIT_RECOVER_TASK_ID_FROM_PROVIDER_HISTORY"
            ),
        })
        atomic_json(path, transaction)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--precheck-only", action="store_true")
    parser.add_argument("--task-key", action="append", default=[], help="Submit only the named task key; repeat as needed")
    args = parser.parse_args()

    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_tasks = manifest.get("tasks") or []
    if not all_tasks:
        raise SystemExit("Image manifest contains zero tasks")
    gates = [validate_gate(path) for path in manifest.get("machine_gate_reports") or []]
    if not gates:
        raise SystemExit("Image manifest has no machine_gate_reports")
    validate_anchor_count_gate_requirement(manifest, gates)
    global_space_map_gate = evaluate_global_space_map(
        manifest.get("episode_global_space_map_ref"),
        all_tasks,
        episode=manifest.get("episode"),
        required=manifest.get("global_space_map_gate_required"),
    )
    if global_space_map_gate.get("status") == "FAIL":
        codes = sorted({
            f"{row.get('check')}:{row.get('reason')}"
            for row in global_space_map_gate.get("failures") or []
        })
        raise ValueError(
            "SCENE-AUTHORITY-LOCK global space-map component failed: "
            + ", ".join(codes)
        )
    tasks = all_tasks
    if args.task_key:
        requested = set(args.task_key)
        available = {task.get("task_key") for task in all_tasks}
        unknown = sorted(requested - available)
        if unknown:
            raise SystemExit(f"Unknown image task keys: {', '.join(unknown)}")
        tasks = [task for task in all_tasks if task.get("task_key") in requested]
    if not args.precheck_only:
        validate_submission_authority(manifest, tasks, gates, manifest_path)
    for task in tasks:
        validate_task(task)
    if not args.precheck_only and not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY is not set")

    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt_dir = out.parent / f"{out.stem}_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    episode_key = str(manifest.get("episode") or "UNKNOWN").replace("/", "-")
    transaction_dir = ROOT / "workflow" / "tasks" / "giggle_submit_transactions" / episode_key
    transaction_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    submit_started_at = datetime.now(timezone.utc)
    if args.precheck_only:
        results = [{"task_key": task["task_key"], "beat_id": task.get("beat_id"), "status": "precheck_pass"} for task in tasks]
    else:
        results, failures = submit_all(tasks, receipt_dir, transaction_dir, args.concurrency)
    submit_finished_at = datetime.now(timezone.utc)

    results.sort(key=lambda row: row["task_key"])
    failures.sort(key=lambda row: row["task_key"])
    credit_reconciliation = None
    ambiguity_resolution = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_submitted = sum(
            row["status"] == "submitted" and not row.get("recovered_from_transaction")
            for row in results
        )
        recovered_submitted = sum(bool(row.get("recovered_from_transaction")) for row in results)
        maximum_possible_charges = newly_submitted + len(failures)
        if maximum_possible_charges == 0:
            credit_reconciliation = {
                "status": "PASS_REUSED_TRANSACTIONS",
                "method": "NO_NEW_POST_REUSED_DURABLE_TASK_ID_BINDINGS",
                "newly_submitted": 0,
                "recovered_task_ids": recovered_submitted,
                "charged_credits_this_run": 0,
            }
            matched = 0
        else:
            for attempt in range(7):
                credit_reconciliation = reconcile_rows(
                    fetch_pay_statements(),
                    start=submit_started_at - timedelta(seconds=10),
                    end=datetime.now(timezone.utc) + timedelta(seconds=10),
                    expected_count=maximum_possible_charges,
                    event_description="SingleGenerateImage",
                    model=str(tasks[0].get("model", "gpt-image-2-pro")),
                )
                matched = int(credit_reconciliation.get("matched_count", 0))
                if matched >= newly_submitted or attempt == 6:
                    break
                time.sleep(5)
            if newly_submitted <= matched <= maximum_possible_charges:
                credit_reconciliation["status"] = "PASS_BOUNDED"
                credit_reconciliation["known_task_id_count"] = newly_submitted
                credit_reconciliation["recovered_task_id_count"] = recovered_submitted
                credit_reconciliation["ambiguous_response_count"] = len(failures)
                credit_reconciliation["unmapped_pay_row_count"] = matched - newly_submitted
        ambiguity_resolution = classify_ambiguous_failures(
            failures,
            known_submitted=newly_submitted,
            matched_ledger_rows=matched,
            transaction_dir=transaction_dir,
        )
        credit_out = out.parent / f"{out.stem}_credit_statement.json"
        atomic_json(credit_out, credit_reconciliation)

    generation_pass = len(results) == len(tasks) and not failures
    cost_pass = args.precheck_only or (credit_reconciliation or {}).get("status") in {
        "PASS", "PASS_BOUNDED", "PASS_REUSED_TRANSACTIONS"
    }
    report = {
        "schema": "qingshan.giggle_image_batch_submit.v2",
        "episode": manifest.get("episode"),
        "manifest": str(manifest_path.relative_to(ROOT)),
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "precheck_only": args.precheck_only,
        "concurrency": max(1, args.concurrency),
        "task_filter": sorted(args.task_key),
        "machine_gates": gates,
        "global_space_map_gate": global_space_map_gate,
        "status": "PASS" if generation_pass and cost_pass else "FAIL",
        "submitted": sum(row["status"] == "submitted" for row in results),
        "newly_submitted": sum(
            row["status"] == "submitted" and not row.get("recovered_from_transaction")
            for row in results
        ),
        "recovered_task_ids": sum(bool(row.get("recovered_from_transaction")) for row in results),
        "precheck_pass": sum(row["status"] == "precheck_pass" for row in results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
        "credit_reconciliation": credit_reconciliation,
        "ambiguity_resolution": ambiguity_resolution,
        "transaction_dir": portable_path(transaction_dir),
        "duplicate_submit_policy": "TASK_FINGERPRINT_TRANSACTION_GUARD",
    }
    atomic_json(out, report)
    print(json.dumps({key: report[key] for key in ("status", "submitted", "precheck_pass", "failed")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
