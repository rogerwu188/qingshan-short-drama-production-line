#!/usr/bin/env python3
"""Durably submit independent Giggle video tasks without sacrificing concurrency."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import tempfile
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# A deployed transport wrapper must validate with the exact project checkout
# that produced the manifest.  Otherwise its bundled compiler can silently
# disagree with a newly released project compiler.
_project_root_hint = os.environ.get("BACKLOTOS_PROJECT_ROOT", "").strip()
if _project_root_hint:
    _project_root_path = Path(_project_root_hint).expanduser().resolve()
    for _path in (str(_project_root_path / "tools"), str(_project_root_path)):
        if _path not in sys.path:
            sys.path.insert(0, _path)

INSUFFICIENT_CREDIT_TERMS = (
    "insufficient credit", "insufficient credits", "insufficient balance",
    "not enough credit", "not enough credits", "credit balance too low",
    "余额不足", "积分不足", "额度不足",
)


class ProviderInsufficientCreditsError(RuntimeError):
    """The provider rejected submission because the account cannot fund it."""


class PromptScopeGateBlocked(ValueError):
    """The submit-boundary scope conflict gate failed before any intent or POST (not charged)."""


try:
    from giggle_api_client import _image_list, _registered_asset, _request, paid_video_submission_context
    from giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from video_model_adapter import require_paid_model_contract
    from retry_cap_gate import validate_submission_attempt
    from role_semantic_prompt_gate import (
        validate_role_semantics,
        validate_role_semantics_structure,
    )
    from grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from grouped_transition_contract import validate_transition_sequence
    from grouped_performance_contract import validate_grouped_beat_contract
    from grouped_internal_continuity_contract import validate_internal_transition_sequence
    from video_prompt_compiler import (
        compile_model_prompt,
        validate_model_prompt_for_model,
        validate_transition_prompt_for_model,
    )
    from production_efficiency_contract import DEFAULT_WAVE_SIZE, episode_number, require_e47_efficiency_contract
    from speaker_voice_contract import POLICY_VERSION as SPEAKER_VOICE_POLICY_VERSION
    from sd2_required_prompt_field_gate import validate_required_sd2_field_coverage
    from video_sequence_rhythm_gate import validate_combat_sequence_rhythm
    from opening_anchor_chain_gate import validate_opening_anchor_chain
    from provider_scope_projection import validate_provider_scope_projection
    from provider_request_digest import (
        require_no_silent_resubmission, require_reviewed_request,
        sent_audio_references, sent_image_sha256, task_request_digest,
    )
    from action_video_prompt_compiler import validate_action_contract
    from shot_media_admission_gate import compute_input_template_id, precheck_submission_inputs
    from video_live_binding import attributed_task_ids, live_bindings
    from h3_provider_english_contract import is_director_v2_text
except ModuleNotFoundError:
    from tools.giggle_api_client import _image_list, _registered_asset, _request, paid_video_submission_context
    from tools.giggle_credit_statements import fetch_pay_statements, reconcile_rows
    from tools.video_model_adapter import require_paid_model_contract
    from tools.retry_cap_gate import validate_submission_attempt
    from tools.role_semantic_prompt_gate import (
        validate_role_semantics,
        validate_role_semantics_structure,
    )
    from tools.grouped_camera_contract import validate_camera_plan, validate_camera_sequence
    from tools.grouped_transition_contract import validate_transition_sequence
    from tools.grouped_performance_contract import validate_grouped_beat_contract
    from tools.grouped_internal_continuity_contract import validate_internal_transition_sequence
    from tools.video_prompt_compiler import (
        compile_model_prompt,
        validate_model_prompt_for_model,
        validate_transition_prompt_for_model,
    )
    from tools.production_efficiency_contract import DEFAULT_WAVE_SIZE, episode_number, require_e47_efficiency_contract
    from tools.speaker_voice_contract import POLICY_VERSION as SPEAKER_VOICE_POLICY_VERSION
    from tools.sd2_required_prompt_field_gate import validate_required_sd2_field_coverage
    from tools.video_sequence_rhythm_gate import validate_combat_sequence_rhythm
    from tools.opening_anchor_chain_gate import validate_opening_anchor_chain
    from tools.provider_scope_projection import validate_provider_scope_projection
    from tools.provider_request_digest import (
        require_no_silent_resubmission, require_reviewed_request,
        sent_audio_references, sent_image_sha256, task_request_digest,
    )
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.shot_media_admission_gate import compute_input_template_id, precheck_submission_inputs
    from tools.video_live_binding import attributed_task_ids, live_bindings
    from tools.h3_provider_english_contract import is_director_v2_text

# Shot-scope upgrade (configs/PROMPT_SHOT_SCOPE_POLICY_V1.json): submit-boundary conflict gate
# and loaded-module audit.  Inactive episodes/models never call either, so their request,
# transaction intent and fingerprint stay byte-for-byte as before.
try:
    from tools.prompt_shot_scope_policy import active_for as shot_scope_active_for
    from tools.prompt_scope_conflict_gate import (
        check_task as check_prompt_scope_conflicts,
        loaded_module_audit,
    )
except ModuleNotFoundError:
    from prompt_shot_scope_policy import active_for as shot_scope_active_for
    from prompt_scope_conflict_gate import (
        check_task as check_prompt_scope_conflicts,
        loaded_module_audit,
    )


ROOT = Path(__file__).resolve().parents[1]
# The engine checkout this file was loaded from (ROOT may be re-pointed at a project by
# --project-root); used only to make the loaded-module audit paths portable.
ENGINE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GATE_IDS = frozenset({"WRITER-TO-PROVIDER-PROMPT-FIELD-LINEAGE"})
RUNTIME_GATE_BINDINGS = {
    "WRITER-TO-PROVIDER-PROMPT-FIELD-LINEAGE": "validate_required_sd2_field_coverage",
}
assert frozenset(RUNTIME_GATE_BINDINGS) == RUNTIME_GATE_IDS


def authoritative_pipeline_tools_dir() -> Path:
    """Resolve the versioned gate implementation shipped with this engine.

    ``BACKLOT_PIPELINE_TOOLS_DIR`` remains a supported enterprise override,
    but a clean clone is self-contained and defaults to its own tools folder.
    """
    configured = os.environ.get("BACKLOT_PIPELINE_TOOLS_DIR", "").strip()
    candidate = Path(configured).expanduser() if configured else ROOT / "tools"
    required = candidate / "production_video_submission_gate.py"
    if not required.is_file():
        raise ValueError(
            "Production video gate is unavailable; restore tools/production_video_submission_gate.py "
            "or set BACKLOT_PIPELINE_TOOLS_DIR to a compatible audited deployment."
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


NALU_BUILDER_ID_PREFIX = "build_nalu_preproduction"
NALU_SCOPE_LINE = "nalu"


def nalu_production_scope(manifest: dict[str, Any], manifest_path: Path, vm: Any,
                          nalu_built: bool) -> dict[str, Any] | None:
    """K145 binding: is this manifest production of the nalu roots in effect (``vm._np``)?

    The scope is the verified (runtime_root, work_root, episode) the model records are read from -- never
    the episode name alone, and never ``--project-root`` (that stays the prompt/tool resolution root).
    Evidence that the manifest belongs to these roots, any one of which puts it in scope:
      * ``generated_by`` is the nalu builder;
      * the manifest file, or a task's ``prompt_file`` (resolved like the gates resolve it), lies under
        ``WORK_ROOT``; it must then lie in that root's own ``<episode>/`` directory;
      * ``production_scope`` (written by build_nalu_preproduction) declares line ``nalu`` -- its
        runtime_root, work_root and episode must equal the roots/episode in effect, else the manifest
        was built for another runtime and is refused (it cannot be judged with these records).
    A ``production_scope`` naming another line together with nalu evidence is a conflict and refused,
    so renaming ``generated_by`` or relabelling the scope cannot move a nalu manifest out of the check.
    Without any evidence the manifest is another line's (same episode id or not) and None is returned:
    it is judged by its own line's gates, not against this runtime's lock.
    """
    runtime = Path(vm._np.RUNTIME_ROOT).expanduser().resolve()
    work = Path(vm._np.WORK_ROOT).expanduser().resolve()
    episode = manifest.get("episode")
    effective = {"line": NALU_SCOPE_LINE, "runtime_root": str(runtime), "work_root": str(work), "episode": episode}
    evidence: list[str] = ["generated_by"] if nalu_built else []
    located: list[tuple[str, Path, Any]] = [("manifest_path", Path(manifest_path), episode)]
    for task in manifest.get("tasks") or []:
        if task.get("prompt_file"):
            located.append((f"task:{task.get('task_key')}.prompt_file", resolve(str(task["prompt_file"])),
                            episode or task.get("episode")))
    wrong_dir: list[str] = []
    for label, path, owner in located:
        try:
            relative = path.expanduser().resolve().relative_to(work)
        except ValueError:
            continue
        evidence.append(f"{label}_under_work_root")
        if not relative.parts or relative.parts[0] != owner:
            wrong_dir.append(f"{label}={path}")
    if wrong_dir:
        raise vm.VideoModelSelectionError(
            "VIDEO_MODEL_SCOPE_EPISODE_MISMATCH", episode=episode, expected=str(work / str(episode)),
            actual=wrong_dir, source="nalu work root", files=[manifest_path],
            detail="a file under the nalu work root lies outside this episode's own directory")
    declared = manifest.get("production_scope")
    if declared is not None:
        if not isinstance(declared, dict):
            raise vm.VideoModelSelectionError("VIDEO_MODEL_SCOPE_INVALID", episode=episode, expected=effective,
                                              actual=declared, source="manifest.production_scope",
                                              files=[manifest_path])
        if declared.get("line") != NALU_SCOPE_LINE:
            if evidence:
                raise vm.VideoModelSelectionError(
                    "VIDEO_MODEL_SCOPE_CONFLICT", episode=episode, expected=effective, actual=declared,
                    source="manifest.production_scope", files=[manifest_path],
                    detail="declares another production line but belongs to the nalu roots by " + ",".join(evidence))
            return None

        def same_root(value: Any, root: Path) -> bool:
            return isinstance(value, str) and bool(value) and Path(value).expanduser().resolve() == root
        wrong = [key for key, ok in (("runtime_root", same_root(declared.get("runtime_root"), runtime)),
                                     ("work_root", same_root(declared.get("work_root"), work)),
                                     ("episode", declared.get("episode") == episode)) if not ok]
        if wrong:
            raise vm.VideoModelSelectionError(
                "VIDEO_MODEL_SCOPE_MISMATCH", episode=episode, expected=effective, actual=declared,
                source="manifest.production_scope vs nalu_paths", files=[manifest_path],
                detail="mismatched: " + ",".join(wrong) + "; this manifest's model records live elsewhere")
        evidence.append("declared_production_scope")
    if not evidence:
        return None
    return {**effective, "evidence": evidence}


def require_episode_video_model(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any] | None:
    """K145: every model this manifest would send must be the episode's recorded nalu model.

    The episode lock / editorial manifest (lines/nalu/runtime/tools/nalu_video_model.py, roots from
    nalu_paths) is the selection; the manifest's format_contract, allowed_video_models and each task's
    ``model`` -- the value POSTed as the request's ``model`` -- must all equal it.  Only a manifest bound
    to these roots (nalu_production_scope) is judged against them; inside that scope an episode without a
    record, or with an unreadable, conflicting or foreign-episode record, is refused, and so is a task row
    declaring another episode than the manifest's.  Manifests of other lines -- even with the same episode
    id -- are left to their own gates.
    """
    nalu_built = str(manifest.get("generated_by") or "").startswith(NALU_BUILDER_ID_PREFIX)
    tools_dir = str(ENGINE_ROOT / "lines/nalu/runtime/tools")
    added = tools_dir not in sys.path
    if added:
        sys.path.append(tools_dir)
    try:
        import nalu_video_model as _vm
    except ImportError:
        if nalu_built:
            raise
        return None
    finally:
        if added and tools_dir in sys.path:
            sys.path.remove(tools_dir)
    if nalu_production_scope(manifest, manifest_path, _vm, nalu_built) is None:
        return None
    tasks = manifest.get("tasks") or []
    by_episode: dict[str, list[dict[str, Any]]] = {}
    if manifest.get("episode") and tasks:
        # the manifest's episode is the one being resolved; a row naming another is refused, not regrouped
        by_episode[str(manifest["episode"])] = list(tasks)
    else:
        for task in tasks:
            by_episode.setdefault(str(task.get("episode") or ""), []).append(task)
    checked = {}
    for episode, rows in by_episode.items():
        checked[episode] = _vm.check_task_models(
            episode, tasks=rows, format_contract=manifest.get("format_contract"),
            allowed_video_models=manifest.get("allowed_video_models"), manifest_path=manifest_path)
    return checked or None


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
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".part", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
        "speaker_voice_contract": task.get("speaker_voice_contract")
        or (task.get("machine_contract") or {}).get("speaker_voice_contract"),
        "character_entities": task.get("character_entities")
        or (task.get("machine_contract") or {}).get("character_entities"),
        "visual_culture_contract": task.get("visual_culture_contract")
        or (task.get("machine_contract") or {}).get("visual_culture_contract"),
        "model": task.get("model"),
        "duration": task.get("duration_seconds"),
        "aspect_ratio": task.get("aspect_ratio"),
        "resolution": task.get("resolution"),
        "generation_audio_profile_id": task.get("generation_audio_profile_id"),
        "audio_profile_binding": task.get("audio_profile_binding"),
        "incoming_transition_contract": (task.get("machine_contract") or {}).get("incoming_transition_contract")
        or task.get("incoming_transition_contract"),
        "outgoing_transition_contract": (task.get("machine_contract") or {}).get("outgoing_transition_contract")
        or task.get("outgoing_transition_contract"),
        "start_frame_semantic_contract": (task.get("machine_contract") or {}).get("start_frame_semantic_contract")
        or task.get("start_frame_semantic_contract"),
        "opening_anchor_contract": (task.get("machine_contract") or {}).get("opening_anchor_contract")
        or task.get("opening_anchor_contract"),
        "internal_transition_contracts": (task.get("machine_contract") or {}).get("internal_transition_contracts")
        or task.get("internal_transition_contracts")
        or [],
        "event_boundary_decision": (task.get("machine_contract") or {}).get("event_boundary_decision")
        or task.get("event_boundary_decision"),
        "persistent_state_contract": (task.get("machine_contract") or {}).get("persistent_state_contract")
        or task.get("persistent_state_contract"),
        "shot_state_contracts": (task.get("machine_contract") or {}).get("shot_state_contracts")
        or task.get("shot_state_contracts")
        or [],
    }
    transport = reference_transport(task)
    if transport:
        # Only present when compression applies, so every under-limit task keeps its fingerprint.
        contract["reference_transport"] = transport
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode("utf-8")).hexdigest()


# All reference images go base64 inside ONE JSON POST.  Large bodies die at the edge: 2026-09-21
# 12/12 Broken pipe/524 at concurrency 6, and 2026-10-01 E10-VU-020 (7 refs, 37 MB raw ≈ 51 MB
# base64) hit HTTP 524 twice -- the second one charged 160 credits with no task id.  Over the limit
# every reference is registered through the existing asset service (upload_giggle_asset, the same
# path audio references already use) and transported as an {"asset_id": ...} entry, which is what
# giggle_api_client.generate_omni_video already accepts via --image-asset-id.  The files on disk
# (and reference_sha256) are unchanged, and the transport is part of the fingerprint so an
# asset-id submission never collides with an earlier, base64 one for the same unit.  Line-owner
# order seq=21 (Roger 2026-10-01); asset transport 2026-10-02.
REFERENCE_PAYLOAD_RAW_LIMIT_BYTES = int(os.environ.get("GIGGLE_REFERENCE_PAYLOAD_LIMIT_BYTES") or 15_000_000)
REFERENCE_JPEG_TRANSPORT = "JPEG_Q90_V1"
REFERENCE_ASSET_TRANSPORT = "ASSET_ID_V1"
#: Token recorded in the transaction intent so recovery/audit can name the over-limit transport.
REFERENCE_IMAGE_ASSET_IDS_KEY = "reference_image_asset_ids"


def reference_transport(task: dict[str, Any]) -> str | None:
    total = 0
    for value in task.get("reference_images") or []:
        path = resolve(value)
        if path.is_file():
            total += path.stat().st_size
    return REFERENCE_ASSET_TRANSPORT if total > REFERENCE_PAYLOAD_RAW_LIMIT_BYTES else None


def reference_image_payload(task: dict[str, Any]) -> list[dict[str, str]]:
    """Reference-image transport for one task; also records registered ids on the task.

    Over the raw limit the images travel as registered ``{"asset_id": ...}`` entries; at or below
    it they stay base64 exactly as before.  Callers that need the ids for the transaction intent
    use :func:`_reference_image_transport`, which returns both.
    """
    return _reference_image_transport(task)[0]


def _reference_image_transport(task: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    """Build the ``images`` payload and, for the asset transport, the ordered asset ids.

    Idempotent-safe: a re-entry that already registered this task's references (e.g. across a
    second wave pass over the same task dict) reuses the recorded ids instead of re-uploading the
    same bytes.  A task hard-bound to a task id never reaches here -- ``prior_bound`` returns first.
    """
    paths = [str(resolve(value)) for value in task["reference_images"]]
    if reference_transport(task) != REFERENCE_ASSET_TRANSPORT:
        return _image_list(paths), []
    cached = task.get(REFERENCE_IMAGE_ASSET_IDS_KEY)
    if isinstance(cached, list) and len(cached) == len(paths) and all(str(v).strip() for v in cached):
        return [{"asset_id": str(value)} for value in cached], [str(value) for value in cached]
    asset_ids = [str(_registered_asset(path)["asset_id"]) for path in paths]
    task[REFERENCE_IMAGE_ASSET_IDS_KEY] = asset_ids
    return [{"asset_id": value} for value in asset_ids], list(asset_ids)


def validate_submission_camera(task: dict[str, Any]) -> dict[str, Any]:
    unit = grouped_sequence_unit(task)
    if unit.get("camera_scope_policy") == "PER_SHOT_EXPLICIT":
        unit["model"] = task.get("model")
        unit["duration_seconds"] = task.get("duration_seconds")
        validate_camera_sequence([unit])
        return {}
    machine = task.get("machine_contract") or {}
    return validate_camera_plan(machine.get("camera_plan") or task.get("camera_plan"),
                                source_id=str(task.get("task_key")))


def validate_grouped_creative_task(task: dict[str, Any], prompt_text: str) -> None:
    if not task.get("semantic_video_unit"):
        return
    opening_failures = validate_opening_anchor_chain(task)
    if opening_failures:
        raise ValueError(";".join(opening_failures))
    machine = task.get("machine_contract") or {}
    camera_plan = validate_submission_camera(task)
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
    expected_prompt = compile_model_prompt(provider_prompt_unit(task))
    if prompt_text != expected_prompt:
        raise ValueError(
            f"{task.get('task_key')} provider prompt is not the exact output of the current "
            f"{task.get('model')} compiler"
        )
    scope_report = validate_provider_scope_projection(task, prompt_text=prompt_text, model=str(task.get("model") or ""))
    if scope_report.get("status") == "FAIL":
        raise ValueError(";".join(scope_report.get("failures") or []))


def _face_crop_references(task: dict[str, Any]) -> list[str]:
    episode = str(task.get("episode") or "")
    if not episode or str(task.get("model") or "") != "MiniMax-H3":
        return []
    try:
        from tools.original_identity_authority import episode_pixel_crop_transport_paths
    except ModuleNotFoundError:
        from original_identity_authority import episode_pixel_crop_transport_paths
    try:
        crops = episode_pixel_crop_transport_paths(episode)
    except ModuleNotFoundError:  # no nalu series scope on this line
        return []
    return [str(p) for p in task.get("reference_images") or [] if str(p) in crops]


def provider_prompt_unit(task: dict[str, Any]) -> dict[str, Any]:
    """The compiler input the paid boundary re-renders a grouped task's prompt from.

    Lines that materialise references after their grouped compile (NALU attaches identity plates
    in its finalizer) render the final provider prompt from this same function, so the text they
    write is byte-identical to the boundary's expectation."""
    machine = task.get("machine_contract") or {}
    prompt_unit = grouped_sequence_unit(task)
    prompt_unit["model"] = task.get("model")
    # English-dialogue episodes carry dialogue_language on the task (absent == zh); without it the
    # paid-boundary / finalizer re-render tagged English lines <d>[Chinese] (Twelve Gazes E01-VU-011)
    if task.get("dialogue_language") or machine.get("dialogue_language"):
        prompt_unit["dialogue_language"] = task.get("dialogue_language") or machine.get("dialogue_language")
    prompt_unit["h3_prompt_profile"] = task.get("h3_prompt_profile")
    # opt-in DIRECTOR_PROMPT_V2 (generation contract h3_prompt_style): absent on every other task, so their
    # compiler input stays byte-identical
    if task.get("h3_prompt_style") or machine.get("h3_prompt_style"):
        prompt_unit["h3_prompt_style"] = task.get("h3_prompt_style") or machine.get("h3_prompt_style")
    # opt-in Chinese constraint sentences (generation contract h3_constraint_language "zh"; A/B variant tasks)
    if task.get("h3_constraint_language") or machine.get("h3_constraint_language"):
        prompt_unit["h3_constraint_language"] = task.get("h3_constraint_language") or machine.get("h3_constraint_language")
    # declared camera lock (h3_camera_lock "strict" | "standard"; absent = renderer default)
    if task.get("h3_camera_lock") or machine.get("h3_camera_lock"):
        prompt_unit["h3_camera_lock"] = task.get("h3_camera_lock") or machine.get("h3_camera_lock")
    prompt_unit["duration_seconds"] = task.get("duration_seconds")
    prompt_unit["resolution"] = task.get("resolution")
    prompt_unit["aspect_ratio"] = task.get("aspect_ratio")
    prompt_unit["character_entities"] = machine.get("character_entities") or task.get("character_entities")
    prompt_unit["visual_culture_contract"] = machine.get("visual_culture_contract") or task.get("visual_culture_contract")
    prompt_unit["speaker_voice_contract"] = machine.get("speaker_voice_contract") or task.get("speaker_voice_contract")
    prompt_unit["provider_scope_projection"] = task.get("provider_scope_projection")
    # H3 speaker -> SUBJECT_n binding (h3_crossmodal_speaker_gate); absent for SD2 tasks
    if task.get("provider_entity_token_map"):
        prompt_unit["provider_entity_token_map"] = task.get("provider_entity_token_map")
    # Failed-only rerolls carry an explicit full performance rewrite.  Keep it
    # in the compiler input so the paid-boundary byte comparison validates the
    # same prompt that was registered for this new fingerprint.
    prompt_unit["reroll_performance_directive"] = task.get("reroll_performance_directive")
    # E12 2026-10-30: a verified PIXEL_CROP identity transport is a face crop; the H3 renderers lock only
    # face/age/hair from it.  Absent unless the task actually sends one, so other prompts are unchanged.
    face_only = _face_crop_references(task)
    if face_only:
        prompt_unit["face_only_identity_references"] = face_only
    sequence_by_path = {
        str(row.get("path") or ""): row
        for row in task.get("reference_image_sequence") or []
        if row.get("path") and str(row.get("entity_id") or "").startswith("CHAR-")
    }
    prompt_unit["reference_images"] = [
        {
            **sequence_by_path.get(str(path), {}),
            "path": path,
            "role": role,
        }
        for path, role in zip(
            task.get("reference_images") or [],
            task.get("reference_roles") or ["SEMANTIC_REFERENCE"] * len(task.get("reference_images") or []),
        )
    ]
    return prompt_unit
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
    for field in ("camera_scope_policy", "camera_time_coordinate", "timeline_policy"):
        source_value = machine.get(field)
        task_value = task.get(field)
        if source_value is not None and task_value is not None and source_value != task_value:
            raise ValueError(f"SOURCE_POLICY_TRANSPORT_MISMATCH:{field}")
    return {
        "unit_id": task.get("unit_id") or task.get("task_key"),
        # Shared execution-plan recompilation at the final paid boundary is
        # model-aware.  Keep transport identity in this projection; otherwise
        # the compact SD2/H3 coverage gate sees an empty model and fails for
        # the wrong reason after the exact compiler has already passed.
        "model": task.get("model") or machine.get("model"),
        "resolution": task.get("resolution") or machine.get("resolution"),
        "aspect_ratio": task.get("aspect_ratio") or machine.get("aspect_ratio"),
        # Dialogue-safe window recompilation is duration dependent.  Dropping
        # this field at the final paid boundary turns a real dialogue unit into
        # a false "no dialogue" result and can either block a valid task or,
        # worse, bypass the exact safe-cut contract.
        "duration_seconds": task.get("duration_seconds")
        or machine.get("duration_seconds"),
        # Shared Action-IR duration authority must survive the paid-boundary
        # task projection.  Falling back to source beat spans alone can turn a
        # valid provider integer duration plus its authorized tail handle into
        # a false DURATION_EXCEEDS_AUTHORIZED_CONTENT rejection.
        "source_duration_seconds": task.get("source_duration_seconds")
        or machine.get("source_duration_seconds"),
        "authorized_content_seconds": task.get("authorized_content_seconds")
        or machine.get("authorized_content_seconds"),
        "authorized_tail_handle_seconds": task.get("authorized_tail_handle_seconds")
        if task.get("authorized_tail_handle_seconds") is not None
        else machine.get("authorized_tail_handle_seconds"),
        "h3_prompt_profile": task.get("h3_prompt_profile"),
        "scene_id": task.get("scene_id") or machine.get("scene_id"),
        "scene_first_unit": machine.get("scene_first_unit")
        if "scene_first_unit" in machine else task.get("scene_first_unit"),
        "opening_anchor_contract": machine.get("opening_anchor_contract")
        or task.get("opening_anchor_contract"),
        "event_boundary_decision": machine.get("event_boundary_decision")
        or task.get("event_boundary_decision"),
        "persistent_state_contract": machine.get("persistent_state_contract")
        or task.get("persistent_state_contract"),
        "shot_state_contracts": machine.get("shot_state_contracts")
        or task.get("shot_state_contracts")
        or [],
        "continuity_event_contract_required": machine.get("continuity_event_contract_required")
        if "continuity_event_contract_required" in machine
        else task.get("continuity_event_contract_required"),
        "wardrobe_contract": machine.get("wardrobe_contract") or task.get("wardrobe_contract"),
        "speaker_voice_contract": machine.get("speaker_voice_contract")
        or task.get("speaker_voice_contract"),
        "dialogue_cut_safety": machine.get("dialogue_cut_safety") or task.get("dialogue_cut_safety"),
        "pose_transition_anchor_gate": machine.get("pose_transition_anchor_gate")
        or task.get("pose_transition_anchor_gate"),
        "camera_plan": (machine.get("camera_plan") if "camera_plan" in machine
                        else task.get("camera_plan")),
        # Camera scope and authored timing are part of the source contract;
        # preserve them through the final paid-boundary projection so the
        # downstream compiler cannot silently collapse per-shot camera plans
        # into a unit-wide default or stretch the authored timeline.
        "camera_scope_policy": machine.get("camera_scope_policy")
        if "camera_scope_policy" in machine else task.get("camera_scope_policy"),
        "camera_time_coordinate": machine.get("camera_time_coordinate")
        if "camera_time_coordinate" in machine else task.get("camera_time_coordinate"),
        "timeline_policy": machine.get("timeline_policy")
        if "timeline_policy" in machine else task.get("timeline_policy"),
        "ordered_prompt_specs": machine.get("ordered_prompt_specs") or task.get("ordered_prompt_specs") or [],
        "editorial_shot_ids": machine.get("editorial_shot_ids") or task.get("editorial_shot_ids") or [],
        "internal_transition_contracts": machine.get("internal_transition_contracts")
        or task.get("internal_transition_contracts")
        or [],
        # A grouping-plan unit names this boundary `transition_contract`; a paid
        # task carries it as `incoming_transition_contract`.  Accept both, or a
        # read-only neighbour loses its inbound and the slice looks unbound.
        "transition_contract": machine.get("incoming_transition_contract")
        or machine.get("transition_contract")
        or task.get("incoming_transition_contract")
        or task.get("transition_contract"),
        "incoming_transition_contract": machine.get("incoming_transition_contract")
        or machine.get("transition_contract")
        or task.get("incoming_transition_contract")
        or task.get("transition_contract"),
        "outgoing_transition_contract": machine.get("outgoing_transition_contract")
        or task.get("outgoing_transition_contract"),
        "action_classification": machine.get("action_classification")
        or task.get("action_classification"),
        "combat_or_chase": machine.get("combat_or_chase")
        if "combat_or_chase" in machine else task.get("combat_or_chase"),
        "fight_or_chase": machine.get("fight_or_chase")
        if "fight_or_chase" in machine else task.get("fight_or_chase"),
        "combat_classification_override": machine.get("combat_classification_override")
        or task.get("combat_classification_override"),
        "combat_source_authority": machine.get("combat_source_authority")
        or task.get("combat_source_authority"),
        "combat_choreography_contract": machine.get("combat_choreography_contract")
        or task.get("combat_choreography_contract"),
        "combat_action_library_binding": machine.get("combat_action_library_binding")
        or task.get("combat_action_library_binding"),
        "interaction_topology_contract": machine.get("interaction_topology_contract")
        or task.get("interaction_topology_contract"),
        "performance_tempo_contract": machine.get("performance_tempo_contract")
        or task.get("performance_tempo_contract"),
        "h3_provider_english_contract": machine.get("h3_provider_english_contract")
        or task.get("h3_provider_english_contract"),
        "reference_exclusion_recomposition_rule": machine.get("reference_exclusion_recomposition_rule")
        or task.get("reference_exclusion_recomposition_rule"),
        "reference_images": task.get("reference_images") or [],
        "start_frame_semantic_contract": machine.get("start_frame_semantic_contract")
        or task.get("start_frame_semantic_contract"),
        "background_ecology_contract": machine.get("background_ecology_contract")
        or task.get("background_ecology_contract"),
        "weather_visibility_contract": machine.get("weather_visibility_contract")
        or task.get("weather_visibility_contract"),
        "native_audio_contract": machine.get("native_audio_contract")
        or task.get("native_audio_contract"),
        "h3_ref2va_contract": machine.get("h3_ref2va_contract")
        or task.get("h3_ref2va_contract"),
    }


