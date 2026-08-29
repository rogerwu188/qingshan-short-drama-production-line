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


INSUFFICIENT_CREDIT_TERMS = (
    "insufficient credit", "insufficient credits", "insufficient balance",
    "not enough credit", "not enough credits", "credit balance too low",
    "余额不足", "积分不足", "额度不足",
)


class ProviderInsufficientCreditsError(RuntimeError):
    """The provider rejected submission because the account cannot fund it."""

try:
    from giggle_api_client import _image_list, _request
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from video_model_adapter import require_paid_model_contract
    from retry_cap_gate import validate_submission_attempt
    from grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from grouped_transition_contract import validate_transition_sequence
    from grouped_performance_contract import validate_grouped_beat_contract
    from grouped_internal_continuity_contract import validate_internal_transition_sequence
    from video_prompt_compiler import (
        validate_model_prompt_for_model,
        validate_transition_prompt_for_model,
    )
except ModuleNotFoundError:
    from tools.giggle_api_client import _image_list, _request
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.video_model_adapter import require_paid_model_contract
    from tools.retry_cap_gate import validate_submission_attempt
    from tools.grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from tools.grouped_transition_contract import validate_transition_sequence
    from tools.grouped_performance_contract import validate_grouped_beat_contract
    from tools.grouped_internal_continuity_contract import validate_internal_transition_sequence
    from tools.video_prompt_compiler import (
        validate_model_prompt_for_model,
        validate_transition_prompt_for_model,
    )


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
    # Defense in depth: the project-owned map authority contains the current
    # asset paths and SHA bindings, so validate it before loading the deployed
    # BacklotOS gate. E42+ cannot opt out with an explicit false value.
    try:
        from tools.global_space_layout_gate import evaluate_batch as evaluate_complete_map_mode
    except ModuleNotFoundError:
        from global_space_layout_gate import evaluate_batch as evaluate_complete_map_mode
    map_report = evaluate_complete_map_mode(
        manifest.get("episode_global_space_map_ref"),
        manifest.get("tasks") or [],
        episode=manifest.get("episode"),
        required=manifest.get("global_space_map_gate_required"),
    )
    if map_report.get("status") not in {"PASS", "N_A"}:
        checks = sorted({str(row.get("check") or "UNKNOWN") for row in map_report.get("failures") or []})
        raise ValueError(f"Complete map mode gate failed: {','.join(checks)}")
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
    report["project_complete_map_mode"] = map_report
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


def provider_response_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(provider_response_text(item) for item in value.values()).casefold()
    if isinstance(value, list):
        return " ".join(provider_response_text(item) for item in value).casefold()
    return str(value or "").casefold()


def classify_no_task_id_response(response: dict[str, Any]) -> dict[str, str]:
    if any(term in provider_response_text(response) for term in INSUFFICIENT_CREDIT_TERMS):
        return {
            "state": "PROVIDER_INSUFFICIENT_CREDITS_BLOCKED",
            "failure_classification": "PROVIDER_INSUFFICIENT_CREDITS",
            "retry_guard": "DO_NOT_RESUBMIT_UNTIL_CREDITS_RESTORED_AND_LEDGER_RECONCILED",
        }
    return {
        "state": "PROVIDER_RESPONSE_NO_TASK_ID_PENDING_CLASSIFICATION",
        "failure_classification": "PROVIDER_RESPONSE_RECEIVED_NO_TASK_ID",
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_PROVIDER_RESPONSE_CLASSIFIED_AND_LEDGER_RECONCILED",
    }


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
        "incoming_transition_contract": (task.get("machine_contract") or {}).get("incoming_transition_contract")
        or task.get("incoming_transition_contract"),
        "outgoing_transition_contract": (task.get("machine_contract") or {}).get("outgoing_transition_contract")
        or task.get("outgoing_transition_contract"),
        "start_frame_semantic_contract": (task.get("machine_contract") or {}).get("start_frame_semantic_contract")
        or task.get("start_frame_semantic_contract"),
        "internal_transition_contracts": (task.get("machine_contract") or {}).get("internal_transition_contracts")
        or task.get("internal_transition_contracts")
        or [],
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


