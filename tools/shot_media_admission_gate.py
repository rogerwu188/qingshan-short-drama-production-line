#!/usr/bin/env python3
"""Aggregate exact-SHA keyframe/video content evidence into honest admissions.

This is not a new quality gate.  It is a fail-closed aggregator for already
registered gates so advisory reports and technical decode checks cannot be
misrepresented as content admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
KEYFRAME_REQUIRED_GATES = (
    "CHARACTER-IDENTITY-ADMISSION",
    "SCENE-AUTHORITY-LOCK",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
)
VIDEO_REQUIRED_GATES = (*KEYFRAME_REQUIRED_GATES, "DEFECT-TIER-TOLERANCE")
P0_OBJECTIVE_GATES = frozenset({
    "CHARACTER-IDENTITY-ADMISSION",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "PERIOD-ANACHRONISM-LOCK",
})
P0_OBJECTIVE_METHODS = {
    "CHARACTER-IDENTITY-ADMISSION": "INSIGHTFACE_COSINE_V1",
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": "VLM_STRUCTURED_STATE_QA_V1",
    "PERIOD-ANACHRONISM-LOCK": "CLOSED_SET_ANACHRONISM_OCR_V1",
}
NO_CHARACTER_IDENTITY_METHOD = "STRUCTURED_NO_VISIBLE_CHARACTER_V1"
ADVISORY_STATUSES = {"ADVISORY", "ADVISORY_NOT_A_GATE", "DIAGNOSTIC", "WARNING"}
PASS_STATUSES = {"PASS", "PASS_EXACT_SHA", "PASS_ORIGINAL_RESOLUTION"}
FAILURE_ATTRIBUTIONS = frozenset({
    "MISSING_REFERENCE_ANCHOR",
    "PROMPT_SEMANTICS",
    "SPACE_CHAIN_MISMATCH",
    "CANONICAL_MISMATCH",
    "MODEL_STOCHASTIC",
})
ATTRIBUTION_REQUIRED_CHANGE = {
    "MISSING_REFERENCE_ANCHOR": "REFERENCE_ANCHORS",
    "PROMPT_SEMANTICS": "PROMPT",
    "SPACE_CHAIN_MISMATCH": "SPACE_CHAIN",
    "CANONICAL_MISMATCH": "QA_TARGET",
    "MODEL_STOCHASTIC": "NONE",
}
CHARACTER_ROLES = frozenset({"CHARACTER", "IDENTITY", "CHARACTER_REFERENCE", "SPEAKER"})
PROP_ROLES = frozenset({"PROP", "PROP_REFERENCE", "OBJECT", "OBJECT_REFERENCE"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(value: Any, root: Path) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def _registered_gate_ids(registry: dict[str, Any]) -> set[str]:
    return {str(row.get("gate_id")) for row in registry.get("gates") or [] if row.get("gate_id")}


def _gate_parameters(registry: dict[str, Any], gate_id: str) -> dict[str, Any]:
    for row in registry.get("gates") or []:
        if row.get("gate_id") == gate_id:
            return row.get("parameters") or {}
    return {}


def _objective_p0_pass(
    gate_id: str, payload: dict[str, Any], registry: dict[str, Any]
) -> tuple[bool, str]:
    verification = payload.get("objective_verification") or {}
    method = str(verification.get("method") or "")
    expected = P0_OBJECTIVE_METHODS.get(gate_id)
    if (
        gate_id == "CHARACTER-IDENTITY-ADMISSION"
        and method == NO_CHARACTER_IDENTITY_METHOD
    ):
        checks = verification.get("checks") or []
        if verification.get("canonical_characters") not in ([], None):
            return False, "p0_no_character_scope_has_canonical_character"
        if not checks or any(
            str(row.get("answer") or row.get("status") or "").upper() != "PASS"
            for row in checks
        ):
            return False, "p0_no_character_structured_checks_not_pass"
        return True, ""
    if method != expected:
        return False, f"p0_objective_method_invalid:{method or 'MISSING'}"
    if str(verification.get("decision") or "").upper() != "PASS":
        return False, "p0_objective_decision_not_pass"
    if gate_id == "CHARACTER-IDENTITY-ADMISSION":
        parameters = _gate_parameters(registry, gate_id)
        if float(verification.get("pass_threshold", -1)) != float(
            parameters.get("embedding_cosine_pass_threshold", -2)
        ):
            return False, "p0_identity_threshold_not_registry_bound"
        decisions = verification.get("decisions") or []
        if not decisions or any(str(row.get("decision") or "") != "PASS" for row in decisions):
            return False, "p0_identity_sample_decision_not_pass"
        if int(verification.get("canonical_views_min") or 0) < int(parameters.get("canonical_views_min", 3)):
            return False, "p0_identity_canonical_views_below_registry"
        if int(verification.get("sample_frames_per_source_min") or 0) < int(
            parameters.get("sample_frames_per_source_min", 3)
        ):
            return False, "p0_identity_samples_below_registry"
    else:
        checks = verification.get("checks") or []
        if not checks or any(str(row.get("answer") or row.get("status") or "").upper() != "PASS" for row in checks):
            return False, "p0_structured_checks_not_pass"
    return True, ""


def _entity_ids(rows: Any, key: str) -> set[str]:
    if not isinstance(rows, list):
        return set()
    values: set[str] = set()
    for row in rows:
        value = row.get(key) if isinstance(row, dict) else row
        if value:
            values.add(str(value))
    return values


def _canonical_entities(task: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return the exact characters/props declared visible in this unit.

    The function intentionally does not mine free-form prompt text.  A paid
    task must carry a mechanical canonical declaration (directly, through its
    prompt contract, or through the locked blocking plan).
    """
    contract = task.get("prompt_contract") or {}
    characters = set(map(str, task.get("canonical_characters") or []))
    characters.update(map(str, task.get("visible_characters") or []))
    characters.update(map(str, contract.get("visible_characters") or []))
    props = set(map(str, task.get("canonical_props") or []))
    props.update(map(str, contract.get("canonical_props") or []))
    for key in ("blocking", "action_end_blocking"):
        block = task.get(key) or {}
        characters.update(_entity_ids(block.get("characters"), "character_id"))
        props.update(_entity_ids(block.get("props"), "prop_id"))
    return {value for value in characters if value}, {value for value in props if value}