def scoped_sequence_with_global_neighbours(
    manifest: dict[str, Any], submitted: list[dict[str, Any]]
) -> tuple[list[list[dict[str, Any]]], dict[str, Any]]:
    """Splice READ-ONLY global neighbours around a scoped repair wave.

    A partial repair batch is a non-contiguous slice of the episode, so its
    first and last units are NOT real episode endpoints.  Skipping the
    cross-unit validators hides the boundaries the wave actually breaks:
    a repainted camera can now repeat the outgoing motion of a neighbour it
    never POSTs, and a rewritten transition can disagree with the neighbour's
    terminal state.  The fix is to restore the missing context, not to waive
    the check.

    Neighbours come from the sha-bound global grouping plan recorded by
    ``build_nalu_preproduction`` in ``staged_generation_scope``.  They are
    projected with the same ``grouped_sequence_unit`` shape as subtasks, are
    only ever read, and never enter ``manifest["tasks"]`` — so a repair wave
    still POSTs exactly the units it was authorized to POST.

    Returns (ordered SEGMENTS covering the wave plus its immediate neighbours,
    report).  Two wave units whose neighbour spans touch or overlap share one
    segment; two that don't (E12 VU-012/VU-028/VU-051, 2026-10-28: 16 and 23
    units apart) must NOT be concatenated into one flat list — a pairwise
    validator walking that list would check a transition/camera-rotation
    adjacency between two neighbours that are not actually adjacent in the
    episode (it raised on "E12-VU-013->E12-VU-027 transition_contract unit
    binding mismatch", neither of which was even in the wave).  Each caller
    must validate every segment independently.  Empty list with
    ``status=MISSING_GLOBAL_PLAN`` when no bound plan is available; callers
    fall back to per-task validation only.
    """
    scope = manifest.get("staged_generation_scope") or {}
    report: dict[str, Any] = {
        "schema": "qingshan.staged_scope_neighbour_context.v1",
        "neighbour_units_read_only": [],
    }
    if not submitted:
        report["status"] = "NO_UNITS"
        return [], report
    plan_value = scope.get("global_grouping_plan")
    if not plan_value:
        report["status"] = "MISSING_GLOBAL_PLAN"
        return [], report
    plan_path = resolve(plan_value)
    if not plan_path.is_file():
        raise RuntimeError(f"staged_generation_scope global plan is missing: {plan_value}")
    actual_sha = sha256(plan_path)
    expected_sha = str(scope.get("global_grouping_plan_sha256") or "")
    if expected_sha and actual_sha != expected_sha:
        raise RuntimeError(
            "staged_generation_scope global plan changed after the batch was built "
            f"({plan_value}): expected {expected_sha}, found {actual_sha}"
        )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_units = plan.get("units") or []
    order = {str(unit.get("unit_id") or ""): index for index, unit in enumerate(plan_units)}
    missing = [str(unit.get("unit_id")) for unit in submitted
               if str(unit.get("unit_id") or "") not in order]
    if missing:
        raise RuntimeError(
            f"staged wave units are absent from the bound global plan: {','.join(missing)}"
        )

    # The grouping plan carries a neighbour's camera and transition but not its
    # ordered_prompt_specs, and the boundary check binds the target requirements
    # to the neighbour's first/last beat.  A separate prompt-spec context plan
    # (recorded by the builder) supplies only that missing field; per-unit
    # camera/scene/transition always come from the grouping plan.
    spec_context: dict[str, dict[str, Any]] = {}
    context_value = scope.get("global_context_units")
    if context_value:
        context_path = resolve(context_value)
        if not context_path.is_file():
            raise RuntimeError(f"staged_generation_scope context plan is missing: {context_value}")
        expected_context_sha = str(scope.get("global_context_units_sha256") or "")
        actual_context_sha = sha256(context_path)
        if expected_context_sha and actual_context_sha != expected_context_sha:
            raise RuntimeError(
                "staged_generation_scope context plan changed after the batch was built "
                f"({context_value}): expected {expected_context_sha}, found {actual_context_sha}"
            )
        for row in (json.loads(context_path.read_text(encoding="utf-8")).get("units")
                    or json.loads(context_path.read_text(encoding="utf-8")).get("tasks") or []):
            uid = str(row.get("unit_id") or row.get("task_key") or "")
            if uid:
                spec_context[uid] = row

    def neighbour_projection(index: int) -> dict[str, Any]:
        candidate = copy.deepcopy(plan_units[index])
        if not candidate.get("ordered_prompt_specs"):
            extra = spec_context.get(str(candidate.get("unit_id") or "")) or {}
            for field in ("ordered_prompt_specs", "duration_seconds", "aspect_ratio",
                          "resolution", "model", "character_entities"):
                if extra.get(field) is not None and candidate.get(field) is None:
                    candidate[field] = copy.deepcopy(extra[field])
        # The grouping plan stores the same contract fields a task carries, but
        # grouped_sequence_unit() reads most of them from ``machine_contract``
        # (that is where the paid boundary keeps them).  Project the neighbour
        # through the same shape so a neighbour and a real task are validated
        # by identical code paths rather than a lookalike projection.
        return grouped_sequence_unit({
            "semantic_video_unit": True,
            "task_key": candidate.get("unit_id"),
            "machine_contract": candidate,
        })

    wave = sorted(submitted, key=lambda unit: order[str(unit["unit_id"])])
    wave_by_id = {str(unit["unit_id"]): unit for unit in wave}
    # Each wave unit needs its immediate predecessor/successor index (clipped to
    # the plan's bounds).  Spans that touch or overlap share one contiguous
    # segment; spans that don't stay in separate segments, so the pairwise
    # validators never see two neighbours as adjacent when the episode itself
    # does not place them next to each other.
    spans = []
    for unit in wave:
        index = order[str(unit["unit_id"])]
        spans.append([max(index - 1, 0), min(index + 1, len(plan_units) - 1)])
    spans.sort()
    merged: list[list[int]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    segments: list[list[dict[str, Any]]] = []
    neighbour_ids: list[str] = []
    for lo, hi in merged:
        segment: list[dict[str, Any]] = []
        for index in range(lo, hi + 1):
            uid = str(plan_units[index].get("unit_id") or "")
            if uid in wave_by_id:
                segment.append(wave_by_id[uid])
            else:
                projected = neighbour_projection(index)
                segment.append(projected)
                neighbour_ids.append(projected["unit_id"])
        segments.append(segment)
    report.update({
        "status": "VALIDATED_WITH_NEIGHBOURS",
        "global_grouping_plan": plan_value,
        "global_grouping_plan_sha256": actual_sha,
        "submitted_unit_count": len(wave),
        "neighbour_units_read_only": sorted(set(neighbour_ids)),
        "sequence_unit_count": sum(len(segment) for segment in segments),
        "segment_count": len(segments),
    })
    return segments, report


def uses_structured_role_gate(task: dict[str, Any], prompt_text: str) -> bool:
    """Return true for compiler-native prompts that intentionally omit role dumps."""
    shared_ir_prompt = (
        "【任务】" in prompt_text and "【时间轴】" in prompt_text
    ) or (
        "subject_definitions:" in prompt_text and "retention_analysis:" in prompt_text
    )
    # DIRECTOR_PROMPT_V2 is compiler-native too (exact-compiler check + semantic receipt below)
    director_v2 = (str(task.get("h3_prompt_style") or "").strip().upper() == "DIRECTOR_PROMPT_V2"
                   and is_director_v2_text(prompt_text))
    official_h3_ref2va = (
        str(task.get("model") or "").lower() in {"minimax-h3", "h3"}
        and task.get("h3_prompt_profile") == "H3_OFFICIAL_REF2VA_V1"
    )
    return shared_ir_prompt or official_h3_ref2va or director_v2


def transaction_path(transaction_dir: Path, task: dict[str, Any]) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(task.get("task_key") or "")):
        raise ValueError("task_key must be a portable identifier, not a path")
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
    # Shared-IR provider prompts deliberately do not serialize the legacy
    # ROLE_LOCK/schema dump.  Character disambiguation remains fail-closed in
    # the structured graph, and the exact current compiler plus its rendered
    # semantic-coverage receipt are checked below.  Requiring the old prose
    # block here would contradict the provider-boundary contract and force
    # internal machine text back into both SD2 and H3 prompts.
    role_failures = (
        validate_role_semantics_structure(task)
        if uses_structured_role_gate(task, prompt_text)
        else validate_role_semantics(task, prompt_text)
    )
    if role_failures:
        raise ValueError(
            f"{task['task_key']} character-role ambiguity gate failed: "
            + ",".join(role_failures)
        )
    if task.get("native_dialogue_required") is True and str(task.get("model") or "") in {
        "MiniMax-H3", "minimax-h3", "h3", "seedance-2.0-pro"
    }:
        voice_contract = task.get("speaker_voice_contract") or (
            task.get("machine_contract") or {}
        ).get("speaker_voice_contract") or {}
        if voice_contract.get("schema") != SPEAKER_VOICE_POLICY_VERSION or voice_contract.get("status") != "PASS":
            raise ValueError(f"{task['task_key']} missing PASS canonical speaker_voice_contract")
        expected_speakers = []
        for row in task.get("dialogue") or []:
            speaker = str(row.get("speaker") or "").strip()
            if speaker and speaker not in expected_speakers:
                expected_speakers.append(speaker)
        bindings = voice_contract.get("bindings") or []
        if [str(row.get("speaker") or "") for row in bindings] != expected_speakers:
            raise ValueError(f"{task['task_key']} speaker_voice_contract dialogue coverage mismatch")
        english_machine_rescue = task.get("h3_prompt_profile") in {
            "H3_ENGLISH_MACHINE_AUDIO_RESCUE_V1", "H3_OFFICIAL_REF2VA_V1",
            "H3_POSITIVE_SINGLE_SUBJECT_V1", "H3_TIGHT_POV_SINGLE_SUBJECT_V1",
        }
        for row in bindings:
            slot = str(row.get("audio_slot") or "")
            if not slot:
                raise ValueError(f"{task['task_key']} canonical speaker audio slot missing")
            # H3's last-attempt English-machine rescue intentionally removes
            # canonical Chinese names and verbose voice-slot prose from the
            # provider prompt because H3 may vocalize them.  Voice identity is
            # still transported by the bound reference audio URLs, while the
            # provider-facing prompt uses opaque entity tokens plus exact
            # <d>[Chinese] dialogue literals.
            # the H3 renderer serializes the canonical @音频N slot in its English form @AudioN
            prompt_slot = (re.sub(r"^@音频(\d+)$", r"@Audio\1", slot)
                           if str(task.get("model") or "").lower() in {"minimax-h3", "h3"} else slot)
            if not english_machine_rescue and prompt_slot not in prompt_text:
                raise ValueError(f"{task['task_key']} canonical speaker audio slot missing from prompt")
        if english_machine_rescue:
            if not task.get("provider_entity_token_map"):
                raise ValueError(f"{task['task_key']} English rescue lacks provider entity token map")
            outside_dialogue = re.sub(r"<d>\[Chinese\].*?</d>", "", prompt_text, flags=re.DOTALL)
            if re.search(r"[\u3400-\u9fff]", outside_dialogue):
                raise ValueError(f"{task['task_key']} English rescue exposes CJK outside dialogue")
        if str(task.get("model") or "").lower() in {"minimax-h3", "h3"}:
            expected_transport = [str(row.get("voice_reference_url") or "") for row in bindings]
            if expected_transport != list(task.get("reference_audio_urls") or []):
                raise ValueError(f"{task['task_key']} H3 speaker voice URL transport mismatch")
        else:
            expected_transport = [str(row.get("voice_reference_asset_id") or "") for row in bindings]
            if expected_transport != list(task.get("reference_audio_asset_ids") or []):
                raise ValueError(f"{task['task_key']} SD2 speaker voice asset transport mismatch")
    validate_grouped_creative_task(task, prompt_text)
    # Final paid-submission boundary: SD2 required fields must survive all the
    # way from the writer contract into the exact provider-facing prompt.
    # Earlier compiler/QA reports are evidence, not an authorization bypass.
    if str(task.get("model") or "").strip().lower() == "seedance-2.0-pro":
        coverage = validate_required_sd2_field_coverage(
            grouped_sequence_unit(task), prompt_text
        )
        if coverage.get("status") != "PASS":
            raise ValueError(
                f"{task['task_key']} SD2 required prompt fields failed at paid boundary: "
                + ",".join(coverage.get("failures") or [])
            )
        episode_value = episode_number(task.get("episode"))
        if episode_value is not None and episode_value >= 50:
            binding = task.get("audio_profile_binding")
            profile_id = str(task.get("generation_audio_profile_id") or "")
            if not isinstance(binding, dict) or binding.get("automatic") is not True:
                raise ValueError(f"{task['task_key']} missing automatic writer/director audio-profile binding")
            if binding.get("resolved_audio_profile_id") != profile_id:
                raise ValueError(f"{task['task_key']} audio-profile ID/binding mismatch")
            allowed_profiles = {
                "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM",
                "NATIVE_MULTIMODAL_SELECTIVE_BGM",
                "LAYERED_POST_WITH_BGM",
            }
            if profile_id not in allowed_profiles:
                raise ValueError(f"{task['task_key']} unsupported generation audio profile: {profile_id}")
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
    duration = task.get("duration_seconds")
    if type(duration) is not int or not minimum_duration <= duration <= 15:
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
        # Recover a failed secondary receipt write without another paid POST.
        if row.get("receipt") and row.get("provider_response"):
            receipt = resolve(row["receipt"])
            if not receipt.is_file():
                atomic_json(receipt, row["provider_response"])
        return {
            "task_key": task["task_key"], "task_id": row["task_id"], "state": "remote_running",
            "receipt": row.get("receipt"), "transaction": portable(path), "recovered_from_transaction": True,
        }
    if row.get("state") not in {"VERIFIED_ZERO_RETRYABLE"}:
        raise RuntimeError(f"{task['task_key']} blocked by transaction state {row.get('state')}")
    return None


