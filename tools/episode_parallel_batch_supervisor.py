#!/usr/bin/env python3
"""Run all ready video-tool tasks for one episode concurrently.

Each task owns its remote id, output, QA evidence, and retry counter. Completed
candidates are never replayed unchanged; failed-only repairs require changed
generation inputs while sibling tasks continue to run.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

try:
    from giggle_api_client import generate_video, query_task
    from giggle_credit_statements import (
        fetch_pay_statements,
        fetch_task_credit_net_by_task_id,
        fetch_video_credit_by_task_id,
        parse_utc,
        reconcile_rows,
    )
    from episode_video_generation_guard import (
        credit_report_path,
        evaluate_episode_credit_gate,
        evaluate_episode_submission_authority,
        find_existing_paid_candidate,
        generation_fingerprint,
    )
    from scene_authority_lock import evaluate_batch
    from multimodal_character_binding_guard import (
        evaluate_batch as evaluate_multimodal_character_bindings,
        evaluate_task as evaluate_multimodal_character_task,
    )
    from shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
    from generation_first_pass_policy_gate import evaluate as evaluate_generation_first_pass_policy
    from shot_duration_policy import validate_duration_task
    from shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera_constraints
    from dramatic_quality_gate import evaluate as evaluate_dramatic_quality
    from mechanical_default_gate import evaluate as evaluate_mechanical_defaults
    from video_unit_anchor_count_gate import evaluate as evaluate_anchor_counts
    from video_unit_grouping_gate import (
        evaluate as evaluate_video_unit_grouping,
        validate_task_bindings as validate_video_unit_grouping_bindings,
    )
    from common_sense_causality_gate import evaluate as evaluate_common_sense_causality
    from action_shot_design_gate import (
        evaluate as evaluate_action_shot_design,
        validate_task_bindings as validate_action_shot_bindings,
        validate_tail_chained_submission,
    )
    from shot_media_admission_gate import (
        aggregate_template_defects,
        compute_input_template_id,
        evaluate_path as evaluate_shot_media_admission,
        precheck_submission_inputs,
        validate_retry_change,
    )
    from anachronism_lock_gate import evaluate as evaluate_anachronism_lock
    from cut_motivation_gate import evaluate as evaluate_cut_motivation
    from performance_unit_split_gate import evaluate as evaluate_performance_unit_split
    from gate_result_contract import write_gate_result
    from initial_asset_library import gate_library as gate_initial_asset_library
    from submit_giggle_task_manifest import ensure_giggle_api_key
    from supervisor_script_gate import verify_supervisor_script_gate
    from upload_giggle_asset import upload as upload_giggle_asset
    from image_dimensions import read_image_dimensions
    from media_binary import resolve_media_binary
except ModuleNotFoundError:  # Imported as tools.episode_parallel_batch_supervisor.
    from tools.giggle_api_client import generate_video, query_task
    from tools.giggle_credit_statements import (
        fetch_pay_statements,
        fetch_task_credit_net_by_task_id,
        fetch_video_credit_by_task_id,
        parse_utc,
        reconcile_rows,
    )
    from tools.episode_video_generation_guard import (
        credit_report_path,
        evaluate_episode_credit_gate,
        evaluate_episode_submission_authority,
        find_existing_paid_candidate,
        generation_fingerprint,
    )
    from tools.scene_authority_lock import evaluate_batch
    from tools.multimodal_character_binding_guard import (
        evaluate_batch as evaluate_multimodal_character_bindings,
        evaluate_task as evaluate_multimodal_character_task,
    )
    from tools.shot_prompt_professionalism_gate import evaluate_batch as evaluate_prompt_professionalism
    from tools.generation_first_pass_policy_gate import evaluate as evaluate_generation_first_pass_policy
    from tools.shot_duration_policy import validate_duration_task
    from tools.shot_space_camera_constraint_gate import evaluate_batch as evaluate_space_camera_constraints
    from tools.dramatic_quality_gate import evaluate as evaluate_dramatic_quality
    from tools.mechanical_default_gate import evaluate as evaluate_mechanical_defaults
    from tools.video_unit_anchor_count_gate import evaluate as evaluate_anchor_counts
    from tools.video_unit_grouping_gate import (
        evaluate as evaluate_video_unit_grouping,
        validate_task_bindings as validate_video_unit_grouping_bindings,
    )
    from tools.common_sense_causality_gate import evaluate as evaluate_common_sense_causality
    from tools.action_shot_design_gate import (
        evaluate as evaluate_action_shot_design,
        validate_task_bindings as validate_action_shot_bindings,
        validate_tail_chained_submission,
    )
    from tools.shot_media_admission_gate import (
        aggregate_template_defects,
        compute_input_template_id,
        evaluate_path as evaluate_shot_media_admission,
        precheck_submission_inputs,
        validate_retry_change,
    )
    from tools.anachronism_lock_gate import evaluate as evaluate_anachronism_lock
    from tools.cut_motivation_gate import evaluate as evaluate_cut_motivation
    from tools.performance_unit_split_gate import evaluate as evaluate_performance_unit_split
    from tools.gate_result_contract import write_gate_result
    from tools.initial_asset_library import gate_library as gate_initial_asset_library
    from tools.submit_giggle_task_manifest import ensure_giggle_api_key
    from tools.supervisor_script_gate import verify_supervisor_script_gate
    from tools.upload_giggle_asset import upload as upload_giggle_asset
    from tools.image_dimensions import read_image_dimensions
    from tools.media_binary import resolve_media_binary


ROOT = Path(__file__).resolve().parents[1]
SEEDANCE_REFERENCE_IMAGE_MAX_BYTES = 30 * 1024 * 1024
COMPACT_MODEL_PROMPT_POLICY = "qingshan.seedance_model_prompt_compact.v1"
SEEDANCE_REFERENCE_IMAGE_MIN_SHORT_EDGE = 512
TERMINAL_TASK_STATES = {
    "qa_pass",
    "technical_pass_content_unreviewed",
    "admitted_for_assembly",
    "image_pass",
    "qa_failed_terminal",
    "remote_failed_terminal",
    "submit_failed_terminal",
    "tool_pass",
    "tool_failed_terminal",
    "tool_blocked",
    "complete",
}
SUCCESS_TASK_STATES = {"qa_pass", "admitted_for_assembly", "image_pass", "tool_pass", "complete"}
CREDIT_KEYS = {
    "credit",
    "credits",
    "credit_cost",
    "credits_cost",
    "cost_credit",
    "cost_credits",
    "consumed_credit",
    "consumed_credits",
    "credit_consumed",
    "credits_consumed",
    "credit_amount",
    "credits_amount",
    "credit_count",
    "credits_count",
    "credit_used",
    "credits_used",
    "used_credit",
    "used_credits",
    "consume_credit",
    "consume_credits",
    "consumed_point",
    "consumed_points",
    "point_cost",
    "points_cost",
}
QA_RUNTIME_MODULES = ("cv2", "rapidocr_onnxruntime", "faster_whisper")


def resolve_qa_python() -> tuple[str | None, dict]:
    """Find one local Python that can run all source-video QA gates."""
    candidates = [
        os.environ.get("QINGSHAN_QA_PYTHON"),
        shutil.which("python3"),
        sys.executable,
    ]
    seen: set[str] = set()
    attempts = []
    import_probe = "; ".join(f"import {module}" for module in QA_RUNTIME_MODULES)
    for value in candidates:
        if not value:
            continue
        candidate = str(Path(value).expanduser().resolve())
        if candidate in seen:
            continue
        seen.add(candidate)
        completed = subprocess.run(
            [candidate, "-c", import_probe],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        attempt = {
            "python": candidate,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "returncode": completed.returncode,
            "required_modules": list(QA_RUNTIME_MODULES),
        }
        if completed.returncode:
            attempt["stderr"] = completed.stderr[-1000:]
        attempts.append(attempt)
        if completed.returncode == 0:
            return candidate, {
                "schema": "qingshan.source_video_qa_runtime.v1",
                "status": "PASS",
                "selected_python": candidate,
                "required_modules": list(QA_RUNTIME_MODULES),
                "attempts": attempts,
            }
    return None, {
        "schema": "qingshan.source_video_qa_runtime.v1",
        "status": "FAIL",
        "selected_python": None,
        "required_modules": list(QA_RUNTIME_MODULES),
        "attempts": attempts,
        "required_action": "Install cv2, rapidocr_onnxruntime and faster_whisper into one local Python or set QINGSHAN_QA_PYTHON before paid submission.",
    }
RELEASED_STATUS_PREFIXES = (
    "RELEASED",
    "PUBLISHED",
    "BOTH_PLATFORMS_PUBLIC",
    "GRANDFATHERED_PUBLIC",
)
try:
    from action_video_prompt_compiler import validate_action_contract
    from video_model_adapter import require_paid_model_contract
    from image_model_adapter import require_paid_image_model_contract
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.video_model_adapter import require_paid_model_contract
    from tools.image_model_adapter import require_paid_image_model_contract

RUNTIME_GATE_IDS = frozenset({
    "SCENE-AUTHORITY-LOCK",
    "SHOT-PROMPT-PROFESSIONALISM",
    "LOCAL-CLAUDE-SCRIPT-SUPERVISION",
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY",
    "MECHANICAL-DEFAULT-META-GATE",
    "VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT",
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
    "COMPLETE-VIDEO-PROMPT-MANIFEST",
    "EXACT-DIALOGUE-AUDIO-MANIFEST-COVERAGE",
    "SPEAKER-VOICE-GENDER-BINDING",
    "EDIT-CUT-MOTIVATION",
    "EDIT-VIEWING-CONSISTENCY",
    "SOURCE-VIDEO-NATIVE-DIALOGUE-ASR",
})
RUNTIME_GATE_BINDINGS = {
    "SCENE-AUTHORITY-LOCK": "evaluate_batch",
    "SHOT-PROMPT-PROFESSIONALISM": "evaluate_prompt_professionalism",
    "LOCAL-CLAUDE-SCRIPT-SUPERVISION": "validate_corrected_pipeline_quality",
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY": "validate_corrected_pipeline_quality",
    "MECHANICAL-DEFAULT-META-GATE": "validate_corrected_pipeline_quality",
    "VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT": "validate_corrected_pipeline_quality",
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL": "validate_corrected_pipeline_quality",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "validate_corrected_pipeline_quality",
    "PERIOD-ANACHRONISM-LOCK": "validate_corrected_pipeline_quality",
    "COMPLETE-VIDEO-PROMPT-MANIFEST": "validate_complete_video_prompt_manifest",
    "EXACT-DIALOGUE-AUDIO-MANIFEST-COVERAGE": "validate_dialogue_manifest_coverage",
    "SPEAKER-VOICE-GENDER-BINDING": "evaluate_multimodal_character_bindings",
    "EDIT-CUT-MOTIVATION": "evaluate_cut_motivation",
    "EDIT-VIEWING-CONSISTENCY": "evaluate_cut_motivation",
    "SOURCE-VIDEO-NATIVE-DIALOGUE-ASR": "run_qa",
}
assert frozenset(RUNTIME_GATE_BINDINGS) == RUNTIME_GATE_IDS


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def record_gate_result(episode: str, gate_id: str, result: dict, evidence: str | Path) -> Path:
    raw = str(result.get("status") or result.get("gate_status") or "FAIL").upper()
    if raw in {"NOT_APPLICABLE", "N_A"}:
        status = "N_A"
    else:
        status = "PASS" if raw.startswith("PASS") else "FAIL"
    return write_gate_result(
        episode,
        gate_id,
        invoked=True,
        status=status,
        runner="tools/episode_parallel_batch_supervisor.py",
        evidence=evidence,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_blocked_receipt(path: Path, payload: dict) -> None:
    """Record a preflight block without destroying harvested task evidence."""
    existing: dict = {}
    if path.is_file():
        try:
            existing = read_json(path)
        except (OSError, json.JSONDecodeError):
            existing = {}
    merged = dict(existing)
    if existing:
        merged["status_before_preflight_block"] = existing.get("status")
    merged.update(payload)
    atomic_json(path, merged)


def validate_script_readiness(config: dict) -> tuple[bool, str | None, dict | None, list[dict]]:
    """Require an explicit PASS report when a batch declares a script gate."""
    report_ref = config.get("script_readiness_report")
    if not report_ref:
        return True, None, None, []
    report_path = abs_path(report_ref)
    if not report_path.is_file():
        return False, str(report_path), None, [{"check": "script_readiness_report_exists", "path": str(report_path)}]
    try:
        report = read_json(report_path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, str(report_path), None, [{"check": "script_readiness_report_load", "error": str(exc)}]
    status = str(report.get("status") or "").upper()
    if status != "PASS":
        return False, str(report_path), report, [{"check": "script_readiness_status", "expected": "PASS", "actual": status or "MISSING"}]
    return True, str(report_path), report, []


def validate_writer_agent_provenance(config: dict) -> tuple[bool, list[dict]]:
    """E27+ generation must bind the exact selected script and compiled manifest."""
    match = re.search(r"(\d+)", str(config.get("episode") or ""))
    episode_number = int(match.group(1)) if match else 0
    media_tasks = [
        task for task in config.get("tasks", [])
        if task.get("tool_type") in {"image_generation", "video_generation"}
    ]
    if episode_number < 27 or not media_tasks:
        return True, []

    provenance = config.get("writer_agent_provenance") or {}
    failures: list[dict] = []
    if provenance.get("status") != "PASS":
        failures.append({"check": "writer_agent_provenance_status", "expected": "PASS", "actual": provenance.get("status") or "MISSING"})
    if provenance.get("provenance_type") == "claude_writer_script":
        for name in ("source_script", "production_manifest"):
            path_value = provenance.get(name)
            expected_sha = provenance.get(f"{name}_sha256")
            if not path_value or not expected_sha:
                failures.append({"check": f"{name}_binding", "error": "path_or_sha_missing"})
                continue
            path = abs_path(path_value)
            if not path.is_file():
                failures.append({"check": f"{name}_exists", "path": str(path)})
                continue
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                failures.append({"check": f"{name}_sha256", "expected": expected_sha, "actual": actual_sha})
        return not failures, failures
    version = str(provenance.get("agent_version") or "")
    try:
        version_parts = tuple(int(part) for part in version.split(".")[:3])
    except ValueError:
        version_parts = ()
    if version_parts < (0, 3, 0):
        failures.append({"check": "writer_agent_version", "minimum": "0.3.0", "actual": version or "MISSING"})
    schema_version = str(provenance.get("schema_version") or "")
    try:
        schema_parts = tuple(int(part) for part in schema_version.split(".")[:3])
    except ValueError:
        schema_parts = ()
    if schema_parts < (1, 2, 0):
        failures.append({"check": "writer_agent_schema_version", "minimum": "1.2.0", "actual": schema_version or "MISSING"})

    for name in ("generated_script", "compiled_script"):
        path_value = provenance.get(name)
        expected_sha = provenance.get(f"{name}_sha256")
        if not path_value or not expected_sha:
            failures.append({"check": f"{name}_binding", "error": "path_or_sha_missing"})
            continue
        path = abs_path(path_value)
        if not path.is_file():
            failures.append({"check": f"{name}_exists", "path": str(path)})
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            failures.append({"check": f"{name}_sha256", "expected": expected_sha, "actual": actual_sha})
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"check": f"{name}_json", "error": str(exc)})
            continue
        if str(payload.get("agent_version") or "") != version:
            failures.append({"check": f"{name}_agent_version", "expected": version, "actual": payload.get("agent_version")})
        if str(payload.get("schema_version") or "") != schema_version:
            failures.append({"check": f"{name}_schema_version", "expected": schema_version, "actual": payload.get("schema_version")})
    return not failures, failures


def validate_dialogue_manifest_coverage(config: dict) -> dict:
    """Bind every video unit to the authoritative episode dialogue manifest."""
    video_tasks = [task for task in config.get("tasks") or [] if task.get("tool_type") == "video_generation"]
    if not video_tasks:
        return {"status": "NOT_APPLICABLE", "failures": [], "results": []}

    manifest_ref = config.get("dialogue_manifest_ref")
    if not manifest_ref:
        return {
            "status": "FAIL",
            "failures": [{
                "check": "dialogue_manifest_ref",
                "error": "required_for_every_video_batch",
                "message": "A video batch may not infer dialogue from prompt text alone.",
            }],
            "results": [],
        }
    manifest_path = abs_path(manifest_ref)
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "dialogue_manifest_ref": str(manifest_path),
            "failures": [{"check": "dialogue_manifest_read", "error": str(exc)}],
            "results": [],
        }

    failures = []
    rows = manifest.get("rows")
    if manifest.get("status") != "PASS":
        failures.append({"check": "dialogue_manifest_status", "expected": "PASS", "actual": manifest.get("status")})
    if not isinstance(rows, list):
        failures.append({"check": "dialogue_manifest_rows", "error": "missing_or_not_list"})
        rows = []
    if str(manifest.get("episode") or "") != str(config.get("episode") or ""):
        failures.append({
            "check": "dialogue_manifest_episode",
            "expected": config.get("episode"),
            "actual": manifest.get("episode"),
        })

    rows_by_unit: dict[str, list[dict]] = {}
    for row in rows:
        rows_by_unit.setdefault(str(row.get("video_unit_id") or ""), []).append(row)

    registry_path = abs_path(
        config.get("voice_registry_ref")
        or "configs/series_voice_reference_registry_current_20260723.json"
    )
    try:
        registry_payload = read_json(registry_path)
        voice_registry = {
            str(row.get("entity_id") or ""): row
            for row in registry_payload.get("major_roles", [])
        }
    except (OSError, json.JSONDecodeError):
        voice_registry = {}

    results = []
    for task in video_tasks:
        unit_id = str(task.get("unit_id") or "")
        expected_rows = rows_by_unit.get(unit_id, [])
        expected_ids = [str(row.get("dia_id") or "") for row in expected_rows]
        actual_ids = [str(row.get("dia_id") or "") for row in task.get("dialogue") or []]
        task_failures = []
        if actual_ids != expected_ids:
            task_failures.append({
                "check": "dialogue_manifest_unit_coverage",
                "unit_id": unit_id,
                "expected": expected_ids,
                "actual": actual_ids,
                "error": "prompt_dialogue_must_exactly_match_manifest_order",
            })
        expected_native = bool(expected_ids)
        if task.get("native_dialogue_required") is not expected_native:
            task_failures.append({
                "check": "native_dialogue_required",
                "unit_id": unit_id,
                "expected": expected_native,
                "actual": task.get("native_dialogue_required"),
            })
        for row in expected_rows:
            if row.get("status") != "PASS":
                task_failures.append({
                    "check": "dialogue_manifest_line_status",
                    "dia_id": row.get("dia_id"),
                    "expected": "PASS",
                    "actual": row.get("status"),
                })
            mode = row.get("audio_mode")
            if mode == "EXACT_DIALOGUE_AUDIO_REFERENCE":
                continue
            if mode == "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY":
                rights_cleared_native = (
                    row.get("rights_cleared_model_native") is True
                    and row.get("external_voice_reference") is False
                    and row.get("unverified_clone_prohibited") is True
                    and not str(row.get("path") or "").strip()
                    and not str(row.get("remote_asset_id") or "").strip()
                )
                if rights_cleared_native:
                    continue
                task_failures.append({
                    "check": "dialogue_audio_reference_policy",
                    "dia_id": row.get("dia_id"),
                    "actual": mode,
                    "error": "rights_cleared_model_native_requires_no_external_voice_reference_or_clone",
                })
                continue
            if mode == "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION":
                scoped_native_exception = (
                    row.get("human_listening_exception") is True
                    and row.get("external_voice_reference") is False
                    and not str(row.get("path") or "").strip()
                    and not str(row.get("remote_asset_id") or "").strip()
                )
                if scoped_native_exception:
                    continue
                task_failures.append({
                    "check": "dialogue_audio_reference_policy",
                    "dia_id": row.get("dia_id"),
                    "actual": mode,
                    "error": "model_native_human_exception_requires_explicit_scope_and_no_external_reference",
                })
                continue
            voice = voice_registry.get(str(row.get("speaker_id") or ""))
            audio_path = abs_path(str(row.get("path") or ""))
            native_reference_valid = (
                mode == "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT"
                and voice is not None
                and voice.get("status") == "LOCKED_PRODUCTION_READY"
                and row.get("remote_asset_id") == voice.get("remote_asset_id")
                and audio_path.is_file()
                and hashlib.sha256(audio_path.read_bytes()).hexdigest() == row.get("sha256")
            )
            if not native_reference_valid:
                task_failures.append({
                    "check": "dialogue_audio_reference_policy",
                    "dia_id": row.get("dia_id"),
                    "actual": mode or "MISSING",
                    "error": "requires_exact_line_audio_or_registered_locked_native_voice_reference",
                })
        results.append({
            "task_key": task.get("task_key"),
            "unit_id": unit_id,
            "status": "PASS" if not task_failures else "FAIL",
            "expected_dialogue_ids": expected_ids,
            "actual_dialogue_ids": actual_ids,
            "failures": task_failures,
        })
        failures.extend(task_failures)
    return {
        "schema": "qingshan.video_dialogue_manifest_coverage_gate.v1",
        "episode": config.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "dialogue_manifest_ref": str(manifest_path),
        "results": results,
        "failures": failures,
        "policy": "Every scripted line must be present in manifest order and bind exact line audio, a registered locked native voice reference, or an explicitly rights-cleared model-native text-only voice with no external reference or clone.",
    }


def _normalized_scene_weather(value: object) -> str:
    aliases = {
        "interior_clear": "INTERIOR_CLEAR_NO_RAIN",
        "rain": "RAIN_NIGHT",
        "heavy_rain": "HEAVY_RAIN_EXTERIOR",
        "interior_rain_outside": "INTERIOR_RAIN_OUTSIDE_ONLY",
        "rain_stopped_cloud_break": "RAIN_STOPPED_CLOUD_BREAK",
    }
    text = str(value or "").strip()
    return aliases.get(text.lower(), text.upper())


def validate_complete_video_prompt_manifest(config: dict) -> dict:
    """Require complete episode prompt coverage and per-scene weather authority.

    E32+ video work may stream ready units independently, but only after every
    unit has one authoritative prompt in a complete manifest. The task being
    submitted must use the exact prompt SHA recorded by that manifest.
    """
    video_tasks = [task for task in config.get("tasks") or [] if task.get("tool_type") == "video_generation"]
    match = re.search(r"(\d+)", str(config.get("episode") or ""))
    episode_number = int(match.group(1)) if match else 0
    if not video_tasks or episode_number < 32:
        return {"status": "NOT_APPLICABLE", "failures": [], "results": []}

    manifest_ref = config.get("complete_video_prompt_manifest_ref")
    if not manifest_ref:
        return {
            "status": "FAIL",
            "failures": [{
                "check": "complete_video_prompt_manifest_ref",
                "error": "required_for_e32plus_video_batches",
                "message": "Streaming submission is allowed only after the complete episode prompt set is compiled.",
            }],
            "results": [],
        }
    manifest_path = abs_path(manifest_ref)
    try:
        manifest = read_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "manifest_ref": str(manifest_path),
            "failures": [{"check": "complete_video_prompt_manifest_read", "error": str(exc)}],
            "results": [],
        }

    failures: list[dict] = []
    rows = manifest.get("rows")
    if not isinstance(rows, list):
        failures.append({"check": "complete_video_prompt_manifest_rows", "error": "missing_or_not_list"})
        rows = []
    if str(manifest.get("episode") or "") != str(config.get("episode") or ""):
        failures.append({
            "check": "complete_video_prompt_manifest_episode",
            "expected": config.get("episode"),
            "actual": manifest.get("episode"),
        })
    if manifest.get("all_units_have_prompt") is not True:
        failures.append({"check": "all_units_have_prompt", "expected": True, "actual": manifest.get("all_units_have_prompt")})
    if manifest.get("unit_count") != len(rows):
        failures.append({"check": "unit_count", "expected": len(rows), "actual": manifest.get("unit_count")})

    source_plan_path = abs_path(manifest.get("source_plan") or "")
    source_scene_path = abs_path(manifest.get("source_scene_authority") or config.get("scene_contract_ref") or "")
    expected_unit_ids: list[str] = []
    expected_weather_by_scene: dict[str, str] = {}
    for label, path, sha_key in (
        ("source_plan", source_plan_path, "source_plan_sha256"),
        ("source_scene_authority", source_scene_path, "source_scene_authority_sha256"),
    ):
        if not path.is_file():
            failures.append({"check": f"{label}_exists", "path": str(path)})
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        expected_sha = str(manifest.get(sha_key) or "")
        if not expected_sha or actual_sha != expected_sha:
            failures.append({"check": f"{label}_sha256", "expected": expected_sha or "MISSING", "actual": actual_sha})
    if source_plan_path.is_file():
        try:
            plan = read_json(source_plan_path)
            expected_unit_ids = [str(row.get("unit_id") or "") for row in plan.get("units", [])]
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"check": "source_plan_read", "error": str(exc)})
    if source_scene_path.is_file():
        try:
            scene_authority = read_json(source_scene_path)
            scene_state = scene_authority.get("scene_state", [])
            if isinstance(scene_state, dict):
                episode = str(config.get("episode") or "")
                expected_weather_by_scene = {
                    f"{episode}-CW-S{int(scene_key):02d}": _normalized_scene_weather(row.get("weather"))
                    for scene_key, row in scene_state.items()
                    if isinstance(row, dict) and str(scene_key).isdigit()
                }
            else:
                expected_weather_by_scene = {
                    str(row.get("scene_id") or ""): _normalized_scene_weather(row.get("weather"))
                    for row in scene_state
                    if isinstance(row, dict)
                }
        except (OSError, json.JSONDecodeError) as exc:
            failures.append({"check": "source_scene_authority_read", "error": str(exc)})

    row_ids = [str(row.get("unit_id") or "") for row in rows]
    if expected_unit_ids and row_ids != expected_unit_ids:
        failures.append({
            "check": "complete_unit_coverage_and_order",
            "expected": expected_unit_ids,
            "actual": row_ids,
        })
    if len(row_ids) != len(set(row_ids)):
        failures.append({"check": "unique_unit_ids", "actual": row_ids})

    rows_by_unit: dict[str, dict] = {}
    results: list[dict] = []
    for row in rows:
        unit_id = str(row.get("unit_id") or "")
        scene_id = str(row.get("scene_id") or "")
        row_failures: list[dict] = []
        prompt_path = abs_path(row.get("prompt_path") or "")
        expected_prompt_sha = str(row.get("prompt_sha256") or "")
        actual_prompt_sha = None
        if not prompt_path.is_file():
            row_failures.append({"check": "prompt_file_exists", "unit_id": unit_id, "path": str(prompt_path)})
        else:
            prompt_bytes = prompt_path.read_bytes()
            actual_prompt_sha = hashlib.sha256(prompt_bytes).hexdigest()
            if not expected_prompt_sha or actual_prompt_sha != expected_prompt_sha:
                row_failures.append({
                    "check": "prompt_sha256",
                    "unit_id": unit_id,
                    "expected": expected_prompt_sha or "MISSING",
                    "actual": actual_prompt_sha,
                })
            expected_weather = expected_weather_by_scene.get(scene_id)
            actual_weather = _normalized_scene_weather(row.get("weather"))
            if expected_weather and actual_weather != expected_weather:
                row_failures.append({
                    "check": "scene_weather_authority",
                    "unit_id": unit_id,
                    "scene_id": scene_id,
                    "expected": expected_weather,
                    "actual": actual_weather,
                })
            prompt_text = prompt_bytes.decode("utf-8", errors="replace")
            if expected_weather and f"【天气硬合同】weather={expected_weather}" not in prompt_text:
                row_failures.append({
                    "check": "prompt_weather_contract",
                    "unit_id": unit_id,
                    "expected_token": f"【天气硬合同】weather={expected_weather}",
                })
            prompt_contract = row.get("model_prompt_contract")
            if prompt_contract is not None:
                if not isinstance(prompt_contract, dict) or prompt_contract.get("policy") != COMPACT_MODEL_PROMPT_POLICY:
                    row_failures.append({
                        "check": "model_prompt_compact_policy",
                        "unit_id": unit_id,
                        "expected": COMPACT_MODEL_PROMPT_POLICY,
                        "actual": prompt_contract,
                    })
                else:
                    max_chars = int(prompt_contract.get("max_character_count") or 0)
                    if prompt_contract.get("status") != "PASS" or max_chars <= 0 or len(prompt_text) > max_chars:
                        row_failures.append({
                            "check": "model_prompt_compact_length",
                            "unit_id": unit_id,
                            "actual_characters": len(prompt_text),
                            "max_characters": max_chars,
                        })
                    if int(prompt_contract.get("character_count") or -1) != len(prompt_text):
                        row_failures.append({
                            "check": "model_prompt_compact_character_count",
                            "unit_id": unit_id,
                            "expected": prompt_contract.get("character_count"),
                            "actual": len(prompt_text),
                        })
                    leaked = [
                        str(token) for token in prompt_contract.get("forbidden_tokens") or []
                        if str(token) and str(token) in prompt_text
                    ]
                    if leaked:
                        row_failures.append({
                            "check": "model_prompt_machine_contract_leak",
                            "unit_id": unit_id,
                            "tokens": leaked,
                        })
        rows_by_unit[unit_id] = row
        failures.extend(row_failures)
        results.append({
            "unit_id": unit_id,
            "scene_id": scene_id,
            "status": "PASS" if not row_failures else "FAIL",
            "prompt_path": str(prompt_path),
            "prompt_sha256": actual_prompt_sha,
            "failures": row_failures,
        })

    for task in video_tasks:
        unit_id = str(task.get("unit_id") or "")
        row = rows_by_unit.get(unit_id)
        if row is None:
            failures.append({"check": "task_unit_in_complete_manifest", "unit_id": unit_id, "error": "missing"})
            continue
        task_prompt_path = abs_path(task.get("prompt_file") or "")
        task_prompt_sha = hashlib.sha256(task_prompt_path.read_bytes()).hexdigest() if task_prompt_path.is_file() else None
        if task_prompt_sha != row.get("prompt_sha256"):
            failures.append({
                "check": "task_prompt_matches_complete_manifest",
                "unit_id": unit_id,
                "expected": row.get("prompt_sha256"),
                "actual": task_prompt_sha or "MISSING",
                "task_prompt_file": str(task_prompt_path),
            })
        task_prompt_contract = task.get("model_prompt_contract")
        if task_prompt_contract is not None and task_prompt_contract != row.get("model_prompt_contract"):
            failures.append({
                "check": "task_model_prompt_contract_matches_complete_manifest",
                "unit_id": unit_id,
            })
        if task_prompt_contract is not None and task_prompt_path.is_file():
            task_prompt_text = task_prompt_path.read_text(encoding="utf-8")
            for dialogue in task.get("dialogue") or []:
                spoken_text = str(dialogue.get("spoken_text") or "").strip()
                if spoken_text and task_prompt_text.count(spoken_text) != 1:
                    failures.append({
                        "check": "model_prompt_exact_dialogue_once",
                        "unit_id": unit_id,
                        "dia_id": dialogue.get("dia_id"),
                        "spoken_text": spoken_text,
                        "actual_count": task_prompt_text.count(spoken_text),
                    })

    distinct_authority_weather = set(expected_weather_by_scene.values())
    distinct_manifest_weather = {_normalized_scene_weather(row.get("weather")) for row in rows}
    if len(distinct_authority_weather) > 1 and len(distinct_manifest_weather) == 1:
        failures.append({
            "check": "global_weather_template_forbidden",
            "authority_weather": sorted(distinct_authority_weather),
            "manifest_weather": sorted(distinct_manifest_weather),
        })

    return {
        "schema": "qingshan.complete_video_prompt_manifest_gate.v1",
        "episode": config.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "manifest_ref": str(manifest_path),
        "unit_count": len(rows),
        "results": results,
        "failures": failures,
        "policy": "Compile every unit first, then stream each ready unit; weather and prompt SHA are resolved per scene and may never come from a global template.",
    }


def validate_supervisor_script_gate(config: dict) -> dict:
    """Run an explicitly requested supervisor audit without making it a default gate."""
    match = re.search(r"(\d+)", str(config.get("episode") or ""))
    episode_number = int(match.group(1)) if match else 0
    if (
        episode_number < 28
        or not config.get("tasks")
        or config.get("supervisor_script_gate_required") is not True
    ):
        return {"status": "PASS", "generation_allowed": True, "failures": []}
    provenance = config.get("writer_agent_provenance") or {}
    return verify_supervisor_script_gate(
        config.get("episode"),
        provenance.get("generated_script"),
        provenance.get("compiled_script"),
        config.get("supervisor_script_gate_report"),
    )


def validate_entity_reference_task(task: dict) -> list[dict]:
    """Validate reference-sequence and continuous-performance generation inputs."""
    if task.get("generation_mode") not in {"entity_reference_sequence", "performance_generation"}:
        return []
    failures: list[dict] = []
    for key in ("batch_id", "unit_id"):
        if not task.get(key):
            failures.append({"check": key, "error": "missing"})

    sequence = task.get("reference_video_sequence") or {}
    sequence_segments = list(sequence.get("segments") or [])
    minimum = int(task.get("action_reference_minimum", 1 if sequence_segments else 2))
    videos = list(task.get("reference_videos") or [])
    video_only = task.get("reference_video_only_authorized") is True
    still_sequence_only = task.get("still_sequence_only_allowed") is True
    if video_only:
        if not videos:
            failures.append({"check": "reference_video_only", "error": "reference_videos_missing"})
        if not str(task.get("reference_video_plan_reason") or "").strip():
            failures.append({"check": "reference_video_only", "error": "plan_reason_missing"})
    elif sequence_segments:
        if len(sequence_segments) < 2:
            failures.append({"check": "temporal_sequence_segments", "minimum": 2, "actual": len(sequence_segments)})
        if minimum < 1:
            failures.append({"check": "action_reference_minimum", "minimum": 1, "actual": minimum})
    elif not still_sequence_only and minimum < 2:
        failures.append({"check": "action_reference_minimum", "minimum": 2, "actual": minimum})
    if not video_only and not still_sequence_only and len(videos) < minimum:
        failures.append({
            "check": "temporal_action_references",
            "minimum": minimum,
            "actual": len(videos),
            "error": "single_still_fallback_forbidden",
        })
    images = list(task.get("reference_images") or [])
    if len(images) > 9:
        failures.append({"check": "seedance_reference_image_count", "maximum": 9, "actual": len(images)})
    for value in images:
        path = abs_path(value)
        if not path.is_file():
            failures.append({"check": "seedance_reference_image_transport", "path": str(path), "error": "missing"})
            continue
        if path.stat().st_size >= SEEDANCE_REFERENCE_IMAGE_MAX_BYTES:
            failures.append({
                "check": "seedance_reference_image_transport",
                "path": str(path),
                "error": "file_size_at_or_above_30mb",
                "bytes": path.stat().st_size,
            })
            continue
        try:
            width, height = read_image_dimensions(path)
        except (OSError, ValueError) as exc:
            failures.append({"check": "seedance_reference_image_transport", "path": str(path), "error": f"decode_failed:{exc}"})
            continue
        if min(width, height) < SEEDANCE_REFERENCE_IMAGE_MIN_SHORT_EDGE:
            failures.append({
                "check": "seedance_reference_image_transport",
                "path": str(path),
                "error": "short_edge_below_verified_provider_floor",
                "minimum_short_edge": SEEDANCE_REFERENCE_IMAGE_MIN_SHORT_EDGE,
                "actual": [width, height],
                "required_repair": "Use a SHA-bound RGB transport derivative; preserve the canonical source as identity authority.",
            })
    image_sequence = list(task.get("reference_image_sequence") or [])
    non_temporal_role_markers = (
        "IDENTITY",
        "CHARACTER_REFERENCE",
        "STYLE_REFERENCE",
        "SCENE_REFERENCE",
        "REFERENCE_ONLY",
    )
    temporal_image_sequence = [
        row
        for row in image_sequence
        if not any(marker in str(row.get("role") or "").upper() for marker in non_temporal_role_markers)
    ]
    performance_generation = task.get("generation_mode") == "performance_generation"
    planned_image_states = task.get("planned_reference_image_count")
    valid_image_plan = (
        isinstance(planned_image_states, int)
        and not isinstance(planned_image_states, bool)
        and (planned_image_states >= 1 or (video_only and planned_image_states == 0))
    )
    if not valid_image_plan:
        failures.append({
            "check": "dynamic_anchor_plan",
            "error": "planned_reference_image_count_required_for_every_video_unit",
        })
        minimum_image_states = 10**9
    else:
        minimum_image_states = planned_image_states
    legacy_minimum = task.get("state_reference_minimum")
    if legacy_minimum is not None and legacy_minimum != minimum_image_states:
        failures.append({
            "check": "dynamic_anchor_plan",
            "error": "state_reference_minimum_conflicts_with_planned_reference_image_count",
            "legacy": legacy_minimum,
            "planned": planned_image_states,
        })
    temporal_image_count = len(temporal_image_sequence) if image_sequence else len(images)
    temporal_paths = {
        abs_path(str(row.get("path") or "")).resolve()
        for row in temporal_image_sequence
        if str(row.get("path") or "").strip()
    }
    forwarded_image_paths = {abs_path(value).resolve() for value in images}
    missing_temporal_paths = sorted(str(path) for path in temporal_paths - forwarded_image_paths)
    if not video_only and temporal_image_count < minimum_image_states:
        failures.append({
            "check": "temporal_image_states",
            "minimum": minimum_image_states,
            "actual": temporal_image_count,
            "error": "one_still_per_video_unit_forbidden",
        })
    if not video_only and len(temporal_image_sequence) < minimum_image_states:
        failures.append({
            "check": "reference_image_sequence",
            "minimum": minimum_image_states,
            "actual": len(temporal_image_sequence),
            "error": "ordered_state_anchors_required",
        })
    if not video_only and missing_temporal_paths:
        failures.append({
            "check": "temporal_image_forwarding",
            "missing": missing_temporal_paths,
        })
    if isinstance(planned_image_states, int) and temporal_image_count != planned_image_states:
        failures.append({
            "check": "dynamic_anchor_count",
            "planned": planned_image_states,
            "actual": temporal_image_count,
            "error": "actual_anchor_count_must_match_action_design",
        })
    if performance_generation:
        spec = task.get("performance_spec") or {}
        beats = list(spec.get("motion_beats") or [])
        required_motion_fields = {
            "subject",
            "action",
            "contact_point",
            "direction",
            "end_state",
            "intent",
            "visible_causality",
            "expression",
            "viewer_read",
        }
        if not beats:
            failures.append({"check": "performance_motion_spec", "error": "missing"})
        for index, beat in enumerate(beats, 1):
            missing = sorted(field for field in required_motion_fields if not str(beat.get(field) or "").strip())
            if missing:
                failures.append({"check": "performance_motion_beat", "index": index, "missing": missing})
        ownership = spec.get("prop_ownership") or {}
        if not isinstance(ownership, dict):
            failures.append({"check": "performance_prop_ownership", "error": "must_be_structured_object"})
        elif not ownership or any(not str(value or "").strip() for value in ownership.values()):
            failures.append({"check": "performance_prop_ownership", "error": "missing_or_empty"})
        interpolation = task.get("keyframe_interpolation_gate") or {}
        if interpolation.get("status") != "PASS":
            failures.append({"check": "keyframe_interpolation_gate", "status": interpolation.get("status") or "missing"})
        required_interpolation_pairs = max(0, len(temporal_image_sequence) - 1)
        if required_interpolation_pairs and int(interpolation.get("checked_adjacent_pairs", -1)) != required_interpolation_pairs:
            failures.append({
                "check": "keyframe_interpolation_pair_coverage",
                "required": required_interpolation_pairs,
                "actual": interpolation.get("checked_adjacent_pairs"),
            })
    if (
        task.get("audio_reference_optional") is not True
        and not (task.get("reference_audios") or task.get("reference_audio_asset_ids"))
    ):
        failures.append({"check": "audio_references", "error": "missing"})

    if task.get("native_dialogue_required") is True:
        dialogue = list(task.get("dialogue") or [])
        dialogue_assets = list(task.get("dialogue_audio_assets") or [])
        exact_audio_total = sum(
            float(asset.get("duration_seconds") or 0)
            for asset in dialogue_assets
            if asset.get("purpose") == "EXACT_TARGET_DIALOGUE_REFERENCE"
        )
        if exact_audio_total > 15.0:
            failures.append({
                "check": "seedance_reference_audio_total_duration",
                "maximum_seconds": 15.0,
                "actual_seconds": round(exact_audio_total, 6),
                "error": "split_at_natural_dialogue_boundary_before_submission",
            })
        required_ids = [str(row.get("dia_id") or "") for row in dialogue]
        bound_ids = [str(row.get("dia_id") or "") for row in dialogue_assets]
        model_native_ids = [str(value) for value in task.get("model_native_text_only_dialogue_ids") or []]
        if not required_ids or len(required_ids) != len(set(required_ids)):
            failures.append({"check": "dialogue_audio_required_ids", "error": "missing_or_duplicate"})
        if bound_ids != required_ids and model_native_ids != required_ids:
            failures.append({
                "check": "dialogue_audio_coverage",
                "required": required_ids,
                "bound": bound_ids,
                "error": "every_dialogue_id_requires_one_ordered_exact_audio_reference",
            })
        reference_audios = {str(value) for value in task.get("reference_audios") or []}
        reference_audio_asset_ids = {str(value) for value in task.get("reference_audio_asset_ids") or []}
        for asset in dialogue_assets:
            path_value = str(asset.get("path") or "")
            expected_sha = str(asset.get("sha256") or "")
            purpose = asset.get("purpose")
            if purpose not in {
                "EXACT_TARGET_DIALOGUE_REFERENCE",
                "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT",
            }:
                failures.append({"check": "dialogue_audio_purpose", "dia_id": asset.get("dia_id")})
                continue
            remote_asset_id = str(asset.get("remote_asset_id") or "")
            direct_locked_reference = (
                purpose == "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT"
                and remote_asset_id
                and remote_asset_id in reference_audio_asset_ids
            )
            if path_value not in reference_audios and not direct_locked_reference:
                failures.append({"check": "dialogue_audio_forwarding", "dia_id": asset.get("dia_id"), "path": path_value})
                continue
            path = abs_path(path_value)
            if not path.is_file():
                failures.append({"check": "dialogue_audio_exists", "dia_id": asset.get("dia_id"), "path": str(path)})
                continue
            actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if not expected_sha or expected_sha != actual_sha:
                failures.append({
                    "check": "dialogue_audio_sha256",
                    "dia_id": asset.get("dia_id"),
                    "expected": expected_sha,
                    "actual": actual_sha,
                })

    assets = task.get("reference_assets") or []
    required_slots = set(task.get("required_slot_ids") or [])
    bound_slots = {str(asset.get("slot_id")) for asset in assets if asset.get("slot_id")}
    missing_slots = sorted(required_slots - bound_slots)
    if missing_slots:
        failures.append({"check": "required_asset_slots", "missing": missing_slots})

    for asset in assets:
        path_value = asset.get("path")
        expected_sha = asset.get("sha256")
        if not path_value or not expected_sha:
            failures.append({"check": "reference_asset_binding", "slot_id": asset.get("slot_id"), "error": "path_or_sha_missing"})
            continue
        path = abs_path(path_value)
        if not path.is_file():
            failures.append({"check": "reference_asset_exists", "slot_id": asset.get("slot_id"), "path": str(path)})
            continue
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            failures.append({
                "check": "reference_asset_sha256",
                "slot_id": asset.get("slot_id"),
                "expected": expected_sha,
                "actual": actual_sha,
            })
    return failures


def clear_resolved_scene_block(receipt: dict, scene_contract_ref: str | None, scene_gate_path: Path) -> None:
    """Replace stale scene-lock failure evidence after the authoritative gate passes."""
    if receipt.get("status") == "BLOCKED_SCENE_AUTHORITY_LOCK":
        for stale_key in ("failures", "rollback", "recorded_at"):
            receipt.pop(stale_key, None)
    receipt["scene_contract_ref"] = scene_contract_ref
    receipt["scene_authority_report"] = str(scene_gate_path)


def episode_has_release_record(episode: str | None, root: Path = ROOT) -> bool:
    """Released episodes cannot occupy a live production slot."""
    if not episode:
        return False
    release_dir = root / "workflow" / "release" / episode.lower()
    for path in release_dir.glob("*.json") if release_dir.is_dir() else ():
        try:
            payload = read_json(path)
            status = str(payload.get("status") or "").upper()
        except (OSError, json.JSONDecodeError):
            continue
        if status.startswith(RELEASED_STATUS_PREFIXES):
            return True
        youtube = str((payload.get("youtube") or {}).get("status") or "").upper()
        douyin = str((payload.get("douyin") or {}).get("status") or "").upper()
        if youtube.startswith("PUBLIC") and douyin.startswith("PUBLIC"):
            return True
    return False


def safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "task"


def abs_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def validate_corrected_pipeline_quality(config: dict) -> dict:
    episode_match = re.match(r"E(\d+)(?:\D|$)", str(config.get("episode") or "").upper())
    episode_number = int(episode_match.group(1)) if episode_match else 0
    required = episode_number >= 28 or config.get("effective_ruleset") == "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1"
    if not required:
        return {"status": "NOT_APPLICABLE", "required": False, "failures": []}
    failures: list[str] = []
    ready_tasks = [task for task in config.get("tasks") or [] if task_config_is_ready(task)]
    failures.extend(
        f"corrected_pipeline_tail_chain_submission:{value}"
        for value in validate_tail_chained_submission(ready_tasks, ROOT)
    )
    reports: dict[str, dict] = {}
    for key, evaluator in (
        ("dramatic_quality_report_ref", evaluate_dramatic_quality),
        ("mechanical_default_plan_ref", evaluate_mechanical_defaults),
        ("video_unit_grouping_plan_ref", evaluate_video_unit_grouping),
        ("anchor_count_plan_ref", evaluate_anchor_counts),
        ("common_sense_causality_plan_ref", evaluate_common_sense_causality),
        ("action_shot_design_plan_ref", evaluate_action_shot_design),
        ("period_lock_plan_ref", evaluate_anachronism_lock),
    ):
        value = config.get(key)
        if not value:
            failures.append(f"corrected_pipeline_report_missing:{key}")
            continue
        path = abs_path(value)
        if not path.is_file():
            failures.append(f"corrected_pipeline_report_not_found:{key}:{path}")
            continue
        result = evaluator(read_json(path))
        reports[key] = {"path": str(path), "result": result}
        if result.get("status") != "PASS":
            failures.append(f"corrected_pipeline_gate_failed:{key}")
        if key == "action_shot_design_plan_ref" and result.get("status") == "PASS":
            plan = read_json(path)
            failures.extend(
                f"corrected_pipeline_action_prompt_binding:{value}"
                for value in validate_action_shot_bindings(plan, config.get("tasks") or [], ROOT)
            )
        if key == "video_unit_grouping_plan_ref" and result.get("status") == "PASS":
            plan = read_json(path)
            failures.extend(
                f"corrected_pipeline_video_unit_grouping_binding:{value}"
                for value in validate_video_unit_grouping_bindings(plan, ready_tasks)
            )
        if key == "anchor_count_plan_ref" and result.get("status") == "PASS":
            planned_by_unit = {
                str(row.get("unit_id")): row.get("planned_reference_image_count")
                for row in result.get("decisions") or []
            }
            for task in config.get("tasks") or []:
                if task.get("tool_type", "video_generation") != "video_generation":
                    continue
                unit_id = str(task.get("unit_id") or "")
                planned = planned_by_unit.get(unit_id)
                task_planned = task.get("planned_reference_image_count")
                sequence = task.get("reference_image_sequence") or []
                temporal = [
                    row for row in sequence
                    if not any(
                        marker in str(row.get("role") or "").upper()
                        for marker in (
                            "IDENTITY",
                            "CHARACTER_REFERENCE",
                            "STYLE_REFERENCE",
                            "SCENE_REFERENCE",
                            "REFERENCE_ONLY",
                        )
                    )
                ]
                actual = len(temporal) if sequence else len(task.get("reference_images") or [])
                substitution = task.get("anchor_plan_transport_substitution") or {}
                substituted = (
                    task.get("reference_video_only_authorized") is True
                    and substitution.get("status") == "PASS"
                    and substitution.get("source_planned_reference_image_count") == planned
                    and task_planned == 0
                    and actual == 0
                    and bool(task.get("reference_videos"))
                )
                if planned is None:
                    failures.append(f"corrected_pipeline_anchor_unit_missing:{unit_id or 'UNKNOWN'}")
                elif not substituted and (task_planned != planned or actual != planned):
                    failures.append(
                        f"corrected_pipeline_anchor_binding_mismatch:{unit_id or 'UNKNOWN'}:"
                        f"plan={planned}:task={task_planned}:actual={actual}"
                    )
    return {
        "schema": "qingshan.corrected_pipeline_quality_preflight.v1",
        "episode": config.get("episode"),
        "required": True,
        "status": "PASS" if not failures else "FAIL",
        "reports": reports,
        "failures": failures,
    }


def validate_keyframe_admissions(config: dict) -> dict:
    """Require exact-SHA content-admitted start frames before E40+ video spend."""
    match = re.match(r"E(\d+)(?:\D|$)", str(config.get("episode") or "").upper())
    episode_number = int(match.group(1)) if match else 0
    failures: list[str] = []
    decisions: list[dict] = []
    if episode_number < 40:
        return {"status": "NOT_APPLICABLE", "required": False, "decisions": [], "failures": []}
    for task in config.get("tasks") or []:
        if task.get("tool_type", "video_generation") != "video_generation" or not task_config_is_ready(task):
            continue
        task_id = str(task.get("task_key") or task.get("source_id") or "UNKNOWN")
        value = task.get("start_frame_admission_ref")
        if not value:
            failures.append(f"{task_id}:start_frame_admission_ref_missing")
            continue
        path = abs_path(value)
        if not path.is_file():
            failures.append(f"{task_id}:start_frame_admission_not_found:{path}")
            continue
        try:
            result = evaluate_shot_media_admission(path, ROOT)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(f"{task_id}:start_frame_admission_unreadable:{type(exc).__name__}")
            continue
        decisions.append({"task_key": task_id, "path": str(path), "result": result})
        if result.get("status") not in {"ADMITTED", "ADMITTED_WITH_P2"}:
            failures.append(f"{task_id}:start_frame_not_admitted")
            continue
        admitted_path = Path(str(result.get("asset_path") or ""))
        references = task.get("reference_image_sequence") or []
        first = references[0] if references else {}
        task_reference = first.get("path") or ((task.get("reference_images") or [None])[0])
        if not task_reference or abs_path(task_reference).resolve() != admitted_path.resolve():
            failures.append(f"{task_id}:first_temporal_reference_is_not_admitted_start_frame")
        if first and first.get("role") not in {
            "ADMITTED_EXACT_START_FRAME",
            "EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME",
        }:
            failures.append(f"{task_id}:first_reference_role_not_admitted_start_frame")
        if str(task.get("start_frame_sha256") or "") != str(result.get("asset_sha256") or ""):
            failures.append(f"{task_id}:start_frame_sha256_not_bound_to_admission")
    return {
        "schema": "qingshan.keyframe_video_submit_admission.v1",
        "required": True,
        "status": "PASS" if not failures else "FAIL",
        "decisions": decisions,
        "failures": failures,
    }


def prepare_local_reference_assets(receipt: dict) -> None:
    """Register local image/audio/video once per SHA and bind remote asset IDs."""
    registry = receipt.setdefault("local_reference_asset_registry", {})
    needed: dict[str, dict] = {}
    for task in receipt.get("tasks", []):
        if task.get("state") in TERMINAL_TASK_STATES or task.get("state") == "waiting_dependencies":
            continue
        for media_type, field in (
            ("image", "reference_images"),
            ("audio", "reference_audios"),
            ("video", "reference_videos"),
        ):
            if media_type == "image" and task.get("tool_type") == "image_generation":
                # Image-to-image consumes local/base64 references directly.
                # Registering them as omni-video assets only adds latency.
                continue
            if media_type == "image" and task.get("reference_image_transport") in {"inline_base64", "direct_url"}:
                continue
            if media_type == "image":
                configured_ids = [str(value) for value in task.get("reference_image_asset_ids") or [] if str(value)]
                local_images = list(task.get("reference_images") or [])
                if local_images and len(configured_ids) == len(local_images):
                    continue
            for value in task.get(field, []):
                path = abs_path(value)
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                if sha not in registry:
                    needed.setdefault(sha, {"path": path, "media_type": media_type})

    if needed:
        with ThreadPoolExecutor(max_workers=min(8, len(needed))) as pool:
            futures = {
                pool.submit(upload_giggle_asset, item["path"], True): (sha, item)
                for sha, item in needed.items()
            }
            for future in as_completed(futures):
                sha, item = futures[future]
                try:
                    response = future.result()
                    data = response.get("data") or response
                    asset_id = data.get("asset_id")
                    if not asset_id:
                        raise RuntimeError(f"asset_id missing: {response}")
                    registry[sha] = {
                        "path": str(item["path"]),
                        "sha256": sha,
                        "media_type": item["media_type"],
                        "asset_id": str(asset_id),
                        "url": data.get("signed_url") or data.get("file_url"),
                        "registered_at": now(),
                        "generation_credit_scope": "NOT_APPLICABLE_ASSET_REGISTRATION",
                    }
                except Exception as exc:  # Preserve evidence; submit_one will block affected tasks.
                    registry[sha] = {
                        "path": str(item["path"]),
                        "sha256": sha,
                        "media_type": item["media_type"],
                        "error": str(exc),
                        "registered_at": now(),
                    }

    for task in receipt.get("tasks", []):
        if task.get("state") in TERMINAL_TASK_STATES or task.get("state") == "waiting_dependencies":
            continue
        failures = []
        for media_type, local_field, remote_field in (
            ("image", "reference_images", "resolved_reference_image_asset_ids"),
            ("audio", "reference_audios", "resolved_reference_audio_asset_ids"),
            ("video", "reference_videos", "resolved_reference_video_asset_ids"),
        ):
            if media_type == "image" and task.get("reference_image_transport") in {"inline_base64", "direct_url"}:
                task[remote_field] = []
                continue
            if media_type == "image":
                configured_ids = [str(value) for value in task.get("reference_image_asset_ids") or [] if str(value)]
                local_images = list(task.get("reference_images") or [])
                if local_images and len(configured_ids) == len(local_images):
                    task[remote_field] = []
                    continue
            resolved = []
            for value in task.get(local_field, []):
                path = abs_path(value)
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                entry = registry.get(sha) or {}
                if entry.get("asset_id"):
                    resolved.append(entry["asset_id"])
                else:
                    failures.append({"media_type": media_type, "path": str(path), "sha256": sha, "error": entry.get("error") or "not_registered"})
            task[remote_field] = resolved
        if failures:
            task["reference_asset_registration_failures"] = failures
        else:
            task.pop("reference_asset_registration_failures", None)


def extract_credit_observation(payload: object, path: str = "$") -> dict | None:
    """Return an explicit per-action credit value without inferring from task shape."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).strip().lower().replace("-", "_")
            current_path = f"{path}.{key}"
            if normalized in CREDIT_KEYS and not isinstance(value, bool):
                if isinstance(value, (int, float)):
                    return {"credits": value, "response_path": current_path}
                if isinstance(value, str):
                    try:
                        number = float(value)
                    except ValueError:
                        pass
                    else:
                        return {
                            "credits": int(number) if number.is_integer() else number,
                            "response_path": current_path,
                        }
            nested = extract_credit_observation(value, current_path)
            if nested:
                return nested
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            nested = extract_credit_observation(value, f"{path}[{index}]")
            if nested:
                return nested
    return None


