#!/usr/bin/env python3
"""Submit a Giggle task manifest concurrently and write per-task receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    from episode_video_generation_guard import (
        credit_report_path,
        evaluate_episode_credit_gate,
        evaluate_episode_submission_authority,
        find_existing_paid_candidate,
        generation_fingerprint,
    )
    from script_readiness_gate import verify_script_readiness_report
    from script_density_gate_preflight import evaluate_density_gate
    from shot_duration_policy import validate_duration_task
    from supervisor_script_gate import verify_supervisor_script_gate
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
    from anachronism_lock_gate import evaluate as evaluate_anachronism_lock
    from shot_media_admission_gate import (
        compute_input_template_id,
        evaluate_path as evaluate_shot_media_admission,
        precheck_submission_inputs,
        validate_retry_change,
    )
    from video_model_adapter import require_paid_model_contract
    from image_model_adapter import require_paid_image_model_contract
except ImportError:
    from tools.episode_video_generation_guard import (
        credit_report_path,
        evaluate_episode_credit_gate,
        evaluate_episode_submission_authority,
        find_existing_paid_candidate,
        generation_fingerprint,
    )
    from tools.script_readiness_gate import verify_script_readiness_report
    from tools.script_density_gate_preflight import evaluate_density_gate
    from tools.shot_duration_policy import validate_duration_task
    from tools.supervisor_script_gate import verify_supervisor_script_gate
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
    from tools.anachronism_lock_gate import evaluate as evaluate_anachronism_lock
    from tools.shot_media_admission_gate import (
        compute_input_template_id,
        evaluate_path as evaluate_shot_media_admission,
        precheck_submission_inputs,
        validate_retry_change,
    )
    from tools.video_model_adapter import require_paid_model_contract
    from tools.image_model_adapter import require_paid_image_model_contract


BASE = Path(
    os.environ.get("QINGSHAN_FACTORY_ROOT", Path(__file__).resolve().parents[1])
).expanduser().resolve()
CLIENT = BASE / "tools/giggle_api_client.py"
CONSTITUTION_VERSION = "v1"
VISUAL_MARKER = "VISUAL_PROMPT_NO_DIALOGUE_TEXT:"
AUDIO_MARKER = "AUDIO_PROMPT_DIALOGUE_ONLY:"
PROTECTED_GIGGLE_ENV = BASE / ".secrets/giggle_api_key.env"

RUNTIME_GATE_IDS = frozenset({
    "SCRIPT-DENSITY-GENERATION-PREFLIGHT",
    "PICTURE-ONLY-REPAIR-SUBMISSION",
    "LOCAL-CLAUDE-SCRIPT-SUPERVISION",
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY",
    "MECHANICAL-DEFAULT-META-GATE",
    "VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT",
    "VIDEO-UNIT-SEMANTIC-GROUPING",
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
})
RUNTIME_GATE_BINDINGS = {
    "SCRIPT-DENSITY-GENERATION-PREFLIGHT": "resolve_script_density_gate",
    "PICTURE-ONLY-REPAIR-SUBMISSION": "resolve_picture_only_repair_gate",
    "LOCAL-CLAUDE-SCRIPT-SUPERVISION": "resolve_script_gate",
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY": "validate_corrected_pipeline_reports",
    "MECHANICAL-DEFAULT-META-GATE": "validate_corrected_pipeline_reports",
    "VIDEO-UNIT-DYNAMIC-ANCHOR-COUNT": "validate_corrected_pipeline_reports",
    "VIDEO-UNIT-SEMANTIC-GROUPING": "validate_corrected_pipeline_reports",
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL": "validate_corrected_pipeline_reports",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "validate_corrected_pipeline_reports",
    "PERIOD-ANACHRONISM-LOCK": "validate_corrected_pipeline_reports",
}
assert frozenset(RUNTIME_GATE_BINDINGS) == RUNTIME_GATE_IDS


def ensure_giggle_api_key() -> str:
    """Load the protected local key when the current process did not inherit it."""
    if os.environ.get("GIGGLE_API_KEY", "").strip():
        return "INHERITED_ENV"
    if not PROTECTED_GIGGLE_ENV.is_file():
        return "MISSING"
    if PROTECTED_GIGGLE_ENV.stat().st_mode & 0o077:
        return "UNSAFE_FILE_PERMISSIONS"
    for raw_line in PROTECTED_GIGGLE_ENV.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != "GIGGLE_API_KEY":
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ["GIGGLE_API_KEY"] = value
            return "PROTECTED_LOCAL_FILE"
    return "MISSING"

PC_S2_NEGATIVE_GROUPS: dict[str, tuple[str, ...]] = {
    "period_lock": (
        "modern police uniform",
        "peaked cap",
        "epaulettes",
        "republic of china era",
        "suitcase",
        "briefcase",
        "modern signage",
        "modern police",
    ),
    "text_lock": (
        "readable generated chinese",
        "english letters",
        "latin letters",
        "subtitles",
        "captions",
        "central bold dialogue text",
        "no chinese character",
        "no chinese characters",
        "no english",
    ),
    "speed_lock": (
        "slow motion",
        "dreamy pace",
        "floating",
        "weightless",
        "rubber physics",
    ),
    "shot_specific": (
        "static puppet",
        "frozen pose",
        "repeated movement",
        "face drift",
        "body drift",
        "hunched posture",
        "hands holding prop",
        "foreground object",
        "mouth movement",
        "lip movement",
        "wrong face",
    ),
}

PC_T1_ACTION_DELTA_TERMS: tuple[str, ...] = (
    "steps", "step", "half-step", "half pace", "moves", "move", "leans", "lean",
    "bends", "bend", "turns", "turn", "rotates", "rotate", "raises", "raise",
    "lowers", "lower", "lifts", "lift", "reaches", "reach", "slides", "slide",
    "pushes", "push", "pulls", "pull", "presses", "press", "blocks", "block",
    "shields", "shield", "intercepts", "intercept", "opens", "open", "closes",
    "close", "flips", "flip", "unfolds", "folds", "hands", "hand", "passes",
    "pass", "places", "place", "takes", "take", "pinches", "pinch", "points",
    "point", "tilts", "tilt", "drags", "drag", "wipes", "wipe", "shifts",
    "shift", "pivots", "pivot", "advances", "advance", "retreats", "retreat",
    "lamp", "cloth", "corpse cloth", "copper clasp", "box", "lid", "needle",
    "probe", "table", "door", "rainwater", "water", "shadow crosses",
    "light is blocked", "evidence enters the center", "sleeve", "shoulder",
    "上前", "退半步", "半步", "侧身", "俯身", "转身", "抬手", "压住",
    "拨灯", "移灯", "翻尸布", "递", "接过", "取出", "打开", "合上",
    "推开", "拉近", "挡住", "逼近", "伸手", "指向", "掀开", "擦拭",
    "滑到", "落到", "雨水", "灯火", "证物", "箱盖", "铜扣", "尸布",
)
try:
    from action_video_prompt_compiler import validate_action_contract
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import validate_action_contract

PC_S3_RISKY_TEMPLATE_PHRASES: tuple[str, ...] = (
    "stable a-side speaker coverage",
    "speaker close-up",
    "clear mouth movement",
    "speaker says the exact mandarin line",
)


def split_prompt_sections(prompt: str) -> tuple[str | None, str | None]:
    if VISUAL_MARKER not in prompt or AUDIO_MARKER not in prompt:
        return None, None
    visual = prompt.split(VISUAL_MARKER, 1)[1].split(AUDIO_MARKER, 1)[0]
    audio = prompt.split(AUDIO_MARKER, 1)[1]
    return visual, audio


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def audio_section_is_empty(audio: str | None) -> bool:
    if audio is None:
        return False
    first_value = next((line.strip() for line in audio.splitlines() if line.strip()), "")
    return first_value == "[]"


def is_designated_static_beat(task: dict[str, Any]) -> bool:
    return bool(task.get("designated_static_beat") or task.get("static_beat") or task.get("pc_t5_static_beat"))


def validate_prompt_contract(task: dict[str, Any], prompt_path: Path) -> list[str]:
    """Run prompt-constitution checks before any Giggle credit can be spent."""
    problems: list[str] = []
    text = (task.get("text") or task.get("dialogue_text") or "").strip()
    if not text:
        return problems
    prompt = prompt_path.read_text(encoding="utf-8")
    visual, _audio = split_prompt_sections(prompt)
    if visual is None:
        problems.append("FAIL_PC_S1_PROMPT_CONTRACT_MISSING_VISUAL_AUDIO_SECTIONS")
        return problems
    if text in visual:
        problems.append("FAIL_PC_S1_DIALOGUE_TEXT_LEAKED_INTO_VISUAL_PROMPT")
    lower_visual = visual.lower()
    for group_name, terms in PC_S2_NEGATIVE_GROUPS.items():
        if not any(term in lower_visual for term in terms):
            problems.append(f"FAIL_PC_S2_NEGATIVE_BLOCK_MISSING:{group_name}")
    if not is_designated_static_beat(task) and not has_any(visual, PC_T1_ACTION_DELTA_TERMS):
        problems.append("FAIL_PC_T1_NO_ACTION_DELTA")
    return problems


def validate_manifest_constitution(manifest: dict[str, Any], ready: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    static_count = sum(1 for task in ready if is_designated_static_beat(task))
    quota_total = manifest.get("static_beat_quota_total") or manifest.get("episode_total_prompt_count")
    if quota_total:
        static_ratio = static_count / max(1, int(quota_total))
        if static_ratio > 0.10:
            problems.append(f"FAIL_PC_T5_STATIC_BEAT_QUOTA_EXCEEDED:{static_count}/{quota_total}")
    elif len(ready) >= 10 and static_count / max(1, len(ready)) > 0.10:
        problems.append(f"FAIL_PC_T5_STATIC_BEAT_QUOTA_EXCEEDED:{static_count}/{len(ready)}")

    visuals: list[str] = []
    for task in ready:
        try:
            prompt_path = BASE / task["prompt_path"]
            visual, _audio = split_prompt_sections(prompt_path.read_text(encoding="utf-8"))
            if visual:
                visuals.append(visual.lower())
        except Exception:
            continue
    if len(visuals) >= 4:
        for phrase in PC_S3_RISKY_TEMPLATE_PHRASES:
            count = sum(1 for visual in visuals if phrase in visual)
            if count / len(visuals) > 0.30:
                problems.append(f"FAIL_PC_S3_TEMPLATE_FREQUENCY_REVIEW:{phrase}:{count}/{len(visuals)}")
    return problems


def validate_ready_task_contracts(ready: list[dict[str, Any]]) -> list[str]:
    """Validate every task before allowing any task in the batch to submit."""
    problems: list[str] = []
    for task in ready:
        source_id = task.get("source_id") or task.get("dialogue_id") or "unknown"
        task["input_template_id"] = task.get("input_template_id") or compute_input_template_id(task)
        input_precheck = precheck_submission_inputs(task)
        if input_precheck["status"] != "PASS":
            if not input_precheck["missing_characters"] and not input_precheck["missing_props"]:
                problems.append(
                    f"{input_precheck['failure_code']}:{source_id}"
                )
            for entity_id in input_precheck["missing_characters"] + input_precheck["missing_props"]:
                problems.append(
                    f"MISSING_ANCHOR_FOR_CANONICAL_ENTITY:{source_id}:{entity_id}"
                )
        if str(task.get("media_stage") or "").upper() == "VIDEO":
            try:
                require_paid_model_contract(task, str(task.get("episode") or ""))
            except ValueError as exc:
                problems.append(f"FAIL_VIDEO_MODEL_ADAPTER:{source_id}:{exc}")
            problems.extend(
                f"FAIL_STRUCTURED_ACTION_CONTRACT:{source_id}:{value}"
                for value in validate_action_contract(task)
            )
        elif task.get("tool_type") == "image_generation" and str(task.get("episode") or "").upper().startswith("E"):
            try:
                episode_number = int(str(task.get("episode"))[1:].split("-")[0])
                if episode_number >= 40:
                    require_paid_image_model_contract(task, str(task.get("episode")))
            except (ValueError, TypeError) as exc:
                problems.append(f"FAIL_IMAGE_MODEL_ADAPTER:{source_id}:{exc}")
        if task.get("state") == "retry_pending" or task.get("retry_count"):
            retry_gate = validate_retry_change(task)
            problems.extend(f"{value}:{source_id}" for value in retry_gate["failures"])
        prompt_path = BASE / task["prompt_path"]
        problems.extend(validate_duration_task(task))
        if task.get("generation_mode") == "entity_reference_sequence":
            planned = task.get("planned_reference_image_count")
            if not isinstance(planned, int) or isinstance(planned, bool) or planned < 1:
                problems.append(
                    f"FAIL_DYNAMIC_ANCHOR_COUNT_PLAN_MISSING:{source_id}:planned_reference_image_count"
                )
                planned = 10**9
            minimum = int(planned)
            legacy_minimum = task.get("state_reference_minimum")
            if legacy_minimum is not None and legacy_minimum != minimum:
                problems.append(
                    f"FAIL_DYNAMIC_ANCHOR_COUNT_CONFLICT:{source_id}:legacy={legacy_minimum}:planned={minimum}"
                )
            image_count = len(resolve_reference_images(task))
            sequence_count = len(task.get("reference_image_sequence") or [])
            if image_count < minimum:
                problems.append(
                    f"FAIL_MULTI_STATE_IMAGE_COUNT:{source_id}:actual={image_count}:required={minimum}"
                )
            if sequence_count < minimum:
                problems.append(
                    f"FAIL_MULTI_STATE_SEQUENCE_COUNT:{source_id}:actual={sequence_count}:required={minimum}"
                )
            if image_count != minimum or sequence_count != minimum:
                problems.append(
                    f"FAIL_DYNAMIC_ANCHOR_COUNT_MISMATCH:{source_id}:images={image_count}:sequence={sequence_count}:planned={minimum}"
                )
        for problem in validate_prompt_contract(task, prompt_path):
            problems.append(f"FAIL_TASK_PROMPT_CONTRACT:{source_id}:{problem}")
    return problems


def validate_keyframe_admissions(manifest: dict[str, Any], ready: list[dict[str, Any]]) -> list[str]:
    """Close the direct-submitter path around E40+ formal start-frame admission."""
    match = re.match(r"E(\d+)(?:\D|$)", str(manifest.get("episode") or "").upper())
    if not match or int(match.group(1)) < 40:
        return []
    problems: list[str] = []
    for task in ready:
        source_id = str(task.get("source_id") or task.get("dialogue_id") or "unknown")
        value = task.get("start_frame_admission_ref")
        if not value:
            problems.append(f"FAIL_START_FRAME_ADMISSION_MISSING:{source_id}")
            continue
        path = Path(value)
        path = path if path.is_absolute() else BASE / path
        try:
            result = evaluate_shot_media_admission(path, BASE)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            problems.append(f"FAIL_START_FRAME_ADMISSION_UNREADABLE:{source_id}:{type(exc).__name__}")
            continue
        if result.get("status") not in {"ADMITTED", "ADMITTED_WITH_P2"}:
            problems.append(f"FAIL_START_FRAME_NOT_CONTENT_ADMITTED:{source_id}")
            continue
        references = task.get("reference_image_sequence") or []
        first = references[0] if references else {}
        first_path = first.get("path") or ((resolve_reference_images(task) or [None])[0])
        if not first_path or (BASE / first_path).resolve() != Path(result["asset_path"]).resolve():
            problems.append(f"FAIL_FIRST_REFERENCE_NOT_ADMITTED_START_FRAME:{source_id}")
        if str(task.get("start_frame_sha256") or "") != str(result.get("asset_sha256") or ""):
            problems.append(f"FAIL_START_FRAME_SHA_NOT_BOUND_TO_ADMISSION:{source_id}")
    return problems


def validate_corrected_pipeline_reports(
    manifest: dict[str, Any], ready: list[dict[str, Any]]
) -> list[str]:
    """Prevent E28+ direct manifests from bypassing the corrected pipeline gates."""
    match = re.match(r"E(\d+)(?:\D|$)", str(manifest.get("episode") or "").upper())
    episode_number = int(match.group(1)) if match else 0
    required = (
        episode_number >= 28
        or manifest.get("effective_ruleset") == "QINGSHAN_PIPELINE_EFFECTIVE_RULESET_V1"
    )
    if not required or not ready:
        return []
    problems: list[str] = [
        "FAIL_CORRECTED_PIPELINE_DIRECT_SUBMIT_FORBIDDEN:USE_EPISODE_PARALLEL_BATCH_SUPERVISOR"
    ]
    problems.extend(
        f"FAIL_TAIL_CHAIN_SUBMISSION:{value}"
        for value in validate_tail_chained_submission(ready, BASE)
    )
    anchor_result: dict[str, Any] | None = None
    for key, evaluator in (
        ("dramatic_quality_report_ref", evaluate_dramatic_quality),
        ("mechanical_default_plan_ref", evaluate_mechanical_defaults),
        ("video_unit_grouping_plan_ref", evaluate_video_unit_grouping),
        ("anchor_count_plan_ref", evaluate_anchor_counts),
        ("common_sense_causality_plan_ref", evaluate_common_sense_causality),
        ("action_shot_design_plan_ref", evaluate_action_shot_design),
        ("period_lock_plan_ref", evaluate_anachronism_lock),
    ):
        value = manifest.get(key)
        if not value:
            problems.append(f"FAIL_CORRECTED_PIPELINE_REPORT_MISSING:{key}")
            continue
        path = Path(value)
        path = path if path.is_absolute() else BASE / path
        if not path.is_file():
            problems.append(f"FAIL_CORRECTED_PIPELINE_REPORT_NOT_FOUND:{key}:{path}")
            continue
        result = evaluator(json.loads(path.read_text(encoding="utf-8")))
        if result.get("status") != "PASS":
            problems.append(f"FAIL_CORRECTED_PIPELINE_GATE:{key}")
        if key == "action_shot_design_plan_ref" and result.get("status") == "PASS":
            plan = json.loads(path.read_text(encoding="utf-8"))
            problems.extend(
                f"FAIL_ACTION_SHOT_PROMPT_BINDING:{value}"
                for value in validate_action_shot_bindings(plan, ready, BASE)
            )
        if key == "video_unit_grouping_plan_ref" and result.get("status") == "PASS":
            plan = json.loads(path.read_text(encoding="utf-8"))
            problems.extend(
                f"FAIL_VIDEO_UNIT_GROUPING_BINDING:{value}"
                for value in validate_video_unit_grouping_bindings(plan, ready)
            )
        if key == "anchor_count_plan_ref":
            anchor_result = result
    if anchor_result and anchor_result.get("status") == "PASS":
        planned_by_unit = {
            str(row.get("unit_id")): row.get("planned_reference_image_count")
            for row in anchor_result.get("decisions") or []
        }
        for task in ready:
            unit_id = str(task.get("unit_id") or task.get("source_id") or "")
            planned = planned_by_unit.get(unit_id)
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
            actual = len(temporal) if sequence else len(resolve_reference_images(task))
            if planned is None:
                problems.append(f"FAIL_CORRECTED_PIPELINE_ANCHOR_UNIT_MISSING:{unit_id or 'UNKNOWN'}")
            elif task.get("planned_reference_image_count") != planned or actual != planned:
                problems.append(
                    f"FAIL_CORRECTED_PIPELINE_ANCHOR_BINDING:{unit_id or 'UNKNOWN'}:"
                    f"plan={planned}:task={task.get('planned_reference_image_count')}:actual={actual}"
                )
    return problems


def resolve_script_gate(
    manifest: dict[str, Any],
    beat_sheet_arg: str | None,
    report_arg: str | None,
) -> dict[str, Any]:
    binding = manifest.get("script_gate") or {}
    beat_sheet_value = beat_sheet_arg or binding.get("beat_sheet")
    report_value = report_arg or binding.get("report")
    if not beat_sheet_value or not report_value:
        return {
            "status": "FAIL",
            "beat_sheet": beat_sheet_value,
            "report": report_value,
            "failures": ["script_gate_binding_missing"],
        }
    beat_sheet = Path(beat_sheet_value)
    report = Path(report_value)
    if not beat_sheet.is_absolute():
        beat_sheet = BASE / beat_sheet
    if not report.is_absolute():
        report = BASE / report
    return verify_script_readiness_report(beat_sheet, report)


def resolve_script_density_gate(
    manifest: dict[str, Any],
    beat_sheet_arg: str | None,
    review_arg: str | None,
) -> dict[str, Any]:
    binding = manifest.get("script_density_gate") or {}
    script_value = beat_sheet_arg or binding.get("script") or binding.get("beat_sheet")
    review_value = review_arg or binding.get("review")
    episode = manifest.get("episode") or binding.get("episode")
    if not script_value or not review_value or not episode:
        return {
            "status": "FAIL",
            "blocked_by": "SCRIPT_DENSITY_GATE",
            "failures": ["script_density_gate_binding_missing"],
        }
    script = Path(script_value)
    review = Path(review_value)
    if not script.is_absolute():
        script = BASE / script
    if not review.is_absolute():
        review = BASE / review
    return evaluate_density_gate(
        str(episode),
        script,
        review.parent,
        review,
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_picture_only_repair_gate(manifest: dict[str, Any]) -> dict[str, Any]:
    binding = manifest.get("repair_gate") or {}
    failures: list[str] = []
    if binding.get("gate_type") != "picture_only_repair":
        failures.append("repair_gate_type_invalid")
    authorization_ref = manifest.get("authorization_ref")
    if not authorization_ref or binding.get("authorization_ref") != authorization_ref:
        failures.append("repair_authorization_ref_mismatch")

    evidence: dict[str, dict[str, Any]] = {}
    for name in ("source_disposition", "prompt_preflight", "visual_text_guard"):
        item = binding.get(name) or {}
        value = item.get("path")
        expected_sha = item.get("sha256")
        if not value or not expected_sha:
            failures.append(f"repair_evidence_binding_missing:{name}")
            continue
        path = Path(value)
        if not path.is_absolute():
            path = BASE / path
        if not path.is_file():
            failures.append(f"repair_evidence_missing:{name}")
            continue
        actual_sha = file_sha256(path)
        if actual_sha != expected_sha:
            failures.append(f"repair_evidence_sha256_mismatch:{name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            failures.append(f"repair_evidence_json_invalid:{name}")
            continue
        evidence[name] = payload

    disposition = evidence.get("source_disposition", {})
    preflight = evidence.get("prompt_preflight", {})
    guard = evidence.get("visual_text_guard", {})
    if disposition and disposition.get("authorization_ref") != authorization_ref:
        failures.append("repair_source_disposition_authorization_mismatch")
    if preflight and preflight.get("authorization_ref") != authorization_ref:
        failures.append("repair_prompt_preflight_authorization_mismatch")
    if preflight and not str(preflight.get("status", "")).startswith("PASS"):
        failures.append("repair_prompt_preflight_not_pass")
    if guard and guard.get("status") != "PASS":
        failures.append("repair_visual_text_guard_not_pass")
    if guard and int(guard.get("failure_count", -1)) != 0:
        failures.append("repair_visual_text_guard_has_failures")

    preflight_ids = {row.get("source_id") for row in preflight.get("prompts", [])}
    guard_paths = {str(Path(row.get("prompt_file", "")).resolve()) for row in guard.get("results", [])}
    for task in (row for row in manifest.get("tasks", []) if row.get("status") == "READY_TO_SUBMIT"):
        source_id = task.get("source_id")
        prompt_path = BASE / task["prompt_path"]
        prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
        _visual, audio = split_prompt_sections(prompt)
        if source_id not in preflight_ids and not task.get("repair_preflight_exemption"):
            failures.append(f"repair_task_missing_prompt_preflight:{source_id}")
        if str(prompt_path.resolve()) not in guard_paths and not task.get("repair_preflight_exemption"):
            failures.append(f"repair_task_missing_visual_text_guard:{source_id}")
        if not audio_section_is_empty(audio):
            failures.append(f"repair_task_audio_not_empty:{source_id}")
        expected_prompt_sha = task.get("prompt_sha256")
        if not expected_prompt_sha or not prompt_path.is_file() or file_sha256(prompt_path) != expected_prompt_sha:
            failures.append(f"repair_task_prompt_sha256_mismatch:{source_id}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "gate_type": "picture_only_repair",
        "authorization_ref": authorization_ref,
        "failures": failures,
    }


def resolve_submission_gate(
    manifest: dict[str, Any],
    beat_sheet_arg: str | None,
    report_arg: str | None,
    density_review_arg: str | None = None,
) -> dict[str, Any]:
    repair = resolve_picture_only_repair_gate(manifest) if manifest.get("repair_gate") else None
    readiness = resolve_script_gate(manifest, beat_sheet_arg, report_arg) if repair is None else {"status": "PASS", "failures": []}
    density = resolve_script_density_gate(manifest, beat_sheet_arg, density_review_arg) if repair is None else {"status": "PASS", "failures": []}
    failures = [f"script_readiness:{item}" for item in readiness.get("failures", [])]
    failures.extend(f"script_density:{item}" for item in density.get("failures", []))
    if repair is not None:
        failures.extend(f"repair_gate:{item}" for item in repair.get("failures", []))
    match = re.search(r"(\d+)", str(manifest.get("episode") or ""))
    episode_number = int(match.group(1)) if match else 0
    supervisor = {"status": "PASS", "generation_allowed": True, "failures": []}
    if episode_number >= 28 and manifest.get("tasks"):
        provenance = manifest.get("writer_agent_provenance") or {}
        supervisor = verify_supervisor_script_gate(
            manifest.get("episode"),
            provenance.get("generated_script"),
            provenance.get("compiled_script"),
            manifest.get("supervisor_script_gate_report"),
        )
        failures.extend(f"supervisor_script_gate:{item}" for item in supervisor.get("failures", []))
    all_pass = (
        readiness.get("status") == "PASS"
        and density.get("status") == "PASS"
        and (repair is None or repair.get("status") == "PASS")
        and supervisor.get("status") == "PASS"
        and supervisor.get("generation_allowed") is True
    )
    return {
        "status": "PASS" if all_pass else "FAIL",
        "gate_type": "repair_or_script_gates_plus_local_claude_supervision",
        "repair": repair,
        "readiness": readiness,
        "density": density,
        "supervisor": supervisor,
        "failures": failures,
    }


def resolve_reference_images(task: dict[str, Any]) -> list[str]:
    if "reference_images" in task:
        return list(task["reference_images"] or [])
    return [task["visual_lock"], task["speaker_reference"]]


def submit_one(task: dict[str, Any]) -> dict[str, Any]:
    task_dir = BASE / Path(task["prompt_path"]).parent
    prompt_path = BASE / task["prompt_path"]
    receipt_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task.get("source_id") or task.get("dialogue_id") or "task"))
    contract_problems = validate_prompt_contract(task, prompt_path)
    input_precheck = precheck_submission_inputs(task)
    if input_precheck["status"] != "PASS":
        contract_problems.append("MISSING_ANCHOR_FOR_CANONICAL_ENTITY")
    if task.get("state") == "retry_pending" or task.get("retry_count"):
        contract_problems.extend(validate_retry_change(task)["failures"])
    if contract_problems:
        failure = {
            "dialogue_id": task.get("dialogue_id"),
            "status": "BLOCKED_PRECHECK",
            "prompt_constitution_version": CONSTITUTION_VERSION,
            "problems": contract_problems,
            "prompt_path": str(prompt_path),
        }
        (task_dir / f"{receipt_stem}_submit_blocked_prompt_contract.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        return failure
    receipt = task_dir / f"{receipt_stem}_submit_receipt.json"
    if receipt.exists() and not task.get("force_resubmit"):
        try:
            prior = json.loads(receipt.read_text(encoding="utf-8"))
            task_id = (prior.get("data") or {}).get("task_id") or prior.get("task_id")
            if task_id:
                return {"dialogue_id": task.get("dialogue_id"), "status": "ALREADY_SUBMITTED", "receipt": str(receipt), "task_id": task_id, "prompt_constitution_version": CONSTITUTION_VERSION}
        except Exception:
            pass

    reference_images = resolve_reference_images(task)
    args = [
        "python3",
        str(CLIENT),
        "omni-video",
        "--prompt-file",
        str(prompt_path),
    ]
    for reference_image in reference_images:
        args.extend(["--reference-image", str(BASE / reference_image)])
    args.extend([
        "--model",
        task.get("model", "seedance-2.0-fast"),
        "--duration",
        str(task.get("duration", 4)),
        "--aspect-ratio",
        task.get("aspect_ratio", "9:16"),
        "--resolution",
        task.get("resolution", "720p"),
        "--count",
        "1",
    ])
    proc = subprocess.run(args, cwd=BASE, env=os.environ.copy(), text=True, capture_output=True)
    if proc.returncode != 0:
        failure = {
            "dialogue_id": task.get("dialogue_id"),
            "status": "SUBMIT_FAILED",
            "stderr": proc.stderr[-2000:],
            "stdout": proc.stdout[-2000:],
        }
        (task_dir / f"{receipt_stem}_submit_failure.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        return failure
    receipt.write_text(proc.stdout, encoding="utf-8")
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = {}
    task_id = (data.get("data") or {}).get("task_id") or data.get("task_id")
    return {"dialogue_id": task.get("dialogue_id"), "status": "SUBMITTED", "receipt": str(receipt), "task_id": task_id}


def evaluate_video_submission_guards(
    manifest: dict[str, Any], ready: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[str]]:
    if not ready:
        return None, []
    episode = str(manifest.get("episode") or "").upper()
    if not re.fullmatch(r"E\d+", episode):
        return None, ["FAIL_VIDEO_CREDIT_GATE:EPISODE_REQUIRED"]

    authority_gate = evaluate_episode_submission_authority(episode)
    if authority_gate.get("status") != "PASS":
        return authority_gate, [
            "FAIL_EPISODE_VIDEO_SUBMISSION_AUTHORITY:"
            f"{authority_gate.get('status')}:"
            f"reason={authority_gate.get('reason') or 'unspecified'}"
        ]

    gate = evaluate_episode_credit_gate(episode)
    report_path = credit_report_path(episode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if gate.get("status") != "PASS":
        return gate, [
            "FAIL_VIDEO_CREDIT_GATE:"
            f"{gate.get('status')}:"
            f"actual={gate.get('actual_charged_credits_known_total')}:"
            f"effective_limit={gate.get('effective_limit_credits')}"
        ]

    failures: list[str] = []
    for task in ready:
        task.setdefault("tool_type", "video_generation")
        task.setdefault("prompt_file", task.get("prompt_path"))
        task.setdefault("reference_images", resolve_reference_images(task))
        task["generation_fingerprint"] = generation_fingerprint(task)
        existing = find_existing_paid_candidate(episode, task)
        if existing:
            failures.append(
                "FAIL_UNCHANGED_VIDEO_REGENERATION:"
                f"{task.get('source_id') or task.get('dialogue_id') or 'unknown'}:"
                f"task_id={existing.get('task_id')}"
            )
    return gate, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out")
    parser.add_argument("--beat-sheet")
    parser.add_argument("--script-gate-report")
    parser.add_argument("--script-density-review")
    parser.add_argument("--precheck-only", action="store_true")
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = BASE / manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    episode_match = re.match(r"E(\d+)(?:\D|$)", str(manifest.get("episode") or "").upper())
    ready = [task for task in manifest.get("tasks", []) if task.get("status") == "READY_TO_SUBMIT"]
    episode_match = re.match(r"E(\d+)(?:\D|$)", str(manifest.get("episode") or "").upper())
    if episode_match and int(episode_match.group(1)) >= 40:
        for task in ready:
            task["media_stage"] = "VIDEO"
            task["require_semantic_anchor_evidence"] = True
            task.setdefault("semantic_anchor_policy_version", "1.0.0")
    submission_gate = resolve_submission_gate(
        manifest,
        args.beat_sheet,
        args.script_gate_report,
        args.script_density_review,
    )
    manifest_problems = validate_manifest_constitution(manifest, ready)
    if episode_match and int(episode_match.group(1)) >= 40 and ready and not args.precheck_only:
        manifest_problems.append(
            "E40_PLUS_LEGACY_NON_TRANSACTIONAL_SUBMIT_DISABLED: use "
            "submit_giggle_image_manifest.py or deployed submit_giggle_video_manifest_v2.py"
        )
    manifest_problems.extend(validate_ready_task_contracts(ready))
    manifest_problems.extend(validate_keyframe_admissions(manifest, ready))
    manifest_problems.extend(validate_corrected_pipeline_reports(manifest, ready))
    if ready and submission_gate["status"] != "PASS":
        manifest_problems.extend(
            f"FAIL_SUBMISSION_GATE:{failure}" for failure in submission_gate["failures"]
        )
    video_credit_gate, video_guard_problems = evaluate_video_submission_guards(manifest, ready)
    manifest_problems.extend(video_guard_problems)
    key_env_source = (
        "NOT_REQUIRED_PRECHECK_ONLY"
        if args.precheck_only
        else "BLOCKED_BEFORE_KEY_LOAD"
        if manifest_problems
        else ensure_giggle_api_key()
    )
    results: list[dict[str, Any]] = []
    if manifest_problems:
        results = [
            {
                "dialogue_id": task.get("dialogue_id"),
                "status": "BLOCKED_PRECHECK",
                "prompt_constitution_version": CONSTITUTION_VERSION,
                "problems": manifest_problems,
                "prompt_path": str(BASE / task["prompt_path"]),
            }
            for task in ready
        ]
    elif args.precheck_only:
        results = [
            {
                "dialogue_id": task.get("dialogue_id"),
                "status": "PRECHECK_PASS",
                "prompt_constitution_version": CONSTITUTION_VERSION,
                "prompt_path": str(BASE / task["prompt_path"]),
            }
            for task in ready
        ]
    else:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = [pool.submit(submit_one, task) for task in ready]
            for future in as_completed(futures):
                results.append(future.result())
    results.sort(key=lambda item: item.get("dialogue_id") or "")
    report = {
        "schema": "qingshan.giggle_manifest_submit_report.v1",
        "source_manifest": str(manifest_path),
        "submission_gate": submission_gate,
        "episode_video_credit_gate": video_credit_gate,
        "script_gate": submission_gate if submission_gate.get("gate_type") != "picture_only_repair" else None,
        "prompt_constitution_version": manifest.get("prompt_constitution_version", CONSTITUTION_VERSION),
        "prompt_constitution_precheck": "PASS" if not manifest_problems else "FAIL",
        "prompt_constitution_manifest_problems": manifest_problems,
        "giggle_key_environment": key_env_source,
        "precheck_only": args.precheck_only,
        "status": "PASS" if all(item["status"] in {"SUBMITTED", "ALREADY_SUBMITTED", "PRECHECK_PASS"} for item in results) else "FAIL",
        "precheck_pass": sum(1 for item in results if item["status"] == "PRECHECK_PASS"),
        "submitted": sum(1 for item in results if item["status"] == "SUBMITTED"),
        "already_submitted": sum(1 for item in results if item["status"] == "ALREADY_SUBMITTED"),
        "failed": sum(1 for item in results if item["status"] in {"SUBMIT_FAILED", "BLOCKED_PRECHECK"}),
        "results": results,
    }
    out = Path(args.out) if args.out else manifest_path.with_name(manifest_path.stem + "_submit_report.json")
    if not out.is_absolute():
        out = BASE / out
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "submitted": report["submitted"], "already_submitted": report["already_submitted"], "failed": report["failed"], "report": str(out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