def _batch_requires_serial_tail_chain(tasks: list[dict[str, Any]]) -> bool:
    """Return true only for a batch whose every unit needs a predecessor tail.

    A concurrency of one is a correctness requirement only when each submitted
    unit is chained to an exact predecessor tail frame.  Independent units must
    be submitted in parallel; task IDs and the durable transaction store keep
    their results distinguishable.  Mixed batches are intentionally rejected
    instead of silently serialising independent work.
    """
    if not tasks:
        return False
    return all(
        bool((task.get("action_sequence_contract") or {}).get("depends_on_task"))
        and bool(task.get("predecessor_tail_frame"))
        for task in tasks
    )


def prompt_scope_gate_active(task: dict[str, Any]) -> bool:
    episode = task.get("episode") or task.get("unit_id") or task.get("task_key")
    return shot_scope_active_for(episode, task.get("model"))


def submitter_module_audit() -> list[dict[str, Any]]:
    return loaded_module_audit(ENGINE_ROOT, extra=("__main__",) if __name__ == "__main__" else ())


def pre_intent_block_path(transaction_dir: Path, task: dict[str, Any]) -> Path:
    # A sub-directory, so nothing that globs transaction_dir/*.json mistakes it for a transaction.
    return transaction_dir / "_pre_intent_blocks" / transaction_path(transaction_dir, task).name