def record_submit_credit_attempt(task: dict, result: dict) -> None:
    """Persist one immutable generation attempt, including zero-cost submit failures."""
    if task.get("tool_type") not in {"video_generation", "image_generation"}:
        return
    response = result.get("submit_response") or {}
    observed = extract_credit_observation(response)
    accepted = bool(result.get("task_id"))
    task.setdefault("credit_attempts", []).append(
        {
            "attempt": len(task.get("credit_attempts", [])) + 1,
            "task_id": result.get("task_id"),
            "tool_type": task.get("tool_type"),
            "submitted_at": now(),
            "returned_credit": observed.get("credits") if observed else None,
            "credit_response_path": observed.get("response_path") if observed else None,
            "charge_status": "PENDING_REMOTE_RESULT" if accepted else "FAILED_ZERO_CHARGE",
            "actual_charged_credits": None if accepted else 0,
            "success": None if accepted else False,
            "evidence": "submit_response" if response else "submit_process_failure",
            "generation_fingerprint": task.get("generation_fingerprint"),
        }
    )


def settle_credit_attempt(task: dict, remote_status: str, payload: dict) -> None:
    """Settle the matching attempt; failed remote generations never consume credit."""
    attempts = task.get("credit_attempts") or []
    attempt = next(
        (row for row in reversed(attempts) if row.get("task_id") == task.get("task_id")),
        attempts[-1] if attempts else None,
    )
    if not attempt and task.get("task_id"):
        attempt = {
            "attempt": 1,
            "task_id": task["task_id"],
            "tool_type": task.get("tool_type"),
            "submitted_at": task.get("submitted_at"),
            "returned_credit": None,
            "credit_response_path": None,
            "charge_status": "PENDING_REMOTE_RESULT",
            "actual_charged_credits": None,
            "success": None,
            "evidence": "legacy_or_adopted_task_credit_backfill",
            "generation_fingerprint": task.get("generation_fingerprint"),
        }
        task.setdefault("credit_attempts", []).append(attempt)
    if not attempt:
        return
    observed = extract_credit_observation(payload)
    if observed:
        attempt["returned_credit"] = observed["credits"]
        attempt["credit_response_path"] = observed["response_path"]
        attempt["evidence"] = "remote_query_response"
    if remote_status == "completed":
        attempt["success"] = True
        if attempt.get("returned_credit") is None:
            if task.get("tool_type") == "video_generation":
                try:
                    statement = fetch_video_credit_by_task_id(str(task.get("task_id") or ""))
                except BaseException as exc:
                    statement = {"status": "INCOMPLETE", "error": str(exc)}
            else:
                statement = {
                    "status": "PENDING_BATCH_RECONCILIATION",
                    "method": "IMAGE_BATCH_TIME_WINDOW_EXACT_COUNT",
                }
            attempt["credit_statement_reconciliation"] = statement
            if statement.get("status") == "PASS":
                attempt["returned_credit"] = statement["charged_credits"]
                attempt["credit_response_path"] = statement["endpoint"]
                attempt["charge_status"] = "EXACT_TASK_ID_STATEMENT_MATCH"
                attempt["actual_charged_credits"] = statement["charged_credits"]
                attempt["evidence"] = "credit_statement_project_id_equals_task_id"
            else:
                attempt["charge_status"] = "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING"
                attempt["actual_charged_credits"] = None
        else:
            attempt["charge_status"] = "SUCCESS_ACTUAL_CHARGE_RECORDED"
            attempt["actual_charged_credits"] = attempt["returned_credit"]
        attempt["settled_at"] = now()
    elif remote_status in {"failed", "error", "cancelled", "timeout"}:
        attempt["success"] = False
        if task.get("tool_type") == "video_generation" and task.get("task_id"):
            try:
                statement = fetch_task_credit_net_by_task_id(
                    str(task["task_id"]),
                    event_description="SingleGenerateVideo",
                )
            except BaseException as exc:
                statement = {"status": "INCOMPLETE", "error": str(exc)}
            attempt["credit_statement_reconciliation"] = statement
            if statement.get("status") == "PASS_ZERO_REFUNDED":
                attempt["charge_status"] = "FAILED_ZERO_NET_AFTER_REFUND"
                attempt["actual_charged_credits"] = 0
                attempt["evidence"] = "credit_statement_pay_minus_refund"
            else:
                attempt["charge_status"] = "FAILED_CREDIT_REFUND_EVIDENCE_INCOMPLETE"
                attempt["actual_charged_credits"] = None
        else:
            attempt["charge_status"] = "FAILED_ZERO_CHARGE"
            attempt["actual_charged_credits"] = 0
        attempt["settled_at"] = now()