def _normalize_reference_path(value: Any, root: Path) -> str:
    path = Path(str(value or ""))
    return str((path if path.is_absolute() else root / path).resolve()) if value else ""


def _transmitted_reference_paths(task: dict[str, Any], root: Path) -> set[str]:
    rows = task.get("reference_image_sequence")
    if isinstance(rows, list) and rows:
        return {
            _normalize_reference_path(row.get("path") or row.get("asset_path"), root)
            for row in rows if isinstance(row, dict) and (row.get("path") or row.get("asset_path"))
        }
    return {_normalize_reference_path(value, root) for value in task.get("reference_images") or [] if value}


def _reference_bindings(task: dict[str, Any]) -> list[dict[str, Any]]:
    sequence = task.get("reference_image_sequence")
    if isinstance(sequence, list) and sequence:
        return [row for row in sequence if isinstance(row, dict)]
    rows = task.get("reference_bindings")
    if not isinstance(rows, list):
        rows = (task.get("prompt_contract") or {}).get("reference_bindings")
    if not isinstance(rows, list):
        rows = task.get("reference_entity_bindings")
    return [row for row in (rows or []) if isinstance(row, dict)]


def precheck_submission_inputs(
    task: dict[str, Any],
    asset_catalog: dict[str, Any] | None = None,
    *,
    enforce: bool = True,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Check canonical entity anchors before any paid image/video POST."""
    characters, props = _canonical_entities(task)
    contract = task.get("prompt_contract") or {}
    declaration_present = any(
        key in task for key in (
            "canonical_characters", "visible_characters", "canonical_props",
            "blocking", "action_end_blocking",
        )
    ) or any(key in contract for key in ("visible_characters", "canonical_props"))
    transmitted = _transmitted_reference_paths(task, root)
    bindings = _reference_bindings(task)
    bound_characters: set[str] = set()
    bound_props: set[str] = set()
    for row in bindings:
        entity_id = str(row.get("entity_id") or "")
        role = str(row.get("role") or "").upper()
        path = _normalize_reference_path(row.get("path") or row.get("asset_path"), root)
        # A catalog entry or manifest binding is not enough: the referenced
        # file must also be in the exact sequence sent to the provider.
        if not entity_id or not path or (transmitted and path not in transmitted):
            continue
        if role in CHARACTER_ROLES or entity_id.startswith("CHAR-"):
            bound_characters.add(entity_id)
        if role in PROP_ROLES or entity_id.startswith("PROP-"):
            bound_props.add(entity_id)
    missing_characters = sorted(characters - bound_characters)
    missing_props = sorted(props - bound_props)
    catalog = asset_catalog or task.get("anchor_asset_catalog") or {}
    available = catalog.get("entities") if isinstance(catalog, dict) else {}
    if not isinstance(available, dict):
        available = {}
    missing = missing_characters + missing_props
    media_stage = str(task.get("media_stage") or "KEYFRAME").upper()
    semantic_policy_declared = "require_semantic_anchor_evidence" in task
    semantic_policy = (
        True if media_stage == "VIDEO"
        else bool(task.get("require_semantic_anchor_evidence"))
    )
    semantic_policy_failures: list[str] = []
    if media_stage == "VIDEO" and not semantic_policy_declared:
        semantic_policy_failures.append("SEMANTIC_ANCHOR_POLICY_NOT_DECLARED")
    elif media_stage == "VIDEO" and task.get("require_semantic_anchor_evidence") is not True:
        semantic_policy_failures.append("SEMANTIC_ANCHOR_POLICY_DISABLED_FOR_VIDEO")
    semantic_evidence_missing: list[str] = []
    semantic_evidence_invalid: list[str] = []
    start_frame_admission: dict[str, Any] | None = None
    if semantic_policy and media_stage == "VIDEO":
        admission_value = task.get("start_frame_admission_ref") or task.get("q1_admission_result")
        admission_path = _resolve(admission_value, root)
        if not admission_value or not admission_path.is_file():
            semantic_evidence_missing.append("Q1_ADMITTED_START_FRAME")
        else:
            try:
                start_frame_admission = json.loads(admission_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                semantic_evidence_invalid.append("Q1_ADMISSION_UNREADABLE")
            if start_frame_admission is not None:
                status = str(start_frame_admission.get("status") or "")
                downstream = str(start_frame_admission.get("downstream_status") or "")
                admitted_sha = str(start_frame_admission.get("asset_sha256") or "")
                expected_sha = str(task.get("exact_first_frame_sha256") or task.get("start_frame_sha256") or "")
                if status not in {"ADMITTED", "ADMITTED_WITH_P2"}:
                    semantic_evidence_invalid.append("Q1_START_FRAME_NOT_ADMITTED")
                if downstream and downstream != "ADMITTED_FOR_VIDEO_SUBMIT":
                    semantic_evidence_invalid.append("Q1_DOWNSTREAM_STATUS_INVALID")
                if not expected_sha or admitted_sha != expected_sha:
                    semantic_evidence_invalid.append("Q1_START_FRAME_SHA_MISMATCH")
    elif semantic_policy:
        entity_rows: dict[str, list[dict[str, Any]]] = {}
        for row in bindings:
            entity_id = str(row.get("entity_id") or "")
            if entity_id in characters or entity_id in props:
                entity_rows.setdefault(entity_id, []).append(row)
        for entity_id in sorted(characters | props):
            rows = entity_rows.get(entity_id) or []
            valid = False
            for row in rows:
                source_value = row.get("source_component_path") or row.get("path") or row.get("asset_path")
                source_path = _resolve(source_value, root)
                declared_source_sha = str(row.get("source_component_sha256") or row.get("sha256") or "")
                qa_value = row.get("qa_report") or row.get("semantic_qa_report")
                origin = str(row.get("asset_origin") or "")
                if (
                    source_value and source_path.is_file()
                    and declared_source_sha == sha256_file(source_path)
                    and qa_value and _resolve(qa_value, root).is_file()
                    and origin in {
                        "CANONICAL_NATIVE_REGISTRY", "CANONICAL_PROP_REGISTRY",
                        "ADMITTED_PRIOR_EPISODE_NATIVE", "EPISODE_NEW_ASSET",
                    }
                ):
                    valid = True
                    break
            if not valid:
                semantic_evidence_missing.append(entity_id)
    failures: list[str] = list(semantic_policy_failures)
    if not declaration_present:
        failures.append("CANONICAL_ENTITY_DECLARATION_MISSING")
    if missing:
        failures.append("MISSING_ANCHOR_FOR_CANONICAL_ENTITY")
    if semantic_evidence_missing:
        failures.append("SEMANTIC_ANCHOR_EVIDENCE_MISSING")
    if semantic_evidence_invalid:
        failures.append("SEMANTIC_ANCHOR_EVIDENCE_INVALID")
    status = "PASS" if not failures else ("FAIL" if enforce else "WARNING")
    return {
        "schema": "qingshan.submission_input_precheck.v2",
        "gate_id": "CHARACTER-IDENTITY-ADMISSION",
        "check_stage": "BEFORE_PAID_SUBMIT",
        "status": status,
        "failure_code": failures[0] if failures else None,
        "failure_attribution": (
            "MISSING_REFERENCE_ANCHOR"
            if missing or semantic_evidence_missing or semantic_evidence_invalid
            else "CANONICAL_MISMATCH" if failures else None
        ),
        "failures": failures,
        "canonical_entity_declaration_present": declaration_present,
        "canonical_characters": sorted(characters),
        "canonical_props": sorted(props),
        "bound_characters": sorted(bound_characters),
        "bound_props": sorted(bound_props),
        "missing_characters": missing_characters,
        "missing_props": missing_props,
        "available_library_anchors": {
            entity_id: available.get(entity_id) for entity_id in missing if available.get(entity_id)
        },
        "media_stage": media_stage,
        "semantic_anchor_policy_enforced": semantic_policy,
        "semantic_anchor_policy_declared": semantic_policy_declared,
        "semantic_evidence_missing": semantic_evidence_missing,
        "semantic_evidence_invalid": semantic_evidence_invalid,
        "enforced": enforce,
    }


def compute_input_template_id(task: dict[str, Any]) -> str:
    """Stable grouping key; computing it never serializes provider submits."""
    characters, _props = _canonical_entities(task)
    payload = {
        "space_chain_id": task.get("space_chain_id") or task.get("global_space_map_id"),
        "reference_spec": [
            {"role": row.get("role"), "entity_id": row.get("entity_id")}
            for row in _reference_bindings(task)
        ],
        "prompt_template": task.get("prompt_template_id") or task.get("prompt_contract_version"),
        "character_group": sorted(characters),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def aggregate_template_defects(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Find repeated same-cause failures without introducing a canary wait."""
    groups: dict[tuple[str, str], list[str]] = {}
    for task in tasks:
        state = str(task.get("state") or "")
        if state and state not in {
            "retry_pending", "submit_failed", "submit_failed_terminal",
            "qa_failed_terminal", "remote_failed_terminal", "template_defect_pending",
        }:
            continue
        attribution = str(task.get("failure_attribution") or "")
        if attribution not in FAILURE_ATTRIBUTIONS:
            continue
        template_id = str(task.get("input_template_id") or compute_input_template_id(task))
        groups.setdefault((template_id, attribution), []).append(
            str(task.get("task_key") or task.get("unit_id") or "UNKNOWN")
        )
    defects = [
        {"input_template_id": template_id, "failure_attribution": attribution,
         "status": "TEMPLATE_DEFECT", "affected_task_keys": sorted(keys)}
        for (template_id, attribution), keys in sorted(groups.items()) if len(keys) >= 2
    ]
    return {
        "status": "TEMPLATE_DEFECT" if defects else "PASS_NO_TEMPLATE_DEFECT",
        "template_defects": defects,
        "serial_wait_introduced": False,
    }


def validate_retry_change(task: dict[str, Any]) -> dict[str, Any]:
    attribution = str(task.get("failure_attribution") or "")
    changed = {str(value).upper() for value in task.get("changed_variables") or []}
    failures: list[str] = []
    if attribution not in FAILURE_ATTRIBUTIONS:
        failures.append("FAILURE_ATTRIBUTION_INVALID")
    else:
        required = ATTRIBUTION_REQUIRED_CHANGE[attribution]
        if required != "NONE" and required not in changed:
            failures.append("RETRY_CHANGED_WRONG_VARIABLE")
        if attribution == "MODEL_STOCHASTIC" and changed:
            failures.append("RETRY_CHANGED_WRONG_VARIABLE")
        if attribution == "CANONICAL_MISMATCH":
            failures.append("CANONICAL_MISMATCH_MEDIA_RETRY_FORBIDDEN")
    same_count = int(task.get("same_attribution_consecutive_count") or 0)
    if same_count >= 2:
        failures.append("SWITCH_COVERAGE_REQUIRED")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_attribution": attribution,
        "required_changed_variable": ATTRIBUTION_REQUIRED_CHANGE.get(attribution),
        "changed_variables": sorted(changed),
        "failures": failures,
    }