def validate_grouped_creative_task(task: dict[str, Any], prompt_text: str) -> None:
    if not task.get("semantic_video_unit"):
        return
    machine = task.get("machine_contract") or {}
    camera_plan = validate_camera_plan(
        machine.get("camera_plan") or task.get("camera_plan"), source_id=str(task.get("task_key"))
    )
    specs = machine.get("ordered_prompt_specs") or task.get("ordered_prompt_specs") or []
    if not specs:
        raise ValueError(f"{task.get('task_key')} grouped creative beat contracts are missing")
    for index, spec in enumerate(specs, start=1):
        validate_grouped_beat_contract(spec, source_id=f"{task.get('task_key')}:beat-{index}")
    internal_unit = {
        "unit_id": task.get("unit_id") or task.get("task_key"),
        "editorial_shot_ids": machine.get("editorial_shot_ids")
        or task.get("editorial_shot_ids")
        or [],
        "ordered_prompt_specs": specs,
        "internal_transition_contracts": machine.get("internal_transition_contracts")
        or task.get("internal_transition_contracts")
        or [],
    }
    task["internal_transition_contracts"] = validate_internal_transition_sequence(internal_unit)
    prompt_unit = grouped_sequence_unit(task)
    prompt_unit["model"] = task.get("model")
    prompt_unit["duration_seconds"] = task.get("duration_seconds")
    prompt_unit["reference_images"] = [
        {"path": path, "role": role}
        for path, role in zip(
            task.get("reference_images") or [],
            task.get("reference_roles") or ["SEMANTIC_REFERENCE"] * len(task.get("reference_images") or []),
        )
    ]
    prompt_report = validate_model_prompt_for_model(
        prompt_text,
        model=task.get("model"),
        source_id=str(task.get("task_key")),
        unit=prompt_unit,
    )
    if prompt_report.get("status") != "PASS":
        raise ValueError(
            f"{task.get('task_key')} grouped complete prompt contract failed: "
            + ",".join(prompt_report.get("failures") or [])
        )
    semantic = machine.get("start_frame_semantic_contract") or task.get("start_frame_semantic_contract")
    if not isinstance(semantic, dict) or semantic.get("status") != "PASS":
        raise ValueError(f"{task.get('task_key')} start-frame semantic contract is missing or not PASS")
    transition_binding = validate_transition_prompt_for_model(
        prompt_text, grouped_sequence_unit(task), model=task.get("model")
    )
    if transition_binding["status"] != "PASS":
        raise ValueError(
            f"{task.get('task_key')} transition prompt binding failed: "
            + ",".join(transition_binding["failures"])
        )
    references = task.get("reference_images") or []
    reference_sha = task.get("reference_sha256") or []
    if not references or semantic.get("reference_path") != references[0]:
        raise ValueError(f"{task.get('task_key')} start-frame semantic path is not bound to first reference")
    if not reference_sha or semantic.get("reference_sha256") != reference_sha[0]:
        raise ValueError(f"{task.get('task_key')} start-frame semantic SHA is not bound to first reference")
    if semantic.get("camera_start_framing_match") is not True or semantic.get("space_match") is not True:
        raise ValueError(f"{task.get('task_key')} start-frame semantic checks are incomplete")
    task["camera_plan"] = camera_plan