def run_prompt_scope_gate(task: dict[str, Any], prompt_text: str, transaction_dir: Path) -> dict[str, Any]:
    """Fresh check bound to the exact prompt text + reference SHAs; never reuses an older PASS."""
    result = check_prompt_scope_conflicts(task, prompt_text)
    audit = submitter_module_audit()
    if result.get("status") == "PASS" and result.get("prompt_sha256") == task["prompt_sha256"]:
        return {"gate": result, "loaded_modules": audit}
    failures = list(result.get("failures") or [])
    if result.get("status") == "PASS":
        failures.append("PROMPT_SCOPE_GATE_PROMPT_SHA_NOT_BOUND")
    # Same convention as every other pre-intent failure: no transaction file is written, so
    # classify_failures() reports submit_failed_before_intent / NOT_CHARGED_NO_INTENT_RECORDED.
    atomic_json(pre_intent_block_path(transaction_dir, task), {
        "schema": "qingshan.giggle_video_submit_pre_intent_block.v1",
        "task_key": task["task_key"], "submission_fingerprint": task_fingerprint(task),
        "state": "BLOCKED_BEFORE_INTENT_PROMPT_SCOPE_CONFLICT",
        "status": "submit_failed_before_intent", "credit": 0,
        "credit_status": "NOT_CHARGED_NO_INTENT_RECORDED",
        "blocked_at": utc_now(), "prompt_sha256": task["prompt_sha256"],
        "reference_sha256": task["reference_sha256"], "model": task.get("model"),
        "prompt_scope_conflict_gate": {**result, "status": "FAIL", "failures": failures},
        "loaded_modules": audit,
    })
    raise PromptScopeGateBlocked(
        f"{task['task_key']} PROMPT_SCOPE_CONFLICT_GATE_FAILED (not charged, no intent recorded): "
        + ",".join(failures)
    )