def refresh_credit_summary(receipt: dict) -> None:
    attempts = [
        attempt
        for task in receipt.get("tasks", [])
        for attempt in task.get("credit_attempts", [])
    ]
    known = [
        row["actual_charged_credits"]
        for row in attempts
        if isinstance(row.get("actual_charged_credits"), (int, float))
    ]
    receipt["credit_summary"] = {
        "schema": "qingshan.remote_generation_credit_summary.v1",
        "attempt_count": len(attempts),
        "successful_attempt_count": sum(row.get("success") is True for row in attempts),
        "failed_zero_charge_count": sum(
            row.get("charge_status") in {"FAILED_ZERO_CHARGE", "FAILED_ZERO_NET_AFTER_REFUND"}
            for row in attempts
        ),
        "pending_attempt_count": sum(row.get("charge_status") == "PENDING_REMOTE_RESULT" for row in attempts),
        "successful_unknown_credit_count": sum(
            row.get("charge_status") == "SUCCESS_CREDIT_UNKNOWN_API_FIELD_MISSING" for row in attempts
        ),
        "actual_charged_credits_known_total": sum(known),
        "actual_total_complete": all(
            row.get("actual_charged_credits") is not None for row in attempts
        ),
        "policy": "Record explicit API credit values only; failed attempts are zero; never estimate missing successful credits.",
        "updated_at": now(),
    }