def evaluate(
    admission: dict[str, Any], registry: dict[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    kind = str(admission.get("kind") or "").upper()
    failures: list[str] = []
    diagnostics: list[str] = []
    if kind not in {"KEYFRAME_VIDEO_SUBMIT", "VIDEO_ASSEMBLY"}:
        failures.append("admission_kind_invalid")
    required = KEYFRAME_REQUIRED_GATES if kind == "KEYFRAME_VIDEO_SUBMIT" else VIDEO_REQUIRED_GATES

    asset_path = _resolve(admission.get("asset_path"), root)
    declared_asset_sha = str(admission.get("asset_sha256") or "")
    actual_asset_sha = sha256_file(asset_path) if asset_path.is_file() else ""
    if not asset_path.is_file():
        failures.append(f"asset_missing:{asset_path}")
    elif not declared_asset_sha or declared_asset_sha != actual_asset_sha:
        failures.append("asset_sha256_mismatch")

    registered = _registered_gate_ids(registry)
    passing: set[str] = set()
    conditional_p2: set[str] = set()
    p2_defects: list[dict[str, Any]] = []
    original_resolution_review = False
    evidence_rows = admission.get("evidence")
    if not isinstance(evidence_rows, list):
        evidence_rows = []
        failures.append("evidence_missing")
    for index, row in enumerate(evidence_rows, 1):
        gate_id = str(row.get("gate_id") or "")
        status = str(row.get("status") or "").upper()
        reviewer_type = str(row.get("reviewer_type") or "").upper()
        prefix = f"evidence_{index}:{gate_id or 'UNKNOWN'}"
        if gate_id not in registered:
            diagnostics.append(f"{prefix}:unregistered_gate_downgraded_to_diagnostic")
            continue
        if status in ADVISORY_STATUSES or row.get("advisory_only") is True:
            diagnostics.append(f"{prefix}:advisory_not_admission")
            continue
        reviewed_sha = str(row.get("reviewed_asset_sha256") or "")
        if reviewed_sha != declared_asset_sha:
            failures.append(f"{prefix}:reviewed_asset_sha256_mismatch")
            continue
        evidence_path = _resolve(row.get("evidence_path"), root)
        if not evidence_path.is_file():
            failures.append(f"{prefix}:evidence_file_missing")
            continue
        evidence_sha = str(row.get("evidence_sha256") or "")
        if not evidence_sha or evidence_sha != sha256_file(evidence_path):
            failures.append(f"{prefix}:evidence_sha256_mismatch")
            continue
        try:
            evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append(f"{prefix}:evidence_json_unreadable")
            continue
        declared_gate = str(evidence_payload.get("gate_id") or evidence_payload.get("registered_gate_id") or "")
        if declared_gate and declared_gate != gate_id:
            failures.append(f"{prefix}:evidence_gate_id_mismatch")
            continue
        declared_status = str(evidence_payload.get("status") or "").upper()
        if declared_status and declared_status not in PASS_STATUSES and status in PASS_STATUSES:
            failures.append(f"{prefix}:evidence_payload_not_pass:{declared_status}")
            continue
        if gate_id in P0_OBJECTIVE_GATES and status in PASS_STATUSES:
            # Reviewer labels never substitute for the registered objective
            # method.  Human involvement is useful for boundary arbitration,
            # but "HUMAN_AND_AI" must not become a self-asserted P0 bypass.
            if reviewer_type not in {"HUMAN", "AI_VISUAL", "HUMAN_AND_AI"}:
                failures.append(f"{prefix}:p0_verifier_missing:{reviewer_type or 'MISSING'}")
                continue
            objective_ok, reason = _objective_p0_pass(gate_id, evidence_payload, registry)
            if not objective_ok:
                failures.append(f"{prefix}:{reason}")
                continue
        defect_tier = str(row.get("defect_tier") or "").upper()
        p2_within_budget = row.get("p2_within_budget") is True
        if status in PASS_STATUSES:
            passing.add(gate_id)
        elif defect_tier == "P2" and p2_within_budget:
            conditional_p2.add(gate_id)
            p2_defects.append({
                "gate_id": gate_id,
                "evidence_path": str(evidence_path),
                "defect": row.get("defect") or row.get("finding"),
            })
        else:
            defect_tier = defect_tier or "UNCLASSIFIED"
            failures.append(f"{prefix}:registered_gate_not_pass:{status}:{defect_tier}")
        if row.get("original_resolution_review") is True and reviewer_type in {
            "HUMAN", "AI_VISUAL", "HUMAN_AND_AI"
        }:
            original_resolution_review = True

    for gate_id in required:
        if gate_id not in passing and gate_id not in conditional_p2:
            failures.append(f"required_registered_gate_not_pass:{gate_id}")
    if not original_resolution_review:
        failures.append("original_resolution_content_review_missing")

    technical = admission.get("technical_qa") or {}
    if kind == "VIDEO_ASSEMBLY":
        if technical.get("status") != "TECHNICAL_PASS_CONTENT_UNREVIEWED":
            failures.append("technical_qa_status_missing_or_dishonest")
        if str(technical.get("reviewed_asset_sha256") or "") != declared_asset_sha:
            failures.append("technical_qa_asset_sha256_mismatch")
    elif technical.get("status") in {"PASS", "QA_PASS", "ADMITTED_FOR_ASSEMBLY"}:
        failures.append("keyframe_technical_status_misrepresented_as_content_admission")

    downstream_status = (
        "ADMITTED_FOR_VIDEO_SUBMIT" if kind == "KEYFRAME_VIDEO_SUBMIT"
        else "ADMITTED_FOR_ASSEMBLY"
    )
    status = "FAIL"
    if not failures:
        status = "ADMITTED_WITH_P2" if conditional_p2 else "ADMITTED"
    return {
        "schema": "qingshan.shot_media_admission.v2",
        "kind": kind,
        "asset_path": str(asset_path),
        "asset_sha256": declared_asset_sha,
        "status": status,
        "downstream_status": downstream_status if not failures else "FAIL_NOT_ADMITTED",
        "required_registered_gates": list(required),
        "passing_registered_gates": sorted(passing),
        "conditional_p2_registered_gates": sorted(conditional_p2),
        "p2_defect_ledger": p2_defects,
        "original_resolution_content_review": original_resolution_review,
        "failures": failures,
        "diagnostics": diagnostics,
        "policy": {
            "technical_pass_is_not_content_pass": True,
            "advisory_is_not_admission": True,
            "unregistered_criteria_are_diagnostic_only": True,
            "exact_asset_sha_binding_required": True,
            "p0_requires_objective_verification_not_blanket_human_review": True,
            "p0_machine_boundary_requires_human_arbitration": True,
        },
    }


def evaluate_path(path: str | Path, root: Path = ROOT) -> dict[str, Any]:
    source = _resolve(path, root)
    registry = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    return evaluate(json.loads(source.read_text(encoding="utf-8")), registry, root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        json.loads(args.admission.read_text(encoding="utf-8")),
        json.loads(args.registry.read_text(encoding="utf-8")),
        ROOT,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "failures": result["failures"]}, ensure_ascii=False))
    return 0 if result["status"] in {"ADMITTED", "ADMITTED_WITH_P2"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