def estimated_video_credits(task: dict[str, Any]) -> int:
    """Exposure a bound-but-unreconciled task presents to the episode cap (K111).

    Priced per the provider's own schedule, matching nalu_pipeline.video_task_credits:
    SD2 720p 20 credits/s; MiniMax-H3 768p 14 credits/s + 6 per task.  Over-estimating
    here would stop a healthy H3 episode early; under-estimating would hide exposure.
    """
    seconds = int(task.get("duration_seconds", 6))
    if str(task.get("model") or "") == "MiniMax-H3":
        return int(round(seconds * 14)) + 6
    return int(seconds * 20)


def live_bound_elsewhere(task: dict[str, Any], transaction_dir: Path) -> dict[str, Any] | None:
    """The task's live provider binding under ANOTHER fingerprint, as a recovered row (no POST).

    Lab E05 2026-10-26: a recompile drifted the VU-001 fingerprint (the episode-wide
    ``audio_profile_binding.generation_contract_sha256`` changed when VU-014 was rebuilt) while
    its redo was still rendering, and the store lookup above -- keyed by fingerprint -- let a
    second, byte-identical 48-credit task through.  A bound, not terminally failed take of the
    same task_key that is newer than the unit's last park is the take we already paid for: poll
    it.  Only an explicit ``supersedes_submission_fingerprints`` entry re-opens a POST."""
    declared = {str(v) for v in (task.get("supersedes_submission_fingerprints") or [])}
    episode = str(task.get("episode") or Path(transaction_dir).name)
    live = live_bindings(transaction_dir, str(task["task_key"]), root=ROOT, episode=episode,
                         exclude_fingerprints={task_fingerprint(task), *declared})
    if not live:
        return None
    first = live[0]
    return {
        "task_key": task["task_key"], "task_id": first["task_id"], "state": "remote_running",
        "receipt": first.get("receipt"), "transaction": portable(Path(first["transaction"])),
        "recovered_from_transaction": True,
        "recovered_via": "LIVE_BINDING_UNDER_OTHER_FINGERPRINT",
        "live_takes": [{k: row.get(k) for k in ("task_id", "submission_fingerprint", "bound_at", "request_sha256")}
                       for row in live],
    }


class KnowledgeLockGateBlocked(RuntimeError):
    """The task's locked knowledge no longer verifies; refused before intent, not charged."""


def knowledge_lock_check(task: dict[str, Any], transaction_dir: Path) -> dict[str, Any] | None:
    """None for a task without ``knowledge_lock`` (every task that never opted in)."""
    if not isinstance(task.get("knowledge_lock"), dict):
        return None
    try:
        from tools.collective_learning import runtime_wiring
    except ModuleNotFoundError:
        from collective_learning import runtime_wiring
    try:
        return runtime_wiring.check_before_send(task)
    except runtime_wiring.KnowledgeLockRefused as exc:
        # Same convention as the prompt-scope gate: evidence kept, no transaction file, no POST.
        atomic_json(pre_intent_block_path(transaction_dir, task), {
            "schema": "qingshan.giggle_video_submit_pre_intent_block.v1",
            "task_key": task["task_key"], "state": "BLOCKED_BEFORE_INTENT_KNOWLEDGE_LOCK_INVALID",
            "status": "submit_failed_before_intent", "credit": 0,
            "credit_status": "NOT_CHARGED_NO_INTENT_RECORDED", "blocked_at": utc_now(),
            "knowledge_lock": task.get("knowledge_lock"), "failures": str(exc),
        })
        raise KnowledgeLockGateBlocked(
            f"{task['task_key']} KNOWLEDGE_LOCK_GATE_FAILED (not charged, no intent recorded): {exc}") from exc