def refresh_episode_video_credit_gate(receipt: dict) -> dict:
    gate = evaluate_episode_credit_gate(receipt.get("episode", "UNKNOWN"), receipt)
    gate["recorded_at"] = now()
    report_path = credit_report_path(receipt.get("episode", "UNKNOWN"))
    atomic_json(report_path, gate)
    gate["report"] = str(report_path)
    receipt["episode_video_credit_gate"] = gate
    receipt["submission_gate_blocked"] = gate.get("status") != "PASS"
    return gate


def run_local_tool(task: dict, receipt: dict) -> dict:
    tool_type = task.get("tool_type")
    report = abs_path(task.get("report") or f"workflow/tasks/{safe(task['task_key'])}_tool_report.json")
    report.parent.mkdir(parents=True, exist_ok=True)
    if tool_type == "agentcut":
        project = abs_path(task["project"])
        cut_gate_report = report.with_name(f"{report.stem}_cut_motivation_gate.json")
        try:
            project_payload = read_json(project)
            metrics_ref = task.get("final_cut_metrics")
            metrics_payload = read_json(abs_path(metrics_ref)) if metrics_ref else None
            cut_gate_result = evaluate_cut_motivation(project_payload, metrics_payload)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            cut_gate_result = {
                "schema": "qingshan.cut_motivation_gate_result.v1",
                "gate_status": "INVALID",
                "release_allowed": False,
                "findings": [{"severity": "BLOCKER", "detail": f"cut_gate_input_error:{exc}"}],
            }
        cut_gate_result["episode"] = receipt.get("episode")
        cut_gate_result["project"] = str(project)
        cut_gate_result["invoked"] = True
        cut_gate_result["recorded_at"] = now()
        atomic_json(cut_gate_report, cut_gate_result)
        record_gate_result(receipt.get("episode", "UNKNOWN"), "EDIT-CUT-MOTIVATION", cut_gate_result, cut_gate_report)
        record_gate_result(receipt.get("episode", "UNKNOWN"), "EDIT-VIEWING-CONSISTENCY", cut_gate_result, cut_gate_report)
        if cut_gate_result.get("gate_status") != "PASS":
            payload = {
                "status": "BLOCKED_CUT_MOTIVATION_GATE",
                "tool_type": tool_type,
                "project": str(project),
                "cut_motivation_gate": str(cut_gate_report),
                "gate_status": cut_gate_result.get("gate_status"),
                "recorded_at": now(),
            }
            atomic_json(report, payload)
            return {"state": "tool_blocked", "tool_report": str(report), "tool_result": payload}
        command = [str(ROOT / "tools/run_agentcut.sh"), "validate", str(project)]
        if task.get("strict_media"):
            command.insert(-1, "--strict-media")
    elif tool_type == "ai_review":
        video = task.get("video")
        if not video and task.get("depends_on_task"):
            dependency = next((row for row in receipt.get("tasks", []) if row.get("task_key") == task["depends_on_task"]), None)
            video = dependency.get("output_path") if dependency else None
        if not video or not abs_path(video).is_file():
            payload = {"status": "BLOCKED_INPUT_NOT_READY", "tool_type": tool_type, "video": video, "recorded_at": now()}
            atomic_json(report, payload)
            return {"state": "tool_blocked", "tool_report": str(report), "tool_result": payload}
        command = [str(item).replace("{video}", str(abs_path(video))).replace("{out}", str(report)) for item in task.get("command", [])]
        if not command:
            command = ["python3", "tools/frame_cadence_audit.py", "--video", str(abs_path(video)), "--out", str(report)]
    else:
        return {"state": "tool_failed_terminal", "tool_error": f"unsupported_tool_type:{tool_type}"}
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    stdout_path = report.with_suffix(report.suffix + ".stdout.txt")
    stderr_path = report.with_suffix(report.suffix + ".stderr.txt")
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    payload = {
        "tool_type": tool_type,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "recorded_at": now(),
    }
    if tool_type == "agentcut":
        payload["cut_motivation_gate"] = str(cut_gate_report)
        payload["cut_motivation_gate_status"] = cut_gate_result.get("gate_status")
    atomic_json(report, payload)
    return {"state": "tool_pass" if proc.returncode == 0 else "tool_failed_terminal", "tool_report": str(report), "tool_result": payload}


