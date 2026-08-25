#!/usr/bin/env python3
"""Durably submit independent Giggle video tasks without sacrificing concurrency."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from giggle_api_client import _image_list, _request
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from video_model_adapter import require_paid_model_contract
    from retry_cap_gate import validate_submission_attempt
except ModuleNotFoundError:
    from tools.giggle_api_client import _image_list, _request
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.video_model_adapter import require_paid_model_contract
    from tools.retry_cap_gate import validate_submission_attempt


ROOT = Path(__file__).resolve().parents[1]


def authoritative_pipeline_tools_dir() -> Path:
    """Resolve the deployed BacklotOS tools; never silently fall back to a local copy."""
    configured = os.environ.get("BACKLOT_PIPELINE_TOOLS_DIR", "").strip()
    candidate = Path(configured).expanduser() if configured else Path.home() / ".local/share/backlotos/share/pipeline-tools"
    required = candidate / "production_video_submission_gate.py"
    if not required.is_file():
        raise ValueError(
            "Authoritative BacklotOS production gate is unavailable; run the BacklotOS deployment "
            "or set BACKLOT_PIPELINE_TOOLS_DIR. Paid submission fails closed."
        )
    return candidate.resolve()


def run_authoritative_submission_gate(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    tools_dir = authoritative_pipeline_tools_dir()
    module_path = tools_dir / "production_video_submission_gate.py"
    sys.path.insert(0, str(tools_dir))
    try:
        spec = importlib.util.spec_from_file_location("backlotos_production_video_submission_gate", module_path)
        if spec is None or spec.loader is None:
            raise ValueError("Cannot load authoritative BacklotOS production gate")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = module.evaluate_manifest(manifest, root=ROOT, manifest_path=manifest_path)
    finally:
        if sys.path and sys.path[0] == str(tools_dir):
            sys.path.pop(0)
    if report.get("status") != "PASS":
        codes = sorted({str(row.get("code") or "UNKNOWN") for row in report.get("failures") or []})
        raise ValueError(f"Authoritative BacklotOS production gate failed: {','.join(codes)}")
    return report


def normalized_han(value: str) -> str:
    return re.sub(r"[^\u3400-\u9fffA-Za-z0-9]", "", value or "")


def validate_source_caption_safe_dialogue(task: dict[str, Any], prompt_text: str) -> None:
    """Keep spoken copy out of the visual-language channel when subtitles are forbidden."""
    if task.get("native_dialogue_required") is not True:
        return
    policy = task.get("source_subtitle_policy", "FORBID")
    if policy != "FORBID":
        return
    transport = task.get("dialogue_transport")
    lines = [str(value) for value in task.get("dialogue_lines") or []]
    if transport == "MODEL_NATIVE_TEXT_DIALOGUE":
        if task.get("model_native_text_dialogue") is not True or not lines:
            raise ValueError(f"{task['task_key']} native text dialogue contract is incomplete")
        normalized_prompt = normalized_han(prompt_text)
        missing = [line for line in lines if normalized_han(line) not in normalized_prompt]
        if missing:
            raise ValueError(f"{task['task_key']} canonical native text dialogue is missing from prompt")
        return
    if transport != "EXACT_LINE_AUDIO_REFERENCE":
        raise ValueError(
            f"{task['task_key']} source-caption-forbidden dialogue requires "
            "dialogue_transport=EXACT_LINE_AUDIO_REFERENCE"
        )
    exact_asset_ids = task.get("exact_dialogue_audio_asset_ids") or []
    exact_urls = task.get("exact_dialogue_audio_urls") or []
    if not lines or not (
        len(exact_asset_ids) == len(lines) or len(exact_urls) == len(lines)
    ):
        raise ValueError(
            f"{task['task_key']} requires one ordered exact-line provider asset ID "
            "or public audio URL per dialogue line"
        )
    if any(not isinstance(value, str) or not value.strip() for value in exact_asset_ids):
        raise ValueError(f"{task['task_key']} exact dialogue audio asset IDs are invalid")
    if any(not isinstance(value, str) or not value.startswith("https://") for value in exact_urls):
        raise ValueError(f"{task['task_key']} exact dialogue audio URLs must be public HTTPS URLs")
    normalized_prompt = normalized_han(prompt_text)
    leaked = [line for line in lines if normalized_han(line) and normalized_han(line) in normalized_prompt]
    if leaked:
        raise ValueError(f"{task['task_key']} literal dialogue leaked into visual prompt")


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def portable(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate_gate(path_value: str) -> dict[str, Any]:
    path = resolve(path_value)
    if not path.is_file():
        raise ValueError(f"Missing gate report: {path_value}")
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise ValueError(f"Gate is not PASS: {path_value}")
    return {"path": path_value, "status": "PASS", "schema": report.get("schema")}


def task_fingerprint(task: dict[str, Any]) -> str:
    contract = {
        "task_key": task.get("task_key"),
        "prompt_sha256": task.get("prompt_sha256"),
        "reference_sha256": task.get("reference_sha256") or [],
        "reference_audio_asset_ids": task.get("reference_audio_asset_ids") or [],
        "exact_dialogue_audio_asset_ids": task.get("exact_dialogue_audio_asset_ids") or [],
        "reference_audio_urls": task.get("reference_audio_urls") or [],
        "exact_dialogue_audio_urls": task.get("exact_dialogue_audio_urls") or [],
        "dialogue_transport": task.get("dialogue_transport"),
        "model": task.get("model"),
        "duration": task.get("duration_seconds"),
        "aspect_ratio": task.get("aspect_ratio"),
        "resolution": task.get("resolution"),
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


def transaction_path(transaction_dir: Path, task: dict[str, Any]) -> Path:
    return transaction_dir / f"{task['task_key']}__{task_fingerprint(task)[:16]}.json"


def validate_task(task: dict[str, Any]) -> None:
    require_paid_model_contract(task, str(task.get("episode") or "E40"))
    for field in ("task_key", "prompt_file", "prompt_sha256", "reference_images", "reference_sha256"):
        if not task.get(field):
            raise ValueError(f"{task.get('task_key', 'UNKNOWN')} missing {field}")
    prompt = resolve(task["prompt_file"])
    if not prompt.is_file() or sha256(prompt) != task["prompt_sha256"]:
        raise ValueError(f"{task['task_key']} prompt SHA mismatch")
    prompt_text = prompt.read_text(encoding="utf-8")
    references = [resolve(value) for value in task["reference_images"]]
    if len(references) != len(task["reference_sha256"]):
        raise ValueError(f"{task['task_key']} reference count/SHA count mismatch")
    for path, expected in zip(references, task["reference_sha256"]):
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"{task['task_key']} reference SHA mismatch: {portable(path)}")
    audio_asset_ids = [
        *(task.get("exact_dialogue_audio_asset_ids") or []),
        *(task.get("reference_audio_asset_ids") or []),
    ]
    if any(not isinstance(value, str) or not value.strip() for value in audio_asset_ids):
        raise ValueError(f"{task['task_key']} has invalid reference_audio_asset_ids")
    audio_urls = [
        *(task.get("exact_dialogue_audio_urls") or []),
        *(task.get("reference_audio_urls") or []),
    ]
    if task.get("native_dialogue_required") and task.get("dialogue_transport") == "EXACT_LINE_AUDIO_REFERENCE" and not (audio_asset_ids or audio_urls):
        raise ValueError(f"{task['task_key']} native dialogue lacks provider audio asset IDs or public audio URLs")
    if any(not isinstance(value, str) or not value.startswith("https://") for value in audio_urls):
        raise ValueError(f"{task['task_key']} audio references must be public HTTPS URLs")
    validate_source_caption_safe_dialogue(task, prompt_text)
    selected_audio_references = audio_asset_ids or audio_urls
    if len(selected_audio_references) >= 3:
        raise ValueError(f"{task['task_key']} Giggle accepts fewer than 3 total audio references")
    if task.get("model") != "seedance-2.0-fast":
        raise ValueError(f"{task['task_key']} requires seedance-2.0-fast; Pro, Mini, bare seedance-2.0, and unknown models are forbidden")
    if task.get("resolution") != "720p":
        raise ValueError(f"{task['task_key']} must use provider-native 720p for seedance-2.0-fast")
    if not 4 <= int(task.get("duration_seconds", 0)) <= 15:
        raise ValueError(f"{task['task_key']} duration outside 4-15 seconds")
    if task.get("action_unit"):
        tempo = task.get("performance_tempo_contract") or {}
        windows = tempo.get("atomic_action_windows") or []
        if tempo.get("playback_speed") != "REAL_TIME_1X" or not windows:
            raise ValueError(f"{task['task_key']} missing action tempo contract")
        if min(float(row["start_seconds"]) for row in windows) > 0.5:
            raise ValueError(f"{task['task_key']} action onset exceeds 0.5 seconds")
        if any(float(row["end_seconds"]) - float(row["start_seconds"]) > 1.200001 for row in windows):
            raise ValueError(f"{task['task_key']} atomic action exceeds 1.2 seconds")
    sequence = task.get("action_sequence_contract") or {}
    if sequence.get("depends_on_task") and not task.get("predecessor_tail_frame"):
        raise ValueError(f"{task['task_key']} dependent task lacks exact predecessor tail")


def prior_bound(task: dict[str, Any], transaction_dir: Path) -> dict[str, Any] | None:
    path = transaction_path(transaction_dir, task)
    if not path.is_file():
        return None
    row = json.loads(path.read_text(encoding="utf-8"))
    if row.get("submission_fingerprint") != task_fingerprint(task):
        raise RuntimeError(f"{task['task_key']} transaction fingerprint mismatch")
    if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
        return {
            "task_key": task["task_key"], "task_id": row["task_id"], "state": "remote_running",
            "receipt": row.get("receipt"), "transaction": portable(path), "recovered_from_transaction": True,
        }
    if row.get("state") not in {"VERIFIED_ZERO_RETRYABLE"}:
        raise RuntimeError(f"{task['task_key']} blocked by transaction state {row.get('state')}")
    return None


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    prior = prior_bound(task, transaction_dir)
    if prior:
        return prior
    transaction = transaction_path(transaction_dir, task)
    intent = {
        "schema": "qingshan.giggle_video_submit_transaction.v1",
        "task_key": task["task_key"], "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": task_fingerprint(task), "state": "INTENT_RECORDED",
        "intent_recorded_at": utc_now(), "prompt_sha256": task["prompt_sha256"],
        "reference_sha256": task["reference_sha256"], "model": task["model"],
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    atomic_json(transaction, intent)
    payload = {
        "prompt": resolve(task["prompt_file"]).read_text(encoding="utf-8"),
        "model": task["model"], "duration": int(task["duration_seconds"]),
        "aspect_ratio": task.get("aspect_ratio", "9:16"), "resolution": task["resolution"],
        "generating_count": 1,
        "images": _image_list([str(resolve(value)) for value in task["reference_images"]]),
    }
    audio_asset_ids = [
        *(task.get("exact_dialogue_audio_asset_ids") or []),
        *(task.get("reference_audio_asset_ids") or []),
    ]
    audio_urls = [
        *(task.get("exact_dialogue_audio_urls") or []),
        *(task.get("reference_audio_urls") or []),
    ]
    if audio_asset_ids:
        payload["audios"] = [{"asset_id": value} for value in audio_asset_ids]
    elif audio_urls:
        payload["audios"] = [{"url": value} for value in audio_urls]
    try:
        response = _request("/api/v1/generation/omni-video", payload)
    except (Exception, SystemExit) as exc:
        intent.update({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION", "response_lost_at": utc_now(), "error": str(exc)})
        atomic_json(transaction, intent)
        raise
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    if not task_id:
        response_sha256 = hashlib.sha256(
            json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        intent.update({
            "state": "PROVIDER_RESPONSE_NO_TASK_ID_PENDING_CLASSIFICATION",
            "response_received_at": utc_now(),
            "error": "response missing task_id",
            "provider_response": response,
            "provider_response_sha256": response_sha256,
            "failure_classification": "PROVIDER_RESPONSE_RECEIVED_NO_TASK_ID",
            "retry_guard": "DO_NOT_RESUBMIT_UNTIL_PROVIDER_RESPONSE_CLASSIFIED_AND_LEDGER_RECONCILED",
        })
        atomic_json(transaction, intent)
        raise RuntimeError(f"response missing task_id: {json.dumps(response, ensure_ascii=False)}")
    receipt = receipt_dir / f"{task['task_key']}_submit_receipt.json"
    atomic_json(receipt, response)
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(task_id), "receipt": portable(receipt), "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    return {
        **task, "task_id": str(task_id), "state": "remote_running", "submitted_at": utc_now(),
        "receipt": portable(receipt), "transaction": portable(transaction), "recovered_from_transaction": False,
        "credit_attempts": [{"attempt": 1, "task_id": str(task_id), "success": None, "charge_status": "PENDING_REMOTE_RESULT", "actual_charged_credits": None}],
    }


# The in-project implementation above is retained only so historical tests and
# receipts remain readable.  It used Omni images[] for every visual reference
# and must never perform another paid submission.  The CLI below always execs
# the deployed BacklotOS submitter; any direct import-based submit attempt fails
# closed instead of bypassing deployed transport policy.
_legacy_submit_one_for_audit_only = submit_one


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    raise RuntimeError(
        "LOCAL_LEGACY_VIDEO_SUBMIT_DISABLED: invoke the deployed BacklotOS "
        "submit_giggle_video_manifest_v2.py entrypoint"
    )


def classify_failures(failures: list[dict[str, Any]], known: int, matched: int, transaction_dir: Path) -> str:
    extra = matched - known
    if not failures:
        return "NO_AMBIGUOUS_SUBMISSIONS"
    if extra == 0:
        state, summary = "VERIFIED_ZERO_RETRYABLE", "ALL_RESPONSE_LOSSES_VERIFIED_ZERO"
    elif len(failures) == 1 and extra == 1:
        state, summary = "CHARGED_TASK_ID_MISSING", "RECOVER_ONE_TASK_ID_FROM_PROVIDER_HISTORY"
    else:
        state, summary = "CHARGE_STATE_UNRESOLVED_BATCH", "QUARANTINE_AMBIGUOUS_TASKS_ONLY"
    for failure in failures:
        path = resolve(failure["transaction"])
        row = json.loads(path.read_text(encoding="utf-8"))
        row.update({"state": state, "ledger_reconciled_at": utc_now(), "batch_known_task_ids": known, "batch_ledger_pay_rows": matched, "retry_guard": "RETRY_ALLOWED" if state == "VERIFIED_ZERO_RETRYABLE" else "DO_NOT_RESUBMIT_RECOVER_TASK_ID"})
        atomic_json(path, row)
        failure["credit_status"] = state
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--precheck-only", action="store_true")
    args = parser.parse_args()
    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    authoritative_gate = run_authoritative_submission_gate(manifest, manifest_path)
    gates = [validate_gate(value) for value in manifest.get("machine_gate_reports") or []]
    tasks = manifest.get("tasks") or []
    if not gates or not tasks:
        raise SystemExit("Video manifest requires passing gates and tasks")
    for task in tasks:
        validate_task(task)
    if not args.precheck_only and not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY is not set")
    out = resolve(args.out)
    receipts = out.parent / f"{out.stem}_receipts"
    transactions = ROOT / "workflow/tasks/giggle_video_submit_transactions" / str(manifest.get("episode") or "UNKNOWN")
    start = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if args.precheck_only:
        results = [{"task_key": task["task_key"], "state": "precheck_pass"} for task in tasks]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {pool.submit(submit_one, task, receipts, transactions): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    results.append(future.result())
                except (Exception, SystemExit) as exc:
                    failures.append({"task_key": task["task_key"], "state": "submit_response_lost", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
    credit = None
    ambiguity = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_bound = sum(not row.get("recovered_from_transaction") for row in results)
        maximum = newly_bound + len(failures)
        for attempt in range(7):
            credit = reconcile_rows(fetch_pay_statements(), start=start - timedelta(seconds=10), end=datetime.now(timezone.utc) + timedelta(seconds=10), expected_count=maximum, event_description="SingleGenerateVideo", model=str(tasks[0]["model"]))
            matched = int(credit.get("matched_count", 0))
            if matched >= newly_bound or attempt == 6:
                break
            time.sleep(5)
        if newly_bound <= matched <= maximum:
            credit["status"] = "PASS_BOUNDED"
            credit["known_task_id_count"] = newly_bound
            credit["ambiguous_response_count"] = len(failures)
            credit["unmapped_pay_row_count"] = matched - newly_bound
        ambiguity = classify_failures(failures, newly_bound, matched, transactions)
        atomic_json(out.parent / f"{out.stem}_credit_statement.json", credit)
    report = {
        "schema": "qingshan.giggle_video_batch_submit.v2", "episode": manifest.get("episode"),
        "manifest": portable(manifest_path), "manifest_sha256": sha256(manifest_path), "recorded_at": utc_now(),
        "precheck_only": args.precheck_only, "concurrency": max(1, args.concurrency), "machine_gates": gates,
        "authoritative_production_gate": authoritative_gate,
        "status": "PASS" if len(results) == len(tasks) and not failures and (args.precheck_only or (credit or {}).get("status") == "PASS_BOUNDED") else "FAIL",
        "submitted": sum(row.get("state") == "remote_running" for row in results),
        "precheck_pass": sum(row.get("state") == "precheck_pass" for row in results),
        "failed": len(failures), "tasks": sorted(results, key=lambda row: row["task_key"]),
        "failures": sorted(failures, key=lambda row: row["task_key"]), "credit_reconciliation": credit,
        "ambiguity_resolution": ambiguity, "duplicate_submit_policy": "TASK_FINGERPRINT_DURABLE_TRANSACTION_GUARD",
    }
    atomic_json(out, report)
    print(json.dumps({key: report[key] for key in ("status", "submitted", "precheck_pass", "failed")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


def exec_deployed_submitter() -> None:
    forwarded = list(sys.argv[1:])
    try:
        manifest_value = forwarded[forwarded.index("--manifest") + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("--manifest is required") from exc
    manifest_path = resolve(manifest_value)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.shot_media_admission_gate import compute_input_template_id, precheck_submission_inputs

    for task in manifest.get("tasks") or []:
        retry_failures = validate_submission_attempt(task)
        if retry_failures:
            raise RuntimeError(
                f"{task.get('task_key')} BLOCK_RETRY_CAP_GATE: "
                f"{','.join(retry_failures)}"
            )
        action_failures = validate_action_contract(task)
        if action_failures:
            raise RuntimeError(
                f"{task.get('task_key')} BLOCK_STRUCTURED_ACTION_CONTRACT_INVALID: "
                f"{','.join(action_failures)}"
            )
        expected_template_id = compute_input_template_id(task)
        if task.get("input_template_id") != expected_template_id:
            raise RuntimeError(f"{task.get('task_key')} missing or stale input_template_id")
        precheck = precheck_submission_inputs(task, enforce=True, root=ROOT)
        if precheck.get("status") != "PASS":
            missing = [*(precheck.get("missing_characters") or []), *(precheck.get("missing_props") or [])]
            raise RuntimeError(
                f"{task.get('task_key')} input completeness failed: "
                f"{precheck.get('failure_code')} missing={','.join(missing)}"
            )
    deployed = authoritative_pipeline_tools_dir() / "submit_giggle_video_manifest_v2.py"
    if not deployed.is_file():
        raise RuntimeError("Deployed BacklotOS video submitter is unavailable")
    if "--project-root" not in forwarded:
        forwarded = ["--project-root", str(ROOT), *forwarded]
    os.execv(sys.executable, [sys.executable, str(deployed), *forwarded])


if __name__ == "__main__":
    exec_deployed_submitter()