def record_knowledge_provider_request(task: dict[str, Any], payload: dict[str, Any], transaction: Path,
                                      intent: dict[str, Any]) -> None:
    """PROVIDER_REQUEST adoption receipts for the exact payload just sent.  Never raises: the
    provider binding above is already durable and must not be lost to a receipt write."""
    try:
        try:
            from tools.collective_learning import runtime_wiring
        except ModuleNotFoundError:
            from collective_learning import runtime_wiring
        rows = runtime_wiring.record_provider_request(task, payload)
        intent["knowledge_provider_request_receipts"] = [
            {"receipt_id": r["receipt_id"], "rule_id": r["rule_id"], "state": r["state"]} for r in rows]
    except Exception as exc:  # noqa: BLE001
        intent["knowledge_provider_request_receipts_error"] = f"{type(exc).__name__}:{exc}"[:500]
    atomic_json(transaction, intent)


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    prior = prior_bound(task, transaction_dir)
    if prior:
        return prior
    live = live_bound_elsewhere(task, transaction_dir)
    if live:
        return live
    try:
        from tools.episode_prompt_batch_gate import require_generation_batch
    except ModuleNotFoundError:
        from episode_prompt_batch_gate import require_generation_batch
    require_generation_batch(task, ROOT, artifact_kind='video_prompt')
    if sha256(resolve(task["prompt_file"])) != task["prompt_sha256"]:
        raise ValueError(f"{task['task_key']} prompt changed while waiting for submission")
    if len(task["reference_images"]) != len(task["reference_sha256"]):
        raise ValueError("reference count/SHA count mismatch at submission")
    for reference, expected in zip(task["reference_images"], task["reference_sha256"]):
        if sha256(resolve(reference)) != expected:
            raise ValueError(f"{task['task_key']} reference changed while waiting for submission")
    scope_evidence = None
    prompt_text = None
    if prompt_scope_gate_active(task):
        # Gate the exact string that is POSTed below; the PASS is bound to its SHA + reference SHAs.
        prompt_text = resolve(task["prompt_file"]).read_text(encoding="utf-8")
        scope_evidence = run_prompt_scope_gate(task, prompt_text, transaction_dir)
    transaction = transaction_path(transaction_dir, task)
    # Bind the fingerprint before any upload: task_fingerprint() reads reference_transport (the
    # transport mode) but never the registered ids, so it is stable across a registration retry.
    fingerprint = task_fingerprint(task)
    # Register over-limit references BEFORE the intent record.  A failed upload must not leave an
    # INTENT_RECORDED transaction (that would look like an in-flight submission and block recovery);
    # no POST is attempted, so the task is simply not charged and follows the pre-intent convention
    # (no transaction file -> classify_failures reports submit_failed_before_intent / NOT_CHARGED).
    images_payload, reference_image_asset_ids = _reference_image_transport(task)
    # Build the request BEFORE the intent record (plan §7.2).  Everything below
    # is local; nothing here can reach the provider.  The review binding is
    # checked against these exact values, and a refusal leaves no transaction,
    # so it is NOT_CHARGED_NO_INTENT_RECORDED with zero POSTs.
    payload = {
        "prompt": prompt_text if prompt_text is not None else resolve(task["prompt_file"]).read_text(encoding="utf-8"),
        "model": task["model"], "duration": int(task["duration_seconds"]),
        "aspect_ratio": task.get("aspect_ratio", "9:16"), "resolution": task["resolution"],
        "generating_count": 1,
        "images": images_payload,
    }
    audio_asset_ids = [
        *(task.get("exact_dialogue_audio_asset_ids") or []),
        *(task.get("reference_audio_asset_ids") or []),
    ]
    audio_urls = [
        *(task.get("exact_dialogue_audio_urls") or []),
        *(task.get("reference_audio_urls") or []),
    ]
    if str(task.get("model") or "").lower() in {"minimax-h3", "h3"} and audio_asset_ids:
        # Raised before the intent record: it used to fire after it and leave a
        # transaction that looked like an in-flight submission.
        raise ValueError("MiniMax-H3 requires URL audio references; asset IDs are not valid transport")
    if audio_asset_ids:
        payload["audios"] = [{"asset_id": value} for value in audio_asset_ids]
    elif audio_urls:
        payload["audios"] = [{"url": value} for value in audio_urls]
    request_binding = require_reviewed_request(task, task_request_digest(
        task, prompt_text=payload["prompt"],
        reference_paths=[resolve(value) for value in task["reference_images"]],
        duration=payload["duration"], audio=sent_audio_references(task),
    )["request_sha256"])
    require_no_silent_resubmission(task, transaction_dir, fingerprint)
    # Collective learning (opt-in, only a task bound to a run knowledge lock): re-verify the
    # locked knowledge immediately before this NEW post.  Resume paths returned above and never
    # reach here, so a remote task already bound keeps its original binding.
    knowledge_check = knowledge_lock_check(task, transaction_dir)
    intent = {
        "schema": "qingshan.giggle_video_submit_transaction.v1",
        "task_key": task["task_key"], "attempt_id": str(uuid.uuid4()),
        "submission_fingerprint": fingerprint, "state": "INTENT_RECORDED",
        "intent_recorded_at": utc_now(), "prompt_sha256": task["prompt_sha256"],
        "reference_sha256": task["reference_sha256"], "model": task["model"],
        # Exposure while this task is bound but unreconciled (K111); priced by model
        # so an H3 episode is not stopped by an SD2-rate overestimate.
        "estimated_credits": estimated_video_credits(task),
        "retry_guard": "DO_NOT_RESUBMIT_UNTIL_LEDGER_RECONCILED",
    }
    if reference_image_asset_ids:
        # Over-limit transport: record the registered ids so recovery and audit can see exactly
        # which provider assets this transaction is bound to without re-reading the request body.
        intent["reference_transport"] = REFERENCE_ASSET_TRANSPORT
        intent[REFERENCE_IMAGE_ASSET_IDS_KEY] = list(reference_image_asset_ids)
    if scope_evidence is not None:
        intent["prompt_scope_conflict_gate"] = scope_evidence["gate"]
        intent["loaded_modules"] = scope_evidence["loaded_modules"]
    intent["request_binding"] = request_binding
    intent["sent_reference_sha256"] = sent_image_sha256(images_payload)
    if knowledge_check is not None:
        intent["knowledge_lock_check"] = knowledge_check
    atomic_json(transaction, intent)
    try:
        with paid_video_submission_context():
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
    intent.update({"state": "SUBMITTED_TASK_ID_BOUND", "task_id": str(task_id), "receipt": portable(receipt), "provider_response": response, "response_recorded_at": utc_now()})
    atomic_json(transaction, intent)
    atomic_json(receipt, response)
    if knowledge_check is not None:
        record_knowledge_provider_request(task, payload, transaction, intent)
    return {
        **task, "task_id": str(task_id), "state": "remote_running", "submitted_at": utc_now(),
        "receipt": portable(receipt), "transaction": portable(transaction), "recovered_from_transaction": False,
        "credit_attempts": [{"attempt": 1, "task_id": str(task_id), "success": None, "charge_status": "PENDING_REMOTE_RESULT", "actual_charged_credits": None}],
    }


# The repository owns the standard multi-reference transport. An enterprise
# deployment may still wrap or replace this entrypoint through an explicit
# BACKLOT_PIPELINE_TOOLS_DIR, but clean-clone operation never depends on a
# hidden machine-local copy.
_legacy_submit_one_for_audit_only = submit_one


def submit_one(task: dict[str, Any], receipt_dir: Path, transaction_dir: Path) -> dict[str, Any]:
    transaction = transaction_path(transaction_dir, task)
    transaction.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock inode: unlinking it can let a third worker bypass a waiter.
    with transaction.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return _legacy_submit_one_for_audit_only(task, receipt_dir, transaction_dir)


def _provider_declined(failure: dict[str, Any], transaction_dir: Path | None = None) -> bool:
    """True when the recorded provider response is an explicit non-200 failure carrying no task_id (nalu e24).

    2026-09-21 (nalu E08 wave 2): a transport failure that never reached a task id counts too —
    12/12 POSTs died as ``NETWORK: <urlopen error [Errno 32] Broken pipe>`` or Cloudflare
    ``HTTP 524`` at concurrency 6.  The money-safety property is unchanged because the only caller
    also requires ``extra == 0``: the ledger window must show no pay row beyond the task ids we
    already hold, so "retryable" is still asserted against the ledger, never against the error text.
    """
    text = str(failure.get("provider_response") or "")
    if not text and transaction_dir is not None and failure.get("transaction"):
        path = resolve(failure["transaction"])
        if path.is_file():
            try:
                recorded = json.loads(path.read_text(encoding="utf-8")).get("provider_response")
                # A transaction written before any response carries provider_response: null;
                # json.dumps(None) is the non-empty string "null", which used to mask the real
                # error text below and made every transport failure look ambiguous (nalu E08 wave 2).
                text = json.dumps(recorded, ensure_ascii=False) if recorded else ""
            except Exception:  # noqa: BLE001
                text = ""
    text = text or str(failure.get("error") or "")
    return ("task_id" not in text or "missing task_id" in text) and any(
        marker in text for marker in ("'code': 500", '"code": 500', '"code":500', "payment failed",
                                      "status: 500", "status: 4",
                                      "NETWORK:", "Broken pipe", "HTTP 524", "HTTP 502", "HTTP 503",
                                      "timed out", "Connection reset")
    )


def _attempted(failure: dict[str, Any]) -> bool:
    """False for a failure that stopped before its intent record (no POST was attempted).

    Such a failure carries no charge question at all, so it must not take part in deciding whether
    the POSTs that DID go out were declined (nalu E11 wave 9: a pre-intent prompt-gate refusal of
    VU-003 sat in the same batch as VU-026's DNS failure, and its non-network error text flipped
    the whole batch to CHARGE_STATE_UNRESOLVED_BATCH although the ledger matched exactly, 2 == 2)."""
    if failure.get("state") == "submit_failed_before_intent" or failure.get("pre_intent_block"):
        return False
    return True