def grouped_sequence_unit(task: dict[str, Any]) -> dict[str, Any]:
    machine = task.get("machine_contract") or {}
    return {
        "unit_id": task.get("unit_id") or task.get("task_key"),
        "scene_id": task.get("scene_id") or machine.get("scene_id"),
        "camera_plan": machine.get("camera_plan") or task.get("camera_plan"),
        "ordered_prompt_specs": machine.get("ordered_prompt_specs") or task.get("ordered_prompt_specs") or [],
        "editorial_shot_ids": machine.get("editorial_shot_ids") or task.get("editorial_shot_ids") or [],
        "internal_transition_contracts": machine.get("internal_transition_contracts")
        or task.get("internal_transition_contracts")
        or [],
        "transition_contract": machine.get("incoming_transition_contract")
        or task.get("incoming_transition_contract"),
        "incoming_transition_contract": machine.get("incoming_transition_contract")
        or task.get("incoming_transition_contract"),
        "outgoing_transition_contract": machine.get("outgoing_transition_contract")
        or task.get("outgoing_transition_contract"),
    }


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
    validate_grouped_creative_task(task, prompt_text)
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
    model = task.get("model")
    resolution = task.get("resolution")
    if model == "seedance-2.0-pro":
        if resolution != "720p":
            raise ValueError(
                f"{task['task_key']} must use Giggle SD2 multi-reference provider-native 720p; "
                "higher release rasters require a separate upscale stage"
            )
        minimum_duration = 4
    elif model == "MiniMax-H3":
        if resolution != "768p":
            raise ValueError(
                f"{task['task_key']} must use MiniMax-H3 provider-native 768p; "
                "1080p and 2K must not be represented as native H3 output"
            )
        if len(references) > 9:
            raise ValueError(f"{task['task_key']} MiniMax-H3 omni accepts at most 9 images")
        if audio_asset_ids:
            raise ValueError(f"{task['task_key']} MiniMax-H3 audio/video references require public HTTPS URLs")
        minimum_duration = 3
    else:
        raise ValueError(f"{task['task_key']} has no deployed prompt/submission adapter for model {model}")
    if not minimum_duration <= int(task.get("duration_seconds", 0)) <= 15:
        raise ValueError(f"{task['task_key']} duration outside {minimum_duration}-15 seconds")
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
        classification = classify_no_task_id_response(response)
        intent.update({
            "response_received_at": utc_now(),
            "error": "response missing task_id",
            "provider_response": response,
            "provider_response_sha256": response_sha256,
            **classification,
        })
        atomic_json(transaction, intent)
        if classification["failure_classification"] == "PROVIDER_INSUFFICIENT_CREDITS":
            raise ProviderInsufficientCreditsError(
                f"provider insufficient credits: {json.dumps(response, ensure_ascii=False)}"
            )
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
    grouped_camera_units = []
    for task in tasks:
        validate_task(task)
        if task.get("semantic_video_unit"):
            grouped_camera_units.append(grouped_sequence_unit(task))
    if not manifest.get("partial_repair_scope"):
        validate_camera_sequence(grouped_camera_units)
    # A scoped repair batch may contain non-adjacent units from the full
    # episode.  Each unit still validates its own inbound/outbound prompt
    # binding above, but the subset must not be mistaken for a new contiguous
    # episode whose first/last units have no external neighbors.
    if not manifest.get("partial_repair_scope"):
        validate_transition_sequence(grouped_camera_units, require_prompt_specs=True)
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
        concurrency = max(1, args.concurrency)
        credit_fuse_tripped = False
        for offset in range(0, len(tasks), concurrency):
            wave = tasks[offset:offset + concurrency]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(submit_one, task, receipts, transactions): task for task in wave}
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        results.append(future.result())
                    except ProviderInsufficientCreditsError as exc:
                        credit_fuse_tripped = True
                        failures.append({"task_key": task["task_key"], "state": "provider_insufficient_credits", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
                    except (Exception, SystemExit) as exc:
                        failures.append({"task_key": task["task_key"], "state": "submit_failed", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
            if credit_fuse_tripped:
                for task in tasks[offset + len(wave):]:
                    failures.append({
                        "task_key": task["task_key"],
                        "state": "not_submitted_provider_insufficient_credits",
                        "error": "batch dispatch stopped after provider insufficient-credits response",
                        "transaction": portable(transaction_path(transactions, task)),
                    })
                break
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

    grouped_camera_units = []
    for task in manifest.get("tasks") or []:
        validate_task(task)
        if task.get("semantic_video_unit"):
            grouped_camera_units.append(grouped_sequence_unit(task))
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
    if not manifest.get("partial_repair_scope"):
        validate_camera_sequence(grouped_camera_units)
    if not manifest.get("partial_repair_scope"):
        validate_transition_sequence(grouped_camera_units, require_prompt_specs=True)
    deployed = authoritative_pipeline_tools_dir() / "submit_giggle_video_manifest_v2.py"
    if not deployed.is_file():
        raise RuntimeError("Deployed BacklotOS video submitter is unavailable")
    if "--project-root" not in forwarded:
        forwarded = ["--project-root", str(ROOT), *forwarded]
    os.execv(sys.executable, [sys.executable, str(deployed), *forwarded])


if __name__ == "__main__":
    exec_deployed_submitter()