def cli_int_duration(value: Any) -> str:
    duration = float(value)
    if not duration.is_integer():
        raise ValueError(f"video duration must be an integer number of seconds: {value!r}")
    return str(int(duration))


def submit_one(task: dict, receipt: dict) -> dict:
    tool_type = task.get("tool_type", "video_generation")
    if tool_type in {"agentcut", "ai_review"}:
        return run_local_tool(task, receipt)
    if tool_type not in {"video_generation", "image_generation"}:
        return {"state": "tool_failed_terminal", "tool_error": f"unsupported_tool_type:{tool_type}"}
    episode_match = re.match(r"E(\d+)(?:\D|$)", str(receipt.get("episode") or "").upper())
    if episode_match and int(episode_match.group(1)) >= 40:
        task["media_stage"] = "VIDEO" if tool_type == "video_generation" else "KEYFRAME"
        task["require_semantic_anchor_evidence"] = True
        task.setdefault("semantic_anchor_policy_version", "1.0.0")
        if tool_type == "video_generation":
            try:
                require_paid_model_contract(task, str(receipt.get("episode") or ""))
            except ValueError as exc:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_VIDEO_MODEL_ADAPTER_INVALID",
                    "model_adapter_error": str(exc),
                }
            action_failures = validate_action_contract(task)
            if action_failures:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_STRUCTURED_ACTION_CONTRACT_INVALID",
                    "action_contract_failures": action_failures,
                }
        else:
            try:
                require_paid_image_model_contract(task, str(receipt.get("episode") or ""))
            except ValueError as exc:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_IMAGE_MODEL_ADAPTER_INVALID",
                    "model_adapter_error": str(exc),
                }
    task["input_template_id"] = task.get("input_template_id") or compute_input_template_id(task)
    input_precheck = precheck_submission_inputs(task)
    if input_precheck.get("status") != "PASS":
        return {
            "status": "submit_blocked",
            "state": "tool_blocked",
            "block_code": "MISSING_ANCHOR_FOR_CANONICAL_ENTITY",
            "failure_attribution": "MISSING_REFERENCE_ANCHOR",
            "input_precheck": input_precheck,
        }
    if task.get("state") == "retry_pending" or task.get("retry_count"):
        retry_gate = validate_retry_change(task)
        if retry_gate.get("status") != "PASS":
            return {
                "status": "submit_blocked",
                "state": "tool_blocked",
                "block_code": (retry_gate.get("failures") or ["RETRY_CHANGED_WRONG_VARIABLE"])[0],
                "retry_gate": retry_gate,
            }
    if tool_type == "video_generation":
        match = episode_match
        if match and int(match.group(1)) >= 40:
            admission_ref = task.get("start_frame_admission_ref")
            if not admission_ref:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_START_FRAME_CONTENT_ADMISSION_MISSING",
                }
            try:
                admission = evaluate_shot_media_admission(abs_path(admission_ref), ROOT)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_START_FRAME_CONTENT_ADMISSION_UNREADABLE",
                    "error": type(exc).__name__,
                }
            if admission.get("status") not in {"ADMITTED", "ADMITTED_WITH_P2"}:
                return {
                    "status": "submit_blocked", "state": "tool_blocked",
                    "block_code": "BLOCK_START_FRAME_NOT_CONTENT_ADMITTED",
                    "admission": admission,
                }
        binding_gate = evaluate_multimodal_character_task(task)
        if binding_gate.get("status") != "PASS":
            return {
                "status": "submit_blocked",
                "state": "tool_blocked",
                "block_code": "BLOCK_MULTIMODAL_CHARACTER_BINDING",
                "binding_gate": binding_gate,
            }
        task["generation_fingerprint"] = generation_fingerprint(task)
        existing = find_existing_paid_candidate(receipt.get("episode", "UNKNOWN"), task, receipt)
        if existing:
            return {
                "status": "submit_blocked",
                "state": "tool_blocked",
                "block_code": "BLOCK_UNCHANGED_VIDEO_REGENERATION",
                "existing_candidate": existing,
                "required_action": "Reuse the existing candidate or change a generation-affecting prompt, asset, duration, model, or parameter before a failed-only resubmission.",
            }
    entity_reference_failures = validate_entity_reference_task(task)
    if entity_reference_failures:
        return {
            "status": "submit_blocked",
            "state": "tool_blocked",
            "block_code": "BLOCK_ENTITY_REFERENCE_SEQUENCE_PREFLIGHT",
            "preflight_failures": entity_reference_failures,
        }
    if task.get("reference_asset_registration_failures"):
        return {
            "status": "submit_blocked",
            "state": "tool_blocked",
            "block_code": "BLOCK_LOCAL_REFERENCE_ASSET_REGISTRATION",
            "preflight_failures": task["reference_asset_registration_failures"],
        }
    prompt_file = abs_path(task["prompt_file"]) if task.get("prompt_file") else None
    prompt = prompt_file.read_text(encoding="utf-8") if prompt_file else str(task.get("prompt") or "")
    if tool_type == "image_generation" and episode_match and int(episode_match.group(1)) >= 40:
        try:
            require_paid_image_model_contract(
                task, str(receipt.get("episode") or ""), prompt_text=prompt
            )
        except ValueError as exc:
            return {
                "status": "submit_blocked", "state": "tool_blocked",
                "block_code": "BLOCK_IMAGE_IDENTITY_TRANSPORT_INVALID",
                "model_adapter_error": str(exc),
            }
    args = [
        "--prompt-file", str(prompt_file),
    ]
    if tool_type == "image_generation":
        command = ["python3", str(ROOT / "tools/giggle_api_client.py"), "image", "--prompt", prompt]
    else:
        command = ["python3", str(ROOT / "tools/giggle_api_client.py"), "omni-video", *args]
    if tool_type == "image_generation":
        # The image CLI accepts local reference images and sends them as base64
        # to image-to-image. Registered asset IDs are an omni-video transport
        # and must never leak into this command.
        for ref in task.get("reference_images", []):
            command.extend(["--reference-image", str(abs_path(ref))])
    else:
        image_transport = task.get("reference_image_transport")
        image_asset_ids = [] if image_transport in {"inline_base64", "direct_url"} else [
            *list(task.get("reference_image_asset_ids") or []),
            *list(task.get("resolved_reference_image_asset_ids") or []),
        ]
        if image_transport == "direct_url":
            image_urls = list(task.get("reference_image_urls") or [])
            if len(image_urls) != len(task.get("reference_images") or []):
                return {
                    "status": "submit_blocked",
                    "state": "tool_blocked",
                    "block_code": "BLOCK_DIRECT_IMAGE_URL_COVERAGE",
                    "expected": len(task.get("reference_images") or []),
                    "actual": len(image_urls),
                }
            for image_url in image_urls:
                command.extend(["--image-url", str(image_url)])
        elif image_asset_ids:
            for asset_id in image_asset_ids:
                command.extend(["--image-asset-id", str(asset_id)])
        else:
            for ref in task.get("reference_images", []):
                command.extend(["--reference-image", str(abs_path(ref))])
        for asset_id in [*task.get("reference_audio_asset_ids", []), *task.get("resolved_reference_audio_asset_ids", [])]:
            command.extend(["--audio-asset-id", str(asset_id)])
        for asset_id in [*task.get("reference_video_asset_ids", []), *task.get("resolved_reference_video_asset_ids", [])]:
            command.extend(["--video-asset-id", str(asset_id)])
    command.extend(["--model", task.get("model", "gpt-image-2-pro" if tool_type == "image_generation" else "seedance-2.0-fast")])
    if tool_type == "video_generation":
        try:
            duration = cli_int_duration(task.get("duration", 4))
        except (TypeError, ValueError) as exc:
            return {"status": "submit_failed", "stderr": str(exc), "stdout": ""}
        command.extend(["--duration", duration])
    command.extend(["--aspect-ratio", task.get("aspect_ratio", "9:16"), "--resolution", task.get("resolution", "1K" if tool_type == "image_generation" else "720p"), "--count", "1"])
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=os.environ.copy())
    if proc.returncode != 0:
        return {"status": "submit_failed", "stderr": proc.stderr[-2000:], "stdout": proc.stdout[-2000:]}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "submit_failed", "stderr": "invalid_json_response", "stdout": proc.stdout[-2000:]}
    task_id = (payload.get("data") or {}).get("task_id") or payload.get("task_id")
    return {"status": "remote_running", "task_id": task_id, "submit_response": payload}


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    request = Request(url, headers={"User-Agent": "qingshan-episode-parallel-batch/1.0"})
    with urlopen(request, timeout=240) as source, partial.open("wb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    os.replace(partial, destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def confirmed_periodic_duplicate_frames(cadence_path: Path) -> list[int]:
    try:
        payload = read_json(cadence_path)
    except (OSError, json.JSONDecodeError):
        return []
    periodic = payload.get("periodic_duplicates") or {}
    confirmed = [
        chain for chain in periodic.get("periodic_chains") or []
        if chain.get("verification_status") == "CONFIRMED_MPDECIMATE"
    ]
    if payload.get("status") != "FAIL" or not confirmed:
        return []
    return sorted(set(int(frame) for frame in periodic.get("mpdecimate_removed_frames") or []))


def run_qa(task: dict, output: Path, batch_receipt: dict) -> dict:
    qa_dir = abs_path(task["qa_dir"])
    qa_dir.mkdir(parents=True, exist_ok=True)
    qa_python, qa_runtime = resolve_qa_python()
    if not qa_python:
        task.update({
            "qa": {
                "status": "FAIL_QA_RUNTIME_UNAVAILABLE",
                "failures": [{"check": "source_video_qa_runtime", "report": qa_runtime}],
                "recorded_at": now(),
            }
        })
        return {"status": "qa_failed", "failures": task["qa"]["failures"]}
    stem = safe(task["task_key"])
    cadence_path = qa_dir / f"{stem}_frame_cadence.json"
    cadence = subprocess.run([
        sys.executable, "tools/frame_cadence_audit.py", "--video", str(output), "--out", str(cadence_path)
    ], cwd=ROOT, check=False)
    qa_output = output
    cadence_gate = cadence
    cadence_gate_path = cadence_path
    local_repair = None
    duplicate_frames = confirmed_periodic_duplicate_frames(cadence_path) if cadence.returncode else []
    if task.get("tool_type") == "video_generation" and duplicate_frames:
        repaired = output.with_name(f"{output.stem}_DEDUP_FRAMES{output.suffix}")
        repair_report = qa_dir / f"{stem}_DEDUP_FRAMES_REPAIR.json"
        repair = subprocess.run([
            sys.executable, "tools/repair_periodic_duplicate_frames.py",
            "--video", str(output), "--cadence-report", str(cadence_path),
            "--out", str(repaired), "--report", str(repair_report),
        ], cwd=ROOT, check=False)
        post_cadence_path = qa_dir / f"{stem}_DEDUP_FRAMES_frame_cadence.json"
        post_cadence = subprocess.run([
            sys.executable, "tools/frame_cadence_audit.py", "--video", str(repaired), "--out", str(post_cadence_path)
        ], cwd=ROOT, check=False) if repair.returncode == 0 else None
        local_repair = {
            "status": "PASS" if post_cadence is not None and post_cadence.returncode == 0 else "FAIL",
            "method": "DELETE_CONFIRMED_DUPLICATE_FRAMES_AND_MATCHING_AUDIO_INTERVALS_ONLY",
            "raw_output_path": str(output),
            "raw_cadence_report": str(cadence_path),
            "repair_report": str(repair_report),
            "post_repair_cadence_report": str(post_cadence_path),
            "removed_frame_indices": duplicate_frames,
            "new_generation_credits": 0,
        }
        if post_cadence is not None and post_cadence.returncode == 0:
            qa_output = repaired
            cadence_gate = post_cadence
            cadence_gate_path = post_cadence_path

    ocr_path = qa_dir / f"{stem}{'_DEDUP_FRAMES' if qa_output != output else ''}_ocr.json"
    frame_path = qa_dir / f"{stem}{'_DEDUP_FRAMES' if qa_output != output else ''}_review.jpg"
    ocr = subprocess.run([
        qa_python, "tools/final_video_ocr_audit.py", "--video", str(qa_output), "--out", str(ocr_path),
        "--source-mode", "--allow-text", "__NO_TEXT_ALLOWED__", "--forbid-text", "__FORBIDDEN_TEXT__"
    ], cwd=ROOT, check=False)
    frame = subprocess.run([
        str(resolve_media_binary("ffmpeg")), "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.0", "-i", str(qa_output),
        "-frames:v", "1", "-q:v", "2", str(frame_path)
    ], cwd=ROOT, check=False)
    dialogue_contract_path = qa_dir / f"{stem}_dialogue_contract.json"
    dialogue_report_path = qa_dir / f"{stem}_native_dialogue.json"
    atomic_json(
        dialogue_contract_path,
        {
            "schema": "qingshan.source_video_dialogue_contract.v1",
            "dialogue": list(task.get("dialogue") or []),
            "native_dialogue_required": bool(task.get("native_dialogue_required")),
        },
    )
    dialogue_command = [
        qa_python,
        "-m",
        "tools.source_video_dialogue_gate",
        "--video",
        str(qa_output),
        "--dialogue-json",
        str(dialogue_contract_path),
        "--out",
        str(dialogue_report_path),
        "--minimum-recall",
        str(task.get("minimum_dialogue_recall", 0.55)),
    ]
    if task.get("whisper_model"):
        dialogue_command.extend(["--model", str(task["whisper_model"])])
    dialogue = subprocess.run(dialogue_command, cwd=ROOT, check=False)
    try:
        dialogue_report = read_json(dialogue_report_path)
    except (OSError, json.JSONDecodeError) as exc:
        dialogue_report = {
            "status": "FAIL",
            "invoked": True,
            "failures": [f"dialogue_report_unreadable:{type(exc).__name__}"],
        }
    dialogue_report.setdefault("invoked", True)
    record_gate_result(
        batch_receipt.get("episode", "UNKNOWN"),
        "SOURCE-VIDEO-NATIVE-DIALOGUE-ASR",
        dialogue_report,
        dialogue_report_path,
    )
    failures = []
    if cadence_gate.returncode:
        failures.append({"check": "frame_cadence", "returncode": cadence_gate.returncode})
    if ocr.returncode:
        failures.append({"check": "full_motion_ocr", "returncode": ocr.returncode})
    if frame.returncode:
        failures.append({"check": "visual_frame_extract", "returncode": frame.returncode})
    if dialogue.returncode:
        failures.append(
            {
                "check": "native_dialogue_and_audio",
                "returncode": dialogue.returncode,
                "report": str(dialogue_report_path),
            }
        )
    sha = sha256_file(qa_output)
    task.update({
        "output_path": str(qa_output),
        "sha256": sha,
        "qa": {
            "status": "TECHNICAL_PASS_CONTENT_UNREVIEWED" if not failures else "TECHNICAL_FAIL",
            "scope": "TECHNICAL_AND_MACHINE_CHECKS_ONLY",
            "content_admission_status": "PENDING_ORIGINAL_RESOLUTION_REVIEW" if not failures else "NOT_APPLICABLE",
            "failures": failures,
            "frame_cadence": str(cadence_gate_path),
            "raw_frame_cadence": str(cadence_path),
            "ocr": str(ocr_path),
            "visual_review": str(frame_path),
            "native_dialogue": str(dialogue_report_path),
            "dialogue_contract": str(dialogue_contract_path),
            "automatic_local_repair": local_repair,
            "qa_runtime": qa_runtime,
            "recorded_at": now(),
        },
    })
    return {
        "status": "technical_pass_content_unreviewed" if not failures else "qa_failed",
        "failures": failures,
    }


def submission_scope_tasks(config: dict) -> list[dict]:
    """Keep full-episode gate context while scheduling only explicit repair tasks."""
    scope = config.get("submission_scope_task_keys")
    tasks = list(config.get("tasks") or [])
    if scope is None:
        return tasks
    scope_keys = {str(key) for key in scope}
    available = {str(task.get("task_key")) for task in tasks}
    missing = sorted(scope_keys - available)
    if missing:
        raise ValueError(f"submission scope contains unknown task keys: {missing}")
    return [task for task in tasks if str(task.get("task_key")) in scope_keys]


def initial_receipt(config: dict, receipt_path: Path) -> dict:
    legacy = config.get("legacy_receipt")
    legacy_task = None
    if legacy:
        legacy_path = abs_path(legacy)
        if legacy_path.is_file():
            try:
                legacy_task = read_json(legacy_path).get("task_id")
            except (OSError, json.JSONDecodeError):
                legacy_task = None
    tasks = []
    for index, raw in enumerate(submission_scope_tasks(config)):
        task = dict(raw)
        task.setdefault("task_key", f"{config['episode']}-internal-{index + 1:02d}")
        task["qa_dir"] = config["qa_dir"]
        task["output_dir"] = config["output_dir"]
        task.setdefault("state", "pending" if task_config_is_ready(task) else "waiting_dependencies")
        if index == 0 and legacy_task:
            task["task_id"] = legacy_task
            task["state"] = "remote_running"
            task["adopted_from_legacy_receipt"] = str(abs_path(legacy))
        tasks.append(task)
    return {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": config["episode"],
        "supervisor_type": "episode_parallel_batch",
        "status": "BATCH_RUNNING",
        "local_pid": os.getpid(),
        "started_at": now(),
        "last_action_at": now(),
        "last_action": "parallel_batch_supervisor_started",
        "parallel_submission": True,
        "supported_tool_types": ["video_generation", "image_generation", "agentcut", "ai_review"],
        "parallel_tool_policy": "Submit every independent tool task concurrently; only its own declared input dependency may gate it.",
        "submission_scope_task_keys": config.get("submission_scope_task_keys"),
        "max_retries": int(config.get("max_retries", 2)),
        "base_batch_note": config.get("base_batch_note"),
        "tasks": tasks,
    }


def task_config_is_ready(task: dict) -> bool:
    """Treat readiness as a per-unit dependency signal, never a batch barrier."""
    explicit = task.get("dependencies_ready")
    if explicit is not None:
        return bool(explicit)
    status = str(task.get("status") or "").strip().upper()
    if not status:
        return True
    blocked_markers = ("WAITING", "BLOCKED", "HOLD", "NOT_READY", "PENDING_DEPENDENCIES")
    if any(marker in status for marker in blocked_markers):
        return False
    return "READY" in status and "SUBMIT" in status


def bind_predecessor_tail_frame(task: dict, dependency: dict) -> bool:
    """Bind an accepted predecessor tail as the sole first temporal anchor."""
    contract = task.get("action_sequence_contract") or {}
    destination_value = contract.get("predecessor_tail_frame_ref")
    source_value = dependency.get("output_path")
    if not destination_value or not source_value:
        return False
    source = abs_path(source_value)
    destination = abs_path(destination_value)
    if not source.is_file():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        ffmpeg = str(resolve_media_binary("ffmpeg"))
        for tail_offset in ("-0.10", "-0.20", "-0.50"):
            proc = subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-sseof", tail_offset, "-i", str(source), "-frames:v", "1", "-q:v", "2", str(destination),
            ], cwd=ROOT, check=False)
            if proc.returncode == 0 and destination.is_file() and destination.stat().st_size > 0:
                break
        if not destination.is_file() or destination.stat().st_size == 0:
            return False
    destination_ref = str(destination_value)
    tail_sha = sha256_file(destination)
    sequence = list(task.get("reference_image_sequence") or [])
    non_temporal_markers = (
        "IDENTITY",
        "CHARACTER_REFERENCE",
        "STYLE_REFERENCE",
        "SCENE_REFERENCE",
        "REFERENCE_ONLY",
    )
    replacement = {
        "asset_label": "@图片1",
        "role": "EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME",
        "path": destination_ref,
        "sha256": tail_sha,
        "identity_reference": False,
    }
    replaced = False
    rebound_sequence = []
    for row in sequence:
        role = str(row.get("role") or "").upper()
        if not replaced and not any(marker in role for marker in non_temporal_markers):
            rebound_sequence.append(replacement)
            replaced = True
            continue
        if row.get("path") != destination_ref:
            rebound_sequence.append(row)
    if not replaced:
        rebound_sequence.insert(0, replacement)
    task["reference_image_sequence"] = rebound_sequence
    task["reference_images"] = [
        str(row.get("path")) for row in rebound_sequence if row.get("path")
    ]
    task["predecessor_tail_frame_sha256"] = tail_sha
    task["predecessor_output_sha256"] = dependency.get("sha256") or sha256_file(source)
    task["predecessor_tail_bound_at"] = now()
    task["dependencies_ready"] = True
    return True