def classify_failures(failures: list[dict[str, Any]], known: int, matched: int, transaction_dir: Path) -> str:
    extra = matched - known
    if not failures:
        return "NO_AMBIGUOUS_SUBMISSIONS"
    posted = [f for f in failures if _attempted(f)]
    if len(posted) == 1 and extra == 1:
        state, summary = "CHARGED_TASK_ID_MISSING", "RECOVER_ONE_TASK_ID_FROM_PROVIDER_HISTORY"
    elif extra == 0 and all(_provider_declined(f, transaction_dir) for f in posted):
        # nalu e24 (2026-09-18, mirrors e18 for images): the provider answered with an explicit
        # non-charging failure (code != 200, e.g. "payment failed ... 500", no task_id) AND the ledger
        # window shows exactly as many pay rows as the task ids we hold — nothing was bought; the
        # attempt may be retried (VERIFIED_ZERO_RETRYABLE is the state prior_bound() lets through).
        state, summary = "VERIFIED_ZERO_RETRYABLE", "PROVIDER_DECLINED_AND_LEDGER_ROWS_EQUAL_KNOWN_TASK_IDS"
    else:
        state, summary = "CHARGE_STATE_UNRESOLVED_BATCH", "QUARANTINE_AMBIGUOUS_TASKS_ONLY"
    for failure in failures:
        path = resolve(failure["transaction"])
        if not path.is_file():
            # nalu e21 (mirrors e17 for images): the task failed BEFORE its intent record was written
            # (batch prompt gate / precheck / reference read) — no POST was attempted, nothing was charged.
            failure["status"] = "submit_failed_before_intent"
            failure["credit"] = 0
            failure["credit_status"] = "NOT_CHARGED_NO_INTENT_RECORDED"
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        if row.get("state") == "SUBMITTED_TASK_ID_BOUND" and row.get("task_id"):
            failure["task_id"] = row["task_id"]
            failure["credit_status"] = "BOUND_TASK_RECEIPT_RECOVERY_REQUIRED"
            continue
        # Aggregate absence is not per-attempt zero-charge evidence: ledgers can lag.
        retry_guard = "RETRY_ALLOWED_NEW_ATTEMPT" if state == "VERIFIED_ZERO_RETRYABLE" else "DO_NOT_RESUBMIT_RECOVER_TASK_ID"
        row.update({"state": state, "ledger_reconciled_at": utc_now(), "batch_known_task_ids": known, "batch_ledger_pay_rows": matched, "retry_guard": retry_guard})
        if state == "VERIFIED_ZERO_RETRYABLE":
            row["credit_status"] = "NOT_CHARGED_RETRYABLE"
            row["reconciliation"] = {"rule": "nalu e24: explicit provider decline + ledger pay rows == known task ids", "credit": 0}
            failure["credit"] = 0
        atomic_json(path, row)
        failure["credit_status"] = "NOT_CHARGED_RETRYABLE" if state == "VERIFIED_ZERO_RETRYABLE" else state
    return summary


def main() -> int:
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--precheck-only", action="store_true")
    parser.add_argument(
        "--reconcile-unresolved-report",
        help="Offline re-classification of a submit report's failures against a re-fetched credit window; never POSTs",
    )
    args = parser.parse_args()
    if args.project_root:
        ROOT = Path(args.project_root).expanduser().resolve()
    if args.reconcile_unresolved_report:
        # Mirrors submit_giggle_image_manifest.py --reconcile-unresolved-report.  The submit path only
        # classifies on its way out of a run; once a transaction is CHARGE_STATE_UNRESOLVED_BATCH the
        # durable guard refuses to POST it again, so a misclassified row could never be re-settled
        # (nalu E11 wave 9, VU-026: DNS failure, ledger 2 == 2, quarantined by a co-batched
        # pre-intent refusal).  This re-fetches the SAME window and runs the SAME classifier; a charge
        # is never hidden because extra pay rows still keep the row quarantined.
        report_path = resolve(args.reconcile_unresolved_report)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        failures = list(report.get("failures") or [])
        if not failures:
            raise SystemExit("reconcile report has no failures to reclassify")
        window = report.get("credit_reconciliation") or {}
        known = int(window.get("known_task_id_count") or report.get("submitted") or 0)
        start = datetime.fromisoformat(str(window.get("window_start_utc") or report["recorded_at"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(window.get("window_end_utc") or report["recorded_at"]).replace("Z", "+00:00"))
        expected = known + sum(_attempted(f) for f in failures)
        transactions = ROOT / "workflow/tasks/giggle_video_submit_transactions" / str(report.get("episode") or "")
        own_ids = {str(row["task_id"]) for row in report.get("tasks") or []
                   if isinstance(row, dict) and row.get("task_id") and not row.get("recovered_from_transaction")}
        fresh = reconcile_rows(fetch_pay_statements(), start=start - timedelta(seconds=10),
                               end=end + timedelta(minutes=10), expected_count=expected,
                               event_description="SingleGenerateVideo",
                               model=str(window.get("model") or "seedance-2.0-pro"),
                               known_task_ids=own_ids,
                               exclude_task_ids=attributed_task_ids(transactions.parent) - own_ids)
        matched = int(fresh.get("matched_count", 0))
        for failure in failures:
            path = resolve(failure["transaction"]) if failure.get("transaction") else None
            if path is not None and path.is_file():
                row = json.loads(path.read_text(encoding="utf-8"))
                if row.get("state") == "SUBMITTED_TASK_ID_BOUND":
                    continue
                failure.setdefault("error", row.get("error"))
        summary = classify_failures(failures, known, matched, transactions)
        result = {"schema": "qingshan.giggle_video_reconcile.v1", "report": portable(report_path),
                  "known_task_id_count": known, "matched_ledger_rows": matched,
                  "charged_credits": fresh.get("charged_credits"), "summary": summary,
                  "rows": [{"task_key": f.get("task_key"), "credit_status": f.get("credit_status")} for f in failures],
                  "posted": 0}
        atomic_json(resolve(args.out), result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    manifest_path = resolve(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require_episode_video_model(manifest, manifest_path)  # K145: before any gate, intent or POST
    efficiency_gate = require_e47_efficiency_contract(manifest)
    authoritative_gate = run_authoritative_submission_gate(manifest, manifest_path)
    gates = [validate_gate(value) for value in manifest.get("machine_gate_reports") or []]
    tasks = manifest.get("tasks") or []
    if not gates or not tasks:
        raise SystemExit("Video manifest requires passing gates and tasks")
    # D-46 partial redo: the materialised copy authorises only the units without a clip on disk and marks
    # the rest provider_post_allowed=False.  Those rows are not part of this submission — validating them
    # (their recompiled prompts no longer match the registered batch) failed the whole redo before any POST
    # (urban lab E03 2026-10-24).  Keep only authorised rows when at least one row is authorised.
    unauthorised_rows = [t for t in tasks if t.get("provider_post_allowed") is False]
    if not args.precheck_only and unauthorised_rows and len(unauthorised_rows) < len(tasks):
        tasks = [t for t in tasks if t.get("provider_post_allowed") is not False]
        manifest = {**manifest, "tasks": tasks, "partial_repair_scope": manifest.get("partial_repair_scope")
                    or "D46_UNAUTHORISED_ROWS_EXCLUDED"}
    # E47+ production uses rolling parallel waves.  Serial submission is only
    # valid when every unit is causally chained to an exact predecessor tail;
    # otherwise a caller that explicitly passes ``--concurrency 1`` is a
    # configuration error, not a safe fallback.
    episode_value = episode_number(manifest.get("episode"))
    if (
        episode_value is not None
        and episode_value >= 47
        and max(1, args.concurrency) == 1
        and not _batch_requires_serial_tail_chain(tasks)
    ):
        raise RuntimeError(
            "E47+ independent video batches require concurrency >= 2; "
            "concurrency=1 is reserved for batches where every task has an "
            "exact predecessor tail-frame dependency"
        )
    grouped_camera_units = []
    for task in tasks:
        validate_task(task)
        gate_failures = validate_task_submission_gates(task)
        if gate_failures:
            raise RuntimeError(
                f"{task.get('task_key')} submission gate failed: " + ",".join(gate_failures)
            )
        if task.get("semantic_video_unit"):
            grouped_camera_units.append(grouped_sequence_unit(task))
    scoped = bool(manifest.get("partial_repair_scope") or manifest.get("staged_generation_scope"))
    if scoped:
        # A scoped repair batch is a non-contiguous slice of the episode, so it
        # must not be validated as a standalone contiguous episode.  It also
        # must not skip the cross-unit checks: the boundaries it actually
        # touches are exactly the risk.  Splice the read-only global
        # neighbours from the sha-bound grouping plan and validate the whole
        # affected run (see CC_H3 audit 2026-10-26 §四-缺口E).
        segments, neighbour_report = scoped_sequence_with_global_neighbours(
            manifest, grouped_camera_units)
        for segment in segments:
            validate_camera_sequence(segment)
            # Each segment starts inside the episode: its first unit is a
            # read-only neighbour that legitimately has an inbound transition.
            # Segments are never concatenated across a real gap (2026-10-28:
            # two unrelated neighbours landing adjacent in one flat list raised
            # a spurious transition-binding mismatch between units nothing
            # actually placed next to each other).
            validate_transition_sequence(segment, require_prompt_specs=True,
                                        starts_episode=False)
            rhythm = validate_combat_sequence_rhythm(segment)
            if rhythm["status"] != "PASS":
                raise ValueError("Combat sequence rhythm gate failed: " + ",".join(rhythm["failures"]))
    else:
        validate_camera_sequence(grouped_camera_units)
        validate_transition_sequence(grouped_camera_units, require_prompt_specs=True)
        rhythm = validate_combat_sequence_rhythm(grouped_camera_units)
        if rhythm["status"] != "PASS":
            raise ValueError("Combat sequence rhythm gate failed: " + ",".join(rhythm["failures"]))
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
        # Bounded ready queue instead of a fixed wave barrier (2026-10-13).  The old loop sliced the
        # batch into range(0, len(tasks), concurrency) waves and only opened the next slice after
        # as_completed() had drained the whole wave, so one slow POST held a free submit slot idle
        # while other READY tasks waited on it.  E11 wave11 (2026-10-11) spread 124.4 s over 6 tasks
        # at concurrency 3 for exactly this reason.
        #
        # What is NOT relaxed by this change:
        #   * every gate, the whole-batch prompt registration and the per-task fingerprint lock are
        #     untouched — submit_one still refuses a second POST for the same fingerprint;
        #   * results/failures keep one row per task and the report keeps one entry per task_key, so
        #     the reconciliation below still accounts for every submission attempt;
        #   * the provider-insufficient-credits fuse still stops DISPATCH, and it now stops it at the
        #     first free slot rather than at a wave boundary.
        # The ceiling is the same: at most ``concurrency`` POSTs are in flight at any instant.
        task_iter = iter(tasks)
        in_flight: dict[Any, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            def _start(task: dict[str, Any]) -> None:
                in_flight[pool.submit(submit_one, task, receipts, transactions)] = task

            # Prime exactly ``concurrency`` slots.  Tasks are NOT all queued up front: the
            # insufficient-credits fuse has to be able to stop DISPATCH, and a pool already holding
            # the whole batch would run the remaining tasks anyway.
            for task in task_iter:
                _start(task)
                if len(in_flight) >= concurrency:
                    break
            while in_flight:
                # FIRST_COMPLETED, not as_completed over the whole set: a slot is refilled the moment
                # ITS POST returns, without waiting for the batch's slowest in-flight request.
                done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for future in done:
                    task = in_flight.pop(future)
                    try:
                        results.append(future.result())
                    except ProviderInsufficientCreditsError as exc:
                        credit_fuse_tripped = True
                        failures.append({"task_key": task["task_key"], "state": "provider_insufficient_credits", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
                    except PromptScopeGateBlocked as exc:
                        failures.append({"task_key": task["task_key"], "state": "submit_failed_before_intent", "error": str(exc), "transaction": portable(transaction_path(transactions, task)), "pre_intent_block": portable(pre_intent_block_path(transactions, task)), "credit": 0, "credit_status": "NOT_CHARGED_NO_INTENT_RECORDED"})
                    except (Exception, SystemExit) as exc:
                        failures.append({"task_key": task["task_key"], "state": "submit_failed", "error": str(exc), "transaction": portable(transaction_path(transactions, task))})
                    if credit_fuse_tripped:
                        break
                    # a submit slot just freed: start the next READY task now instead of waiting for
                    # this batch's slowest POST to return.
                    nxt = next(task_iter, None)
                    if nxt is not None:
                        in_flight[pool.submit(submit_one, nxt, receipts, transactions)] = nxt
                if credit_fuse_tripped:
                    break
        if credit_fuse_tripped:
            # every task that never got a slot is reported as not-submitted, exactly as before
            reported = {row["task_key"] for row in results} | {row["task_key"] for row in failures}
            for task in tasks:
                if task["task_key"] in reported:
                    continue
                failures.append({
                    "task_key": task["task_key"],
                    "state": "not_submitted_provider_insufficient_credits",
                    "error": "batch dispatch stopped after provider insufficient-credits response",
                    "transaction": portable(transaction_path(transactions, task)),
                })
    credit = None
    ambiguity = "NOT_APPLICABLE"
    if not args.precheck_only:
        newly_bound = sum(not row.get("recovered_from_transaction") for row in results)
        # A scope-gate block happens before any intent or POST, so it can never own a pay row.
        maximum = newly_bound + sum(row.get("state") != "submit_failed_before_intent" for row in failures)
        if maximum == 0:
            # nalu e21: nothing was POSTed in this run (every task recovered from the durable store, no
            # failures) — there is no charge to reconcile.  Matching a statement window here only picks up
            # OTHER lines' activity on a shared provider account and turns a no-op re-entry into a FAIL
            # (observed 2026-09-15: 2 foreign SingleGenerateVideo rows, 400 cr, in a 23 s window).
            credit = {"status": "PASS_REUSED_TRANSACTIONS", "matched_count": 0, "charged_credits": 0,
                      "expected_count": 0, "known_task_id_count": 0, "ambiguous_response_count": 0,
                      "unmapped_pay_row_count": 0, "note": "no new submission in this run; window reconciliation skipped"}
            matched = 0
        # Attribute Pay rows by provider task id first (project_id == task_id): the ids this run
        # bound are ours wherever they fall, and an id another durable transaction already owns
        # (an adjacent or overlapping wave) is never counted here again.  Lab E05 2026-10-26:
        # wave 29's window opened 10 s before its POST and swallowed wave 28's 1eb26c4b row.
        own_ids = {str(row["task_id"]) for row in results
                   if row.get("task_id") and not row.get("recovered_from_transaction")}
        foreign_ids = attributed_task_ids(transactions.parent) - own_ids
        for attempt in range(7 if maximum else 0):
            credit = reconcile_rows(fetch_pay_statements(), start=start - timedelta(seconds=10), end=datetime.now(timezone.utc) + timedelta(seconds=10), expected_count=maximum, event_description="SingleGenerateVideo", model=str(tasks[0]["model"]),
                                    known_task_ids=own_ids, exclude_task_ids=foreign_ids)
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
        "production_efficiency_gate": efficiency_gate,
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


def validate_task_submission_gates(task: dict[str, Any]) -> list[str]:
    """Every per-task gate that must pass before a paid video POST.

    These checks used to live only inside ``exec_deployed_submitter()``, which
    nothing calls: ``main()`` — the entrypoint production actually runs — did
    validate_task and the sequence gates but never reached any of this, so the
    repo path and the deployed path validated different things.  One function,
    called by both, is the only way they stay equal.
    """
    failures: list[str] = []
    for label, raised in (
        ("BLOCK_RETRY_CAP_GATE", validate_submission_attempt(task)),
        ("BLOCK_STRUCTURED_ACTION_CONTRACT_INVALID", validate_action_contract(task)),
    ):
        if raised:
            failures.append(f"{label}:{','.join(raised)}")
    expected_template_id = compute_input_template_id(task)
    if task.get("input_template_id") != expected_template_id:
        failures.append("INPUT_TEMPLATE_ID_MISSING_OR_STALE")
    precheck = precheck_submission_inputs(task, enforce=True, root=ROOT)
    if precheck.get("status") != "PASS":
        missing = [*(precheck.get("missing_characters") or []), *(precheck.get("missing_props") or [])]
        failures.append(
            f"INPUT_COMPLETENESS_FAILED:{precheck.get('failure_code')}"
            + (f":missing={','.join(missing)}" if missing else "")
        )
    return failures


def exec_deployed_submitter() -> None:
    forwarded = list(sys.argv[1:])
    try:
        manifest_value = forwarded[forwarded.index("--manifest") + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("--manifest is required") from exc
    manifest_path = resolve(manifest_value)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require_e47_efficiency_contract(manifest)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    grouped_camera_units = []
    for task in manifest.get("tasks") or []:
        validate_task(task)
        gate_failures = validate_task_submission_gates(task)
        if gate_failures:
            raise RuntimeError(
                f"{task.get('task_key')} submission gate failed: " + ",".join(gate_failures)
            )
        if task.get("semantic_video_unit"):
            grouped_camera_units.append(grouped_sequence_unit(task))
    # A scene-first wave is intentionally non-contiguous in episode order:
    # every selected task may be the first unit of a different scene.  Per-task
    # prompt/transition contracts are validated above; here the affected
    # boundaries are validated against the read-only global neighbours the
    # batch recorded, never against the subset treated as a fresh episode.
    scoped = bool(
        manifest.get("partial_repair_scope") or manifest.get("staged_generation_scope")
    )
    if scoped:
        segments, neighbour_report = scoped_sequence_with_global_neighbours(
            manifest, grouped_camera_units)
        for segment in segments:
            validate_camera_sequence(segment)
            # Each segment starts inside the episode: its first unit is a
            # read-only neighbour that legitimately has an inbound transition.
            # Segments are never concatenated across a real gap (2026-10-28:
            # two unrelated neighbours landing adjacent in one flat list raised
            # a spurious transition-binding mismatch between units nothing
            # actually placed next to each other).
            validate_transition_sequence(segment, require_prompt_specs=True,
                                        starts_episode=False)
            rhythm = validate_combat_sequence_rhythm(segment)
            if rhythm["status"] != "PASS":
                raise RuntimeError("Combat sequence rhythm gate failed: " + ",".join(rhythm["failures"]))
    else:
        validate_camera_sequence(grouped_camera_units)
        validate_transition_sequence(grouped_camera_units, require_prompt_specs=True)
        rhythm = validate_combat_sequence_rhythm(grouped_camera_units)
        if rhythm["status"] != "PASS":
            raise RuntimeError("Combat sequence rhythm gate failed: " + ",".join(rhythm["failures"]))
    deployed = authoritative_pipeline_tools_dir() / "submit_giggle_video_manifest_v2.py"
    if not deployed.is_file():
        raise RuntimeError("Deployed BacklotOS video submitter is unavailable")
    if "--project-root" not in forwarded:
        forwarded = ["--project-root", str(ROOT), *forwarded]
    episode_value = episode_number(manifest.get("episode"))
    if episode_value is not None and episode_value >= 47 and "--concurrency" in forwarded:
        try:
            concurrency = int(forwarded[forwarded.index("--concurrency") + 1])
        except (ValueError, IndexError) as exc:
            raise RuntimeError("--concurrency requires an integer from 1 to 6") from exc
        if concurrency < 1 or concurrency > DEFAULT_WAVE_SIZE:
            raise RuntimeError("E47+ rolling submission concurrency must be from 1 to 6")
        if concurrency == 1 and not _batch_requires_serial_tail_chain(manifest.get("tasks") or []):
            raise RuntimeError(
                "E47+ independent video batches require concurrency >= 2; "
                "concurrency=1 is reserved for exact predecessor tail-frame chains"
            )
    elif episode_value is not None and episode_value >= 47:
        forwarded.extend(["--concurrency", str(DEFAULT_WAVE_SIZE)])
    os.environ["BACKLOTOS_DEPLOYED_SUBMITTER"] = "1"
    os.environ["BACKLOTOS_PROJECT_ROOT"] = str(ROOT)
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    injected_paths = os.pathsep.join((str(ROOT / "tools"), str(ROOT)))
    os.environ["PYTHONPATH"] = injected_paths + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    os.execv(sys.executable, [sys.executable, str(deployed), *forwarded])


if __name__ == "__main__":
    raise SystemExit(main())