def refresh_streaming_task_readiness(receipt: dict, config: dict) -> dict:
    """Merge newly ready units without waiting for the rest of the episode."""
    existing = {task.get("task_key"): task for task in receipt.get("tasks", [])}
    added = []
    activated = []
    for template in submission_scope_tasks(config):
        key = template.get("task_key")
        if not key:
            continue
        task = existing.get(key)
        if task is None:
            task = dict(template)
            task["qa_dir"] = config["qa_dir"]
            task["output_dir"] = config["output_dir"]
            task["state"] = "pending" if task_config_is_ready(template) else "waiting_dependencies"
            receipt.setdefault("tasks", []).append(task)
            existing[key] = task
            added.append(key)
            if task["state"] == "pending":
                activated.append(key)
            continue
        if task.get("state") == "waiting_dependencies":
            for field, value in template.items():
                if field not in {"state", "task_id", "credit_attempts"}:
                    task[field] = value
            dependency_key = task.get("depends_on_task")
            dependency = existing.get(dependency_key) if dependency_key else None
            dependency_ready = bool(
                dependency
                and dependency.get("state") in SUCCESS_TASK_STATES
                and bind_predecessor_tail_frame(task, dependency)
            )
            if dependency_ready or task_config_is_ready(template):
                task["state"] = "pending"
                task["dependency_ready_at"] = now()
                activated.append(key)
    if added or activated:
        receipt["last_action"] = (
            f"streaming_readiness_refresh:added={len(added)}:activated={len(activated)}"
        )
        receipt["last_action_at"] = now()
    receipt["streaming_readiness"] = {
        "policy": "SUBMIT_EACH_VIDEO_UNIT_IMMEDIATELY_WHEN_ITS_OWN_DEPENDENCIES_PASS",
        "batch_barrier": False,
        "waiting_task_keys": [
            task.get("task_key") for task in receipt.get("tasks", [])
            if task.get("state") == "waiting_dependencies"
        ],
        "updated_at": now(),
    }
    return {"added": added, "activated": activated}


def select_parallel_submission_wave(tasks: list[dict]) -> tuple[list[dict], list[dict]]:
    """Run every independent task plus one ready head from each serial chain."""
    selected: list[dict] = []
    deferred: list[dict] = []
    claimed_chains: set[str] = set()
    ordered = sorted(
        tasks,
        key=lambda task: (
            str((task.get("action_sequence_contract") or {}).get("chain_id") or ""),
            int((task.get("action_sequence_contract") or {}).get("sequence_index") or 0),
            str(task.get("task_key") or ""),
        ),
    )
    for task in ordered:
        if task.get("generation_schedule_mode") != "TAIL_CHAINED_SERIAL":
            selected.append(task)
            continue
        chain_id = str((task.get("action_sequence_contract") or {}).get("chain_id") or "").strip()
        if not chain_id or chain_id not in claimed_chains:
            selected.append(task)
            if chain_id:
                claimed_chains.add(chain_id)
        else:
            deferred.append(task)
    return selected, deferred


def submit_pending(receipt: dict) -> None:
    pending = [task for task in receipt["tasks"] if not task.get("task_id") and task.get("state") in {"pending", "retry_pending", "submit_failed"} and int(task.get("retry_count", 0)) <= int(receipt.get("max_retries", 2))]
    if not pending:
        return
    wave, deferred = select_parallel_submission_wave(pending)
    worker_limit = max(1, int(receipt.get("max_submit_workers", 8)))
    with ThreadPoolExecutor(max_workers=min(worker_limit, len(wave))) as pool:
        futures = {pool.submit(submit_one, task, receipt): task for task in wave}
        for future in as_completed(futures):
            task = futures[future]
            result = future.result()
            task.update(result)
            record_submit_credit_attempt(task, result)
            if result.get("state") in {"tool_pass", "tool_failed_terminal", "tool_blocked"}:
                task["state"] = result["state"]
            elif result.get("task_id"):
                task["state"] = "remote_running"
                task["submitted_at"] = now()
            else:
                task["retry_count"] = int(task.get("retry_count", 0)) + 1
                task["state"] = "retry_pending" if task["retry_count"] <= int(receipt.get("max_retries", 2)) else "submit_failed_terminal"
                task["retry_after"] = now()
    receipt["last_action"] = f"submitted_{len(wave)}_tasks_across_dependency_lanes_concurrently"
    receipt["last_action_at"] = now()
    receipt["concurrency_wave"] = {
        "submitted_task_keys": [task.get("task_key") for task in wave],
        "deferred_same_chain_task_keys": [task.get("task_key") for task in deferred],
        "max_submit_workers": worker_limit,
        "policy": "ONE_READY_HEAD_PER_SERIAL_CHAIN_PLUS_ALL_INDEPENDENT_TASKS",
        "recorded_at": now(),
    }


def poll_one(task: dict) -> dict:
    if task.get("state") in TERMINAL_TASK_STATES or not task.get("task_id"):
        return {"task_key": task["task_key"], "state": task.get("state")}
    try:
        data = (query_task(SimpleNamespace(task_id=task["task_id"])).get("data") or {})
    except BaseException as exc:
        return {
            "task_key": task["task_key"],
            "task_id": task["task_id"],
            "query_error": f"{type(exc).__name__}: {exc}",
        }
    status = str(data.get("status") or "unknown").lower()
    return {"task_key": task["task_key"], "task_id": task["task_id"], "remote_status": status, "data": data}


def reconcile_completed_image_credits(receipt: dict) -> None:
    """Resolve submitted image charges once per model/window; image rows omit task ids.

    Billing occurs at submission, so the exact-count denominator must be every
    successfully submitted image in the isolated batch, not only images whose
    generation has already completed. That lets each completed image harvest
    immediately after the batch charge window closes.
    """
    completed = [
        task for task in receipt.get("tasks", [])
        if task.get("tool_type") == "image_generation"
        and task.get("remote_status") == "completed"
        and task.get("task_id")
    ]
    if not completed:
        return
    submitted = [
        task for task in receipt.get("tasks", [])
        if task.get("tool_type") == "image_generation" and task.get("task_id")
    ]
    by_model: dict[str, list[dict]] = {}
    for task in submitted:
        by_model.setdefault(str(task.get("model") or "gpt-image-2-pro"), []).append(task)
    try:
        rows = fetch_pay_statements(max(100, len(completed) * 4))
    except BaseException as exc:
        receipt["image_credit_reconciliation"] = {
            "status": "INCOMPLETE",
            "error": f"{type(exc).__name__}: {exc}",
            "queried_at": now(),
        }
        return
    reconciliations = []
    for model, tasks in sorted(by_model.items()):
        starts = [task.get("submitted_at") for task in tasks if task.get("submitted_at")]
        if not starts:
            continue
        reconciliation = reconcile_rows(
            rows,
            start=min(parse_utc(value) for value in starts),
            end=parse_utc(now()),
            expected_count=len(tasks),
            event_description="SingleGenerateImage",
            model=model,
        )
        reconciliation["queried_at"] = now()
        reconciliations.append(reconciliation)
        total = reconciliation.get("charged_credits")
        if reconciliation.get("status") != "PASS" or not isinstance(total, (int, float)):
            continue
        per_task = total / len(tasks)
        if int(per_task) != per_task:
            reconciliation["status"] = "FAIL_NON_UNIFORM_PER_TASK_ALLOCATION"
            continue
        for task in tasks:
            attempt = next(
                (row for row in reversed(task.get("credit_attempts") or []) if row.get("task_id") == task.get("task_id")),
                None,
            )
            if not attempt:
                continue
            attempt.update({
                "returned_credit": int(per_task),
                "credit_response_path": reconciliation.get("endpoint"),
                "charge_status": "KNOWN_BATCH_LEDGER_EXACT_COUNT",
                "actual_charged_credits": int(per_task),
                "evidence": "image_batch_time_window_event_model_exact_count",
                "credit_statement_reconciliation": reconciliation,
                "settled_at": now(),
            })
    receipt["image_credit_reconciliation"] = {
        "status": "PASS" if reconciliations and all(row.get("status") == "PASS" for row in reconciliations) else "INCOMPLETE",
        "groups": reconciliations,
        "queried_at": now(),
    }


def mark_retry_or_terminal(task: dict, receipt: dict, terminal_state: str) -> None:
    task["failure_attribution"] = task.get("failure_attribution") or "MODEL_STOCHASTIC"
    previous = task.get("previous_failure_attribution")
    task["same_attribution_consecutive_count"] = (
        int(task.get("same_attribution_consecutive_count") or 0) + 1
        if previous == task["failure_attribution"] else 1
    )
    task["previous_failure_attribution"] = task["failure_attribution"]
    task["retry_count"] = int(task.get("retry_count", 0)) + 1
    task["state"] = (
        "retry_pending"
        if task["retry_count"] <= int(receipt.get("max_retries", 2))
        else terminal_state
    )


def apply_template_defect_policy(receipt: dict) -> dict:
    """Suspend repeated same-cause retries as one template repair batch."""
    report = aggregate_template_defects(receipt.get("tasks") or [])
    receipt["template_defect_report"] = report
    affected: set[str] = set()
    for defect in report.get("template_defects") or []:
        affected.update(defect.get("affected_task_keys") or [])
    for task in receipt.get("tasks") or []:
        key = str(task.get("task_key") or task.get("unit_id") or "UNKNOWN")
        if key in affected and task.get("state") in {
            "retry_pending", "submit_failed", "qa_failed_terminal", "remote_failed_terminal"
        }:
            task["state"] = "template_defect_pending"
            task["required_action"] = "REPAIR_INPUT_TEMPLATE_THEN_PARALLEL_RESUBMIT_GROUP"
    return report


def harvest_completed_task(task: dict, result: dict, receipt: dict) -> None:
    """Download and QA one completed task inside its own dependency lane."""
    attempt = next(
        (row for row in reversed(task.get("credit_attempts") or []) if row.get("task_id") == task.get("task_id")),
        None,
    )
    if not attempt or not isinstance(attempt.get("actual_charged_credits"), (int, float)):
        task["state"] = "completed_credit_accounting_incomplete"
        task["credit_accounting_block"] = "EXACT_TASK_ID_STATEMENT_REQUIRED_BEFORE_DOWNLOAD_QA"
        return
    task.pop("credit_accounting_block", None)
    urls = (result.get("data") or {}).get("urls") or []
    if not urls:
        task["state"] = "completed_without_output_url"
        return
    suffix = ".png" if task.get("tool_type") == "image_generation" else ".mp4"
    output = abs_path(receipt.get("output_dir", "working_assets")) / f"{safe(receipt['episode'])}_{safe(task['task_key'])}_{task['task_id']}{suffix}"
    if not output.exists():
        download(str(urls[0]), output)
    if task.get("tool_type") == "image_generation":
        task.update({"state": "image_pass", "output_path": str(output), "sha256": subprocess.check_output(["shasum", "-a", "256", str(output)], text=True).split()[0], "recorded_at": now()})
        return
    qa = run_qa(task, output, receipt)
    if qa["status"] == "technical_pass_content_unreviewed":
        match = re.match(r"E(\d+)(?:\D|$)", str(receipt.get("episode") or "").upper())
        task["state"] = "technical_pass_content_unreviewed" if match and int(match.group(1)) >= 40 else "qa_pass"
        return
    task["failure_evidence"] = qa["failures"]
    task["failure_attribution"] = (
        qa.get("failure_attribution")
        or task.get("failure_attribution")
        or "MODEL_STOCHASTIC"
    )
    previous = task.get("previous_failure_attribution")
    task["same_attribution_consecutive_count"] = (
        int(task.get("same_attribution_consecutive_count") or 0) + 1
        if previous == task["failure_attribution"] else 1
    )
    task["previous_failure_attribution"] = task["failure_attribution"]
    # Preserve the charged remote asset for prompt-aware failed-only repair.
    task["retry_count"] = int(task.get("retry_count", 0)) + 1
    task["state"] = "qa_failed_terminal"


def poll_and_harvest(receipt: dict) -> None:
    active = [
        task
        for task in receipt["tasks"]
        if task.get("task_id") and task.get("state") not in TERMINAL_TASK_STATES
    ]
    if not active:
        return
    poll_worker_limit = max(1, int(receipt.get("max_poll_workers", 8)))
    with ThreadPoolExecutor(max_workers=min(poll_worker_limit, len(active))) as pool:
        futures = [pool.submit(poll_one, task) for task in active]
        results = [future.result() for future in as_completed(futures)]
    by_key = {task["task_key"]: task for task in receipt["tasks"]}
    for result in results:
        task = by_key[result["task_key"]]
        if result.get("query_error"):
            task["last_poll_error"] = result["query_error"]
            task["last_poll_error_at"] = now()
            continue
        status = result.get("remote_status")
        task["last_polled_at"] = now()
        task["remote_status"] = status
        task.pop("last_poll_error", None)
        task.pop("last_poll_error_at", None)
        settle_credit_attempt(task, status, result.get("data") or {})
    reconcile_completed_image_credits(receipt)
    completed = [
        (by_key[result["task_key"]], result)
        for result in results
        if not result.get("query_error") and result.get("remote_status") == "completed"
    ]
    if completed:
        qa_worker_limit = max(1, int(receipt.get("max_qa_workers", 4)))
        with ThreadPoolExecutor(max_workers=min(qa_worker_limit, len(completed))) as pool:
            futures = [pool.submit(harvest_completed_task, task, result, receipt) for task, result in completed]
            for future in as_completed(futures):
                future.result()
    for result in results:
        task = by_key[result["task_key"]]
        if result.get("query_error"):
            continue
        status = result.get("remote_status")
        if status in {"running", "pending", "queued", "processing", "submitted"}:
            task["state"] = "remote_running"
        elif status == "completed":
            continue
        elif status in {"failed", "error", "cancelled", "timeout"}:
            task["failure_reason"] = (result.get("data") or {}).get("error") or status
            mark_retry_or_terminal(task, receipt, "remote_failed_terminal")
    apply_template_defect_policy(receipt)


def retry_failed(receipt: dict) -> None:
    apply_template_defect_policy(receipt)
    for task in receipt["tasks"]:
        if task.get("state") == "retry_pending" and task.get("retry_count", 0) <= receipt.get("max_retries", 2):
            task.pop("task_id", None)
    submit_pending(receipt)


def refresh_activity_state(receipt: dict) -> None:
    """Normalize task/batch liveness so readers cannot observe stale aliases."""
    for task in receipt.get("tasks", []):
        if task.get("state"):
            task["status"] = task["state"]
    receipt["active_task_ids"] = [task["task_id"] for task in receipt["tasks"] if task.get("state") == "remote_running" and task.get("task_id")]
    receipt["active_task_count"] = len(receipt["active_task_ids"])
    if receipt.get("submission_gate_blocked"):
        gate_status = (receipt.get("episode_video_credit_gate") or {}).get("status") or "BLOCKED_VIDEO_SUBMISSION_GATE"
        receipt["status"] = "BATCH_DRAINING_REMOTE_TASKS_AFTER_CREDIT_GATE" if receipt["active_task_ids"] else gate_status
        receipt["local_pid"] = os.getpid() if receipt["active_task_ids"] else None
        if not receipt["active_task_ids"]:
            receipt.setdefault("blocked_at", now())
        receipt["last_heartbeat_at"] = now()
        refresh_credit_summary(receipt)
        return
    if all(task.get("state") in TERMINAL_TASK_STATES for task in receipt["tasks"]):
        receipt["status"] = "BATCH_COMPLETE" if all(task.get("state") in SUCCESS_TASK_STATES for task in receipt["tasks"]) else "BATCH_COMPLETE_WITH_ISOLATED_FAILURES"
        receipt["finished_local_pid"] = receipt.get("local_pid") or os.getpid()
        receipt["local_pid"] = None
        receipt.setdefault("completed_at", now())
    else:
        receipt["status"] = "BATCH_RUNNING"
        receipt["local_pid"] = os.getpid()
        receipt.pop("completed_at", None)
    receipt["last_heartbeat_at"] = now()
    refresh_credit_summary(receipt)


def line_has_active_handle(line: dict) -> bool:
    return bool(line.get("local_pid") or line.get("task_ids") or line.get("task_count", 0))


def split_receipt_by_episode(receipt: dict) -> list[dict]:
    """Expose a cross-episode batch as one independently auditable line per episode."""
    grouped: dict[str, list[dict]] = {}
    for task in receipt.get("tasks", []):
        match = re.match(r"^(E\d+)(?:-|_)", str(task.get("task_key") or ""), re.IGNORECASE)
        if not match:
            continue
        grouped.setdefault(match.group(1).upper(), []).append(task)
    if len(grouped) <= 1:
        return [receipt]

    result = []
    for episode, tasks in sorted(grouped.items()):
        active_ids = [
            task["task_id"]
            for task in tasks
            if task.get("state") == "remote_running" and task.get("task_id")
        ]
        view = dict(receipt)
        view["episode"] = episode
        view["tasks"] = tasks
        view["active_task_ids"] = active_ids
        view["active_task_count"] = len(active_ids)
        result.append(view)
    return result


def upsert_activity_line(active_lines: list[dict], receipt: dict, evidence: str) -> None:
    """Refresh an existing episode line or append a newly activated replacement line."""
    line = next((row for row in active_lines if row.get("episode") == receipt.get("episode")), None)
    if line is None:
        line = {"line_id": f"LINE_{receipt.get('episode', 'UNKNOWN')}", "episode": receipt.get("episode")}
        active_lines.append(line)
    line.update({
        "active_work": "LOCAL_PARALLEL_BATCH_SUPERVISOR_AND_REMOTE_GENERATION",
        "task_ids": receipt.get("active_task_ids", []),
        "task_count": receipt.get("active_task_count", 0),
        "task_states": {task["task_key"]: task.get("state") for task in receipt.get("tasks", [])},
        "task_id": (receipt.get("active_task_ids") or [None])[0],
        "local_pid": receipt.get("local_pid"),
        "evidence": evidence,
        "state": receipt.get("status"),
        "real_activity": bool(receipt.get("local_pid") or receipt.get("active_task_ids")),
        "note": "All internal tool tasks are submitted concurrently; failures retry per task.",
    })


def update_activity(receipt_path: Path, receipt: dict) -> None:
    refresh_activity_state(receipt)
    atomic_json(receipt_path, receipt)
    snapshot_path = ROOT / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"
    if not snapshot_path.is_file():
        return

    lock_path = snapshot_path.with_suffix(snapshot_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        snapshot = read_json(snapshot_path)
        existing_lines = snapshot.get("parallel_lines", [])
        retired = [
            line.get("episode")
            for line in existing_lines
            if episode_has_release_record(line.get("episode"))
        ]
        active_lines = [
            line
            for line in existing_lines
            if not episode_has_release_record(line.get("episode"))
        ]
        snapshot["parallel_lines"] = active_lines
        snapshot["retired_released_episodes"] = sorted(
            set(snapshot.get("retired_released_episodes", [])) | set(retired)
        )
        receipt_views = split_receipt_by_episode(receipt)
        if len(receipt_views) > 1:
            active_lines[:] = [line for line in active_lines if line.get("episode") != receipt.get("episode")]
        for receipt_view in receipt_views:
            upsert_activity_line(active_lines, receipt_view, str(receipt_path.relative_to(ROOT)))
        snapshot["observed_at"] = now()
        snapshot["remote_poll_verified_at"] = snapshot["observed_at"]
        snapshot["active_count"] = sum(1 for line in active_lines if line_has_active_handle(line))
        snapshot["state"] = "TARGET_MET" if snapshot["active_count"] >= snapshot.get("target", 3) else "UNDER_TARGET"
        snapshot["source"] = "parallel_batch_supervisor_receipts_and_local_processes"
        snapshot["required_action"] = "Poll every internal task concurrently; download, QA and retry only the failed task."
        atomic_json(snapshot_path, snapshot)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def validate_initial_asset_library(config: dict) -> tuple[dict | None, Path | None]:
    """Run the current-episode asset lock before any paid provider call."""
    if config.get("initial_asset_library_required") is not True:
        return None, None
    qa_dir = abs_path(config.get("qa_dir", "qa"))
    report_path = qa_dir / (
        f"{safe(config.get('episode', 'episode'))}_INITIAL_PRODUCTION_ASSET_LIBRARY_GATE.json"
    )
    requirements_ref = config.get("asset_requirements_ref")
    library_ref = config.get("production_asset_library_ref")
    failures: list[dict] = []
    if not requirements_ref:
        failures.append({"asset_id": None, "errors": ["asset_requirements_ref_missing"]})
    if not library_ref:
        failures.append({"asset_id": None, "errors": ["production_asset_library_ref_missing"]})
    requirements_path = abs_path(requirements_ref) if requirements_ref else None
    library_path = abs_path(library_ref) if library_ref else None
    if requirements_path is not None and not requirements_path.is_file():
        failures.append({"asset_id": None, "errors": [f"asset_requirements_missing:{requirements_path}"]})
    if library_path is not None and not library_path.is_file():
        failures.append({"asset_id": None, "errors": [f"production_asset_library_missing:{library_path}"]})
    if failures:
        report = {
            "schema": "ai_drama.production_asset_library_gate.v1",
            "episode": config.get("episode"),
            "status": "FAIL",
            "checked_asset_count": 0,
            "failure_count": len(failures),
            "failures": failures,
            "completed_at": now(),
        }
    else:
        try:
            report = gate_initial_asset_library(
                read_json(library_path),
                read_json(requirements_path),
                str(config.get("episode") or ""),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            report = {
                "schema": "ai_drama.production_asset_library_gate.v1",
                "episode": config.get("episode"),
                "status": "FAIL",
                "checked_asset_count": 0,
                "failure_count": 1,
                "failures": [{"asset_id": None, "errors": [f"asset_library_gate_error:{exc}"]}],
                "completed_at": now(),
            }
    atomic_json(report_path, report)
    return report, report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument(
        "--precheck-only",
        action="store_true",
        help="Run every local gate and write a PASS receipt without credentials, registration, or paid submission.",
    )
    args = parser.parse_args()
    config_path = abs_path(args.config)
    receipt_path = abs_path(args.receipt)
    config = read_json(config_path)
    episode_match = re.match(r"E(\d+)(?:\D|$)", str(config.get("episode") or "").upper())
    if episode_match and int(episode_match.group(1)) >= 40 and not args.precheck_only:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_LEGACY_NON_TRANSACTIONAL_SUBMITTER",
            "local_pid": None,
            "config": str(config_path),
            "failures": ["E40_PLUS_REQUIRES_DURABLE_TRANSACTION_SUBMITTERS"],
            "rollback": (
                "Use submit_giggle_image_manifest.py for images and the deployed "
                "submit_giggle_video_manifest_v2.py for video; preserve precheck-only use here."
            ),
            "recorded_at": now(),
        })
        return 2
    asset_gate, asset_gate_path = validate_initial_asset_library(config)
    if asset_gate is not None:
        record_gate_result(
            config.get("episode"),
            "INITIAL-PRODUCTION-ASSET-LIBRARY",
            asset_gate,
            asset_gate_path,
        )
        if asset_gate.get("status") != "PASS":
            atomic_blocked_receipt(receipt_path, {
                "schema": "qingshan.episode_parallel_batch.v1",
                "episode": config.get("episode"),
                "status": "BLOCKED_INITIAL_PRODUCTION_ASSET_LIBRARY",
                "local_pid": None,
                "config": str(config_path),
                "asset_library_gate_report": str(asset_gate_path),
                "failures": asset_gate.get("failures", []),
                "rollback": "Lock only the missing or invalid current-episode assets with SHA, provenance, rights PASS and QA PASS; preserve existing locked assets and history.",
                "recorded_at": now(),
            })
            return 2
    submission_authority = evaluate_episode_submission_authority(str(config.get("episode") or "UNKNOWN"))
    if not args.precheck_only and submission_authority.get("status") != "PASS":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_EPISODE_VIDEO_SUBMISSION_AUTHORITY",
            "local_pid": None,
            "config": str(config_path),
            "submission_authority_gate": submission_authority,
            "failures": submission_authority.get("failures", []),
            "rollback": "Do not submit paid video work. Resume only through the episode's explicit authority file and preserve the referenced hold evidence.",
            "recorded_at": now(),
        })
        return 2
    readiness_ok, readiness_path, readiness_report, readiness_failures = validate_script_readiness(config)
    if not readiness_ok:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_SCRIPT_READINESS_GATE",
            "local_pid": None,
            "config": str(config_path),
            "script_readiness_report": readiness_path,
            "script_readiness_status": (readiness_report or {}).get("status"),
            "failures": readiness_failures,
            "rollback": "Repair the episode script contract and regenerate a PASS readiness report before remote submission.",
            "recorded_at": now(),
        })
        return 2
    writer_ok, writer_failures = validate_writer_agent_provenance(config)
    if not writer_ok:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_WRITER_AGENT_PROVENANCE",
            "local_pid": None,
            "config": str(config_path),
            "failures": writer_failures,
            "rollback": "Generate and validate an agent-native Writer Agent v0.3.0 / Schema 1.2.0 script, bind exact generated/compiled SHA-256 values, then rebuild the media batch.",
            "recorded_at": now(),
        })
        return 2
    if config.get("natural_split_gate_required") is True:
        contract_ref = config.get("natural_split_contract_ref")
        contract_path = abs_path(contract_ref) if contract_ref else None
        if contract_path is None or not contract_path.is_file():
            split_gate = {
                "status": "FAIL",
                "invoked": True,
                "failures": ["natural_split_contract_missing"],
            }
        else:
            split_gate = evaluate_performance_unit_split(
                read_json(contract_path), config=config, base=ROOT
            )
        split_gate_path = abs_path(config.get("qa_dir", "qa")) / (
            f"{safe(config.get('episode', 'episode'))}_VIDEO_PERFORMANCE_NATURAL_SPLIT_GATE.json"
        )
        atomic_json(split_gate_path, split_gate)
        record_gate_result(
            config.get("episode"),
            "VIDEO-PERFORMANCE-NATURAL-SPLIT",
            split_gate,
            split_gate_path,
        )
        if split_gate.get("status") != "PASS":
            atomic_blocked_receipt(receipt_path, {
                "schema": "qingshan.episode_parallel_batch.v1",
                "episode": config.get("episode"),
                "status": "BLOCKED_VIDEO_PERFORMANCE_NATURAL_SPLIT",
                "local_pid": None,
                "config": str(config_path),
                "natural_split_contract_ref": contract_ref,
                "natural_split_gate_report": str(split_gate_path),
                "failures": split_gate.get("failures", []),
                "rollback": "Repair only the affected split contract or unit. Preserve passed siblings and submit each independently ready unit without waiting for the episode batch.",
                "recorded_at": now(),
            })
            return 2
    supervisor_gate = validate_supervisor_script_gate(config)
    supervisor_gate_evidence = config.get("supervisor_script_gate_report") or receipt_path
    record_gate_result(config.get("episode"), "LOCAL-CLAUDE-SCRIPT-SUPERVISION", supervisor_gate, supervisor_gate_evidence)
    if supervisor_gate.get("status") != "PASS" or supervisor_gate.get("generation_allowed") is not True:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_LOCAL_CLAUDE_SCRIPT_SUPERVISION",
            "local_pid": None,
            "config": str(config_path),
            "supervisor_script_gate_report": config.get("supervisor_script_gate_report"),
            "supervisor_gate": supervisor_gate,
            "failures": supervisor_gate.get("failures", []),
            "rollback": "Regenerate with the active Writer Agent, then obtain a complete local-Claude per-shot PASS bound to the exact generated and compiled SHA-256 values.",
            "recorded_at": now(),
        })
        return 2
    corrected_quality_gate = validate_corrected_pipeline_quality(config)
    corrected_quality_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_CORRECTED_PIPELINE_QUALITY_GATE.json"
    atomic_json(corrected_quality_path, corrected_quality_gate)
    corrected_gate_ids = {
        "dramatic_quality_report_ref": "SCRIPT-COUNCIL-DRAMATIC-QUALITY",
        "mechanical_default_plan_ref": "MECHANICAL-DEFAULT-META-GATE",
        "video_unit_grouping_plan_ref": "VIDEO-UNIT-SEMANTIC-GROUPING",
        "anchor_count_plan_ref": "VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT",
        "common_sense_causality_plan_ref": "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
        "action_shot_design_plan_ref": "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
        "period_lock_plan_ref": "PERIOD-ANACHRONISM-LOCK",
    }
    for report_key, gate_id in corrected_gate_ids.items():
        report_row = corrected_quality_gate.get("reports", {}).get(report_key)
        if report_row and isinstance(report_row.get("result"), dict):
            record_gate_result(
                config.get("episode"), gate_id, report_row["result"],
                report_row.get("path") or corrected_quality_path,
            )
    if corrected_quality_gate.get("status") == "FAIL":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_CORRECTED_PIPELINE_QUALITY_GATE",
            "local_pid": None,
            "config": str(config_path),
            "corrected_pipeline_quality_report": str(corrected_quality_path),
            "failures": corrected_quality_gate.get("failures", []),
            "rollback": "Complete the six-seat script council, numeric density evidence, eight beat techniques and mechanical-default independence plan; do not submit paid media until the exact reports pass.",
            "recorded_at": now(),
        })
        return 2
    first_pass_gate = evaluate_generation_first_pass_policy(config)
    first_pass_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_GENERATION_FIRST_PASS_POLICY_GATE.json"
    atomic_json(first_pass_gate_path, first_pass_gate)
    if first_pass_gate.get("status") not in {"PASS", "NOT_APPLICABLE"}:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_GENERATION_FIRST_PASS_POLICY",
            "local_pid": None,
            "config": str(config_path),
            "generation_first_pass_policy_report": str(first_pass_gate_path),
            "failures": first_pass_gate.get("failures", []),
            "rollback": "Bind the standing Roger policy and current prompt-failure memory, predeclare CORE/NON_CORE with the80/60 threshold, and disposition every known failure mode before any paid submission.",
            "recorded_at": now(),
        })
        return 2
    complete_prompt_gate = validate_complete_video_prompt_manifest(config)
    complete_prompt_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_COMPLETE_VIDEO_PROMPT_MANIFEST_GATE.json"
    atomic_json(complete_prompt_gate_path, complete_prompt_gate)
    record_gate_result(config.get("episode"), "COMPLETE-VIDEO-PROMPT-MANIFEST", complete_prompt_gate, complete_prompt_gate_path)
    if complete_prompt_gate.get("status") == "FAIL":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_COMPLETE_VIDEO_PROMPT_MANIFEST",
            "local_pid": None,
            "config": str(config_path),
            "complete_video_prompt_manifest_report": str(complete_prompt_gate_path),
            "failures": complete_prompt_gate.get("failures", []),
            "rollback": "Compile the complete episode unit prompt manifest, restore per-scene weather authority, and make the submitted task prompt SHA match its manifest row before any paid call.",
            "recorded_at": now(),
        })
        return 2
    dialogue_gate = validate_dialogue_manifest_coverage(config)
    dialogue_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_VIDEO_DIALOGUE_MANIFEST_COVERAGE_GATE.json"
    atomic_json(dialogue_gate_path, dialogue_gate)
    record_gate_result(config.get("episode"), "EXACT-DIALOGUE-AUDIO-MANIFEST-COVERAGE", dialogue_gate, dialogue_gate_path)
    if dialogue_gate.get("status") == "FAIL":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_VIDEO_DIALOGUE_MANIFEST_COVERAGE",
            "local_pid": None,
            "config": str(config_path),
            "dialogue_manifest_coverage_report": str(dialogue_gate_path),
            "failures": dialogue_gate.get("failures", []),
            "rollback": "Rebuild only blocked unit prompts and exact dialogue audio bindings; never submit a no-dialogue task when the manifest assigns lines.",
            "recorded_at": now(),
        })
        return 2
    prompt_gate = evaluate_prompt_professionalism(config)
    prompt_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_SHOT_PROMPT_PROFESSIONALISM_GATE.json"
    atomic_json(prompt_gate_path, prompt_gate)
    record_gate_result(config.get("episode"), "SHOT-PROMPT-PROFESSIONALISM", prompt_gate, prompt_gate_path)
    if prompt_gate.get("status") != "PASS":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_SHOT_PROMPT_PROFESSIONALISM",
            "local_pid": None,
            "config": str(config_path),
            "prompt_professionalism_report": str(prompt_gate_path),
            "failures": (
                [row for result in prompt_gate.get("results", []) for row in result.get("failures", [])]
                + prompt_gate.get("batch_failures", [])
            ),
            "blocked_tasks": prompt_gate.get("blocked_tasks", []),
            "rollback": prompt_gate.get("rollback"),
            "recorded_at": now(),
        })
        return 2
    if config.get("space_camera_constraint_gate_required") is True:
        prompt_texts = {}
        for task in config.get("tasks", []):
            prompt_ref = task.get("prompt_file")
            if prompt_ref:
                prompt_path = abs_path(prompt_ref)
                if prompt_path.is_file():
                    prompt_texts[str(task.get("task_key"))] = prompt_path.read_text(encoding="utf-8")
        space_camera_gate = evaluate_space_camera_constraints(config.get("tasks", []), prompt_texts)
        space_camera_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_SHOT_SPACE_CAMERA_CONSTRAINT_GATE.json"
        atomic_json(space_camera_path, space_camera_gate)
        if space_camera_gate.get("status") != "PASS":
            atomic_blocked_receipt(receipt_path, {
                "schema": "qingshan.episode_parallel_batch.v1",
                "episode": config.get("episode"),
                "status": "BLOCKED_SHOT_SPACE_CAMERA_CONSTRAINT",
                "local_pid": None,
                "config": str(config_path),
                "space_camera_report": str(space_camera_path),
                "failures": space_camera_gate.get("failures", []),
                "rollback": space_camera_gate.get("rollback"),
                "recorded_at": now(),
            })
            return 2
    binding_gate = evaluate_multimodal_character_bindings(config)
    binding_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_MULTIMODAL_CHARACTER_BINDING_GATE.json"
    atomic_json(binding_gate_path, binding_gate)
    record_gate_result(config.get("episode"), "SPEAKER-VOICE-GENDER-BINDING", binding_gate, binding_gate_path)
    if binding_gate.get("status") != "PASS":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_MULTIMODAL_CHARACTER_BINDING",
            "local_pid": None,
            "config": str(config_path),
            "multimodal_character_binding_report": str(binding_gate_path),
            "blocked_tasks": binding_gate.get("blocked_tasks", []),
            "failures": [
                failure
                for result in binding_gate.get("results", [])
                for failure in result.get("failures", [])
            ],
            "rollback": binding_gate.get("rollback"),
            "recorded_at": now(),
        })
        return 2
    duration_failures = []
    for task in config.get("tasks", []):
        if task.get("tool_type") != "video_generation":
            continue
        duration_failures.extend(validate_duration_task(task))
    if duration_failures:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_SHOT_DURATION_POLICY",
            "local_pid": None,
            "config": str(config_path),
            "failures": duration_failures,
            "rollback": "Add a story-driven 4-15 second duration_plan to each video task; do not change image, AgentCut or AI-review tasks.",
            "recorded_at": now(),
        })
        return 2
    scene_contract_ref = config.get("scene_contract_ref")
    scene_gate = evaluate_batch(scene_contract_ref or {}, config)
    scene_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_SCENE_AUTHORITY_LOCK.json"
    atomic_json(scene_gate_path, scene_gate)
    record_gate_result(config.get("episode"), "SCENE-AUTHORITY-LOCK", scene_gate, scene_gate_path)
    if scene_gate.get("status") != "PASS":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_SCENE_AUTHORITY_LOCK",
            "local_pid": None,
            "config": str(config_path),
            "scene_contract_ref": scene_contract_ref,
            "scene_authority_report": str(scene_gate_path),
            "submission_authority_gate": {
                "status": "NOT_APPLICABLE_PRECHECK_ONLY",
                "observed_paid_submission_authority": submission_authority,
            },
            "failures": scene_gate.get("failures", []),
            "rollback": scene_gate.get("rollback"),
            "recorded_at": now(),
        })
        return 2
    keyframe_gate = validate_keyframe_admissions(config)
    keyframe_gate_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_KEYFRAME_VIDEO_SUBMIT_ADMISSION.json"
    atomic_json(keyframe_gate_path, keyframe_gate)
    if keyframe_gate.get("status") == "FAIL":
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_KEYFRAME_CONTENT_ADMISSION",
            "local_pid": None,
            "config": str(config_path),
            "keyframe_admission_report": str(keyframe_gate_path),
            "failures": keyframe_gate.get("failures", []),
            "rollback": "Create an exact-SHA formal start-frame admission from registered identity, scene, action-state, and period gates; advisory or technical-only evidence cannot authorize paid video submission.",
            "recorded_at": now(),
        })
        return 2
    qa_runtime_path = abs_path(config.get("qa_dir", "qa")) / f"{safe(config.get('episode', 'episode'))}_SOURCE_VIDEO_QA_RUNTIME.json"
    qa_python, qa_runtime = resolve_qa_python()
    atomic_json(qa_runtime_path, qa_runtime)
    record_gate_result(config.get("episode"), "SOURCE-VIDEO-QA-RUNTIME", qa_runtime, qa_runtime_path)
    if not qa_python:
        atomic_blocked_receipt(receipt_path, {
            "schema": "qingshan.episode_parallel_batch.v1",
            "episode": config.get("episode"),
            "status": "BLOCKED_SOURCE_VIDEO_QA_RUNTIME",
            "local_pid": None,
            "config": str(config_path),
            "qa_runtime_report": str(qa_runtime_path),
            "failures": qa_runtime.get("attempts", []),
            "rollback": "Repair the local QA Python runtime before any paid external submission.",
            "recorded_at": now(),
        })
        return 2
    if args.precheck_only:
        atomic_json(receipt_path, {
            "schema": "qingshan.episode_parallel_batch_precheck.v1",
            "episode": config.get("episode"),
            "status": "PASS_PRECHECK_ONLY",
            "precheck_only": True,
            "external_submission_attempted": False,
            "credits_charged": 0,
            "config": str(config_path),
            "script_readiness_report": readiness_path,
            "supervisor_gate": supervisor_gate,
            "corrected_pipeline_quality_report": str(corrected_quality_path),
            "generation_first_pass_policy_report": str(first_pass_gate_path),
            "complete_video_prompt_manifest_report": str(complete_prompt_gate_path),
            "dialogue_manifest_coverage_report": str(dialogue_gate_path),
            "prompt_professionalism_report": str(prompt_gate_path),
            "multimodal_character_binding_report": str(binding_gate_path),
            "scene_authority_report": str(scene_gate_path),
            "keyframe_admission_report": str(keyframe_gate_path),
            "qa_runtime_report": str(qa_runtime_path),
            "qa_python": qa_python,
            "task_keys": [task.get("task_key") for task in config.get("tasks", [])],
            "next_action": "Rerun without --precheck-only only when paid external submission is permitted.",
            "recorded_at": now(),
        })
        return 0
    ensure_giggle_api_key()
    receipt = read_json(receipt_path) if receipt_path.is_file() else initial_receipt(config, receipt_path)
    clear_resolved_scene_block(receipt, scene_contract_ref, scene_gate_path)
    receipt["output_dir"] = config["output_dir"]
    receipt["qa_dir"] = config["qa_dir"]
    receipt["config"] = str(config_path)
    if readiness_path:
        receipt["script_readiness_report"] = readiness_path
        receipt["script_readiness_status"] = "PASS"
    receipt["max_retries"] = int(config.get("max_retries", 2))
    receipt["max_submit_workers"] = int(config.get("max_submit_workers", 8))
    receipt["max_poll_workers"] = int(config.get("max_poll_workers", 8))
    receipt["max_qa_workers"] = int(config.get("max_qa_workers", 4))
    receipt["concurrency_policy"] = {
        "serial_scope": "ONLY_WITHIN_ONE_EXACT_TAIL_DEPENDENCY_CHAIN",
        "parallel_scope": "ALL_INDEPENDENT_CHAINS_AND_LOCAL_QA_LANES",
        "one_ready_head_per_serial_chain": True,
        "batch_barrier": False,
    }
    receipt["supported_tool_types"] = sorted(set(receipt.get("supported_tool_types", [])) | {"video_generation", "image_generation", "agentcut", "ai_review"})
    receipt.setdefault("parallel_tool_policy", "Submit every independent tool task concurrently; only its own declared input dependency may gate it.")
    config_tasks = {task.get("task_key"): task for task in config.get("tasks", [])}
    for task in receipt.get("tasks", []):
        template = config_tasks.get(task.get("task_key"), {})
        for key in (
            "tool_type",
            "project",
            "video",
            "depends_on_task",
            "command",
            "report",
            "reference_images",
            "reference_image_asset_ids",
            "resolved_reference_image_asset_ids",
            "reference_audios",
            "reference_audio_asset_ids",
            "reference_videos",
            "reference_assets",
            "required_slot_ids",
            "generation_mode",
            "batch_id",
            "unit_id",
            "action_reference_minimum",
            "state_reference_minimum",
            "action_unit",
            "reference_image_sequence",
        ):
            if key in template and key not in task:
                task[key] = template[key]
    refresh_streaming_task_readiness(receipt, config)
    atomic_json(receipt_path, receipt)
    exit_code = 0
    while True:
        # Upstream may append or activate one unit at a time. Reloading here is
        # what makes readiness streaming rather than an episode-wide barrier.
        config = read_json(config_path)
        refresh_streaming_task_readiness(receipt, config)
        prepare_local_reference_assets(receipt)
        gate = refresh_episode_video_credit_gate(receipt)
        if gate.get("status") == "PASS":
            submit_pending(receipt)
        poll_and_harvest(receipt)
        gate = refresh_episode_video_credit_gate(receipt)
        if gate.get("status") == "PASS":
            retry_failed(receipt)
        update_activity(receipt_path, receipt)
        if receipt.get("submission_gate_blocked") and not receipt.get("active_task_ids"):
            exit_code = 3
            break
        if receipt.get("status") in {"BATCH_COMPLETE", "BATCH_COMPLETE_WITH_ISOLATED_FAILURES"}:
            break
        time.sleep(args.interval)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
