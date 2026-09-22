#!/usr/bin/env python3
"""Fail-closed StoryClaw asset-plan and confirmation gate.

This module is deliberately independent from ``storyclaw_nalu_runtime.py`` so
the deployment adapter can call one validator without reimplementing script or
receipt authority.  It performs no writes and never treats a proposal as a
confirmation.

The plan schema validated here is ``storyclaw.asset_match_plan.v2``.  Its
``script_evidence`` block is produced by :func:`build_script_evidence`; it binds
the exact four writer layers, the S1 pipeline-state evidence, the enforced
seq=29 writer self-check, the episode, and the private series scope.  Matched
assets must be real files below a declared private root.  Every script-derived
character, scene, and prop must be covered exactly once by either a matched
asset or a priced AI-generation proposal.

Confirmation is a second authority.  A receipt is accepted only below the
configured private receipt root, only when its externally recorded file SHA is
supplied, and only when it binds the current plan and script-evidence SHAs.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Collection, Mapping, Sequence


PLAN_SCHEMA = "storyclaw.asset_match_plan.v2"
SCRIPT_EVIDENCE_SCHEMA = "storyclaw.script_evidence.v2"
CONFIRMATION_RECEIPT_SCHEMA = "storyclaw.asset_plan_confirmation_receipt.v1"
REPORT_SCHEMA = "storyclaw.asset_plan_gate.v1"
LAYER_NAMES = (
    "narrative_canonical",
    "directing_script",
    "generation_contract",
    "writer_manifest",
)
ENTITY_TYPES = ("character", "scene", "prop")
MATCH_LISTS = {
    "character": "character_matches",
    "scene": "scene_matches",
    "prop": "prop_matches",
}
DEFAULT_ALLOWED_GENERATION_MODELS = frozenset({"gpt-image-2-pro"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_PHOTO_KINDS = {"photo", "portrait", "reference_photo", "still_photo"}
_USER_UPLOAD_KINDS = {"user_upload", "uploaded_by_user"}


class AssetPlanRefused(RuntimeError):
    """Raised by ``require_*`` helpers when a validation gate blocks."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=True))
            return True
        except (OSError, ValueError):
            continue
    return False


def _normalise_private_roots(private_roots: Sequence[Path]) -> tuple[list[Path], list[str]]:
    roots: list[Path] = []
    failures: list[str] = []
    if not private_roots:
        return roots, ["PRIVATE_ROOTS_MISSING"]
    for index, value in enumerate(private_roots):
        path = Path(value).expanduser()
        if not path.is_absolute():
            failures.append(f"PRIVATE_ROOT_NOT_ABSOLUTE:{index}")
            continue
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            failures.append(f"PRIVATE_ROOT_MISSING:{index}")
            continue
        if not resolved.is_dir():
            failures.append(f"PRIVATE_ROOT_NOT_DIRECTORY:{index}")
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots, failures


def _binding(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256_file(resolved)}


def _stage_s1_status(document: dict[str, Any]) -> Any:
    stages = document.get("stages")
    if isinstance(stages, dict):
        row = stages.get("S1")
        if isinstance(row, dict):
            return row.get("status")
    if document.get("stage") == "S1":
        return document.get("status")
    return None


def _document_scope(document: dict[str, Any]) -> str | None:
    for key in ("series_scope_id", "scope_id"):
        if str(document.get(key) or "").strip():
            return str(document[key]).strip()
    nested = document.get("series_scope")
    if isinstance(nested, dict):
        for key in ("scope_id", "series_scope_id", "series_id"):
            if str(nested.get(key) or "").strip():
                return str(nested[key]).strip()
    return None


def _script_evidence(
    *,
    episode: str,
    series_scope_id: str,
    generation_contract_path: Path,
    layer_paths: Mapping[str, Path],
    s1_gate_evidence_path: Path,
    s2_gate_evidence_path: Path,
    seq29_report_path: Path,
    private_roots: Sequence[Path],
) -> tuple[dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    roots, root_failures = _normalise_private_roots(private_roots)
    failures.extend(root_failures)
    if not re.fullmatch(r"E\d+", str(episode or "")):
        failures.append("EPISODE_INVALID")
    if not str(series_scope_id or "").strip():
        failures.append("SERIES_SCOPE_ID_MISSING")

    supplied_names = set(layer_paths)
    if supplied_names != set(LAYER_NAMES):
        failures.append("FOUR_LAYER_SET_INVALID")

    layer_bindings: dict[str, dict[str, str]] = {}
    for name in LAYER_NAMES:
        raw = layer_paths.get(name)
        if raw is None:
            failures.append(f"LAYER_MISSING:{name}")
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            failures.append(f"LAYER_PATH_NOT_ABSOLUTE:{name}")
            continue
        if not path.is_file():
            failures.append(f"LAYER_FILE_MISSING:{name}")
            continue
        if not _inside(path, roots):
            failures.append(f"LAYER_NOT_PRIVATE:{name}")
            continue
        layer_bindings[name] = _binding(path)

    contract_path = Path(generation_contract_path).expanduser()
    if not contract_path.is_absolute():
        failures.append("GENERATION_CONTRACT_PATH_NOT_ABSOLUTE")
    elif "generation_contract" in layer_bindings:
        try:
            if contract_path.resolve(strict=True) != Path(
                layer_bindings["generation_contract"]["path"]
            ):
                failures.append("GENERATION_CONTRACT_LAYER_PATH_MISMATCH")
        except OSError:
            failures.append("GENERATION_CONTRACT_FILE_MISSING")

    contract = _json(contract_path) if contract_path.is_file() else None
    if not isinstance(contract, dict):
        failures.append("GENERATION_CONTRACT_JSON_INVALID")
    elif contract.get("episode") != episode:
        failures.append("GENERATION_CONTRACT_EPISODE_MISMATCH")

    s1_path = Path(s1_gate_evidence_path).expanduser()
    if not s1_path.is_absolute():
        failures.append("S1_EVIDENCE_PATH_NOT_ABSOLUTE")
    elif not s1_path.is_file():
        failures.append("S1_EVIDENCE_FILE_MISSING")
    elif not _inside(s1_path, roots):
        failures.append("S1_EVIDENCE_NOT_PRIVATE")
    s1 = _json(s1_path) if s1_path.is_file() else None
    if not isinstance(s1, dict):
        failures.append("S1_EVIDENCE_JSON_INVALID")
    else:
        if s1.get("episode") != episode:
            failures.append("S1_EVIDENCE_EPISODE_MISMATCH")
        if _document_scope(s1) != series_scope_id:
            failures.append("S1_EVIDENCE_SCOPE_MISMATCH")
        if _stage_s1_status(s1) != "PASS":
            failures.append("S1_EVIDENCE_NOT_PASS")

    s2_path = Path(s2_gate_evidence_path).expanduser()
    if not s2_path.is_absolute():
        failures.append("S2_EVIDENCE_PATH_NOT_ABSOLUTE")
    elif not s2_path.is_file():
        failures.append("S2_EVIDENCE_FILE_MISSING")
    elif not _inside(s2_path, roots):
        failures.append("S2_EVIDENCE_NOT_PRIVATE")
    s2 = _json(s2_path) if s2_path.is_file() else None
    if not isinstance(s2, dict):
        failures.append("S2_EVIDENCE_JSON_INVALID")
    else:
        if s2.get("schema") != "nalu.s2_preproduction_receipt.v1":
            failures.append("S2_EVIDENCE_SCHEMA_INVALID")
        if s2.get("episode") != episode:
            failures.append("S2_EVIDENCE_EPISODE_MISMATCH")
        if _document_scope(s2) != series_scope_id:
            failures.append("S2_EVIDENCE_SCOPE_MISMATCH")
        if s2.get("stage") != "S2" or s2.get("status") != "PASS":
            failures.append("S2_EVIDENCE_NOT_PASS")
        if s2.get("keyframes_included") is not False:
            failures.append("S2_EVIDENCE_NOT_FREE_PREPRODUCTION")
        contract_binding = layer_bindings.get("generation_contract") or {}
        manifest_binding = layer_bindings.get("writer_manifest") or {}
        if s2.get("generation_contract_sha256") != contract_binding.get("sha256"):
            failures.append("S2_CONTRACT_SHA256_MISMATCH")
        if s2.get("writer_manifest_sha256") != manifest_binding.get("sha256"):
            failures.append("S2_MANIFEST_SHA256_MISMATCH")
        for field in (
            "global_space_map_sha256",
            "asset_requirements_sha256",
            "preproduction_report_sha256",
        ):
            if not _SHA256_RE.fullmatch(str(s2.get(field) or "")):
                failures.append(f"S2_EVIDENCE_SHA256_INVALID:{field}")

    seq_path = Path(seq29_report_path).expanduser()
    if not seq_path.is_absolute():
        failures.append("SEQ29_REPORT_PATH_NOT_ABSOLUTE")
    elif not seq_path.is_file():
        failures.append("SEQ29_REPORT_FILE_MISSING")
    elif not _inside(seq_path, roots):
        failures.append("SEQ29_REPORT_NOT_PRIVATE")
    seq29 = _json(seq_path) if seq_path.is_file() else None
    if not isinstance(seq29, dict):
        failures.append("SEQ29_REPORT_JSON_INVALID")
    else:
        if seq29.get("episode") != episode:
            failures.append("SEQ29_REPORT_EPISODE_MISMATCH")
        if seq29.get("enforced") is not True:
            failures.append("SEQ29_REPORT_NOT_ENFORCED")
        if seq29.get("status") != "PASS":
            failures.append("SEQ29_REPORT_NOT_PASS")

    if failures:
        return None, failures
    evidence: dict[str, Any] = {
        "schema": SCRIPT_EVIDENCE_SCHEMA,
        "episode": episode,
        "series_scope_id": series_scope_id,
        "layers": layer_bindings,
        "s1_gate_evidence": _binding(s1_path),
        "s2_preproduction_evidence": _binding(s2_path),
        "writer_selfcheck_seq29": _binding(seq_path),
    }
    evidence["script_evidence_sha256"] = _canonical_sha256(evidence)
    return evidence, []


def build_script_evidence(
    *,
    episode: str,
    series_scope_id: str,
    generation_contract_path: Path,
    layer_paths: Mapping[str, Path],
    s1_gate_evidence_path: Path,
    s2_gate_evidence_path: Path,
    seq29_report_path: Path,
    private_roots: Sequence[Path],
) -> dict[str, Any]:
    """Build the exact script-evidence block a proposed plan must contain."""
    evidence, failures = _script_evidence(
        episode=episode,
        series_scope_id=series_scope_id,
        generation_contract_path=generation_contract_path,
        layer_paths=layer_paths,
        s1_gate_evidence_path=s1_gate_evidence_path,
        s2_gate_evidence_path=s2_gate_evidence_path,
        seq29_report_path=seq29_report_path,
        private_roots=private_roots,
    )
    if failures or evidence is None:
        raise AssetPlanRefused(";".join(failures))
    return evidence


def _entity_id(row: Any, keys: Sequence[str]) -> str | None:
    if isinstance(row, str):
        return row.strip() or None
    if not isinstance(row, dict):
        return None
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def extract_requirements(contract: Mapping[str, Any]) -> dict[str, list[str]]:
    """Extract all plan-covered entities from a generation contract.

    The first character is the schema-defined protagonist fallback when the
    optional ``protagonist_ids`` list is absent.
    """
    characters = [
        _entity_id(row, ("character_id", "entity_id", "id"))
        for row in (contract.get("character_entities") or [])
    ]
    scenes = [
        _entity_id(row, ("scene_id", "id"))
        for row in (contract.get("scene_states") or [])
    ]
    props: list[str | None] = []
    for shot in contract.get("shots") or []:
        if not isinstance(shot, dict):
            props.append(None)
            continue
        spec = shot.get("prompt_spec")
        if not isinstance(spec, dict):
            continue
        raw_props = spec.get("props") or []
        if not isinstance(raw_props, list):
            props.append(None)
            continue
        props.extend(
            _entity_id(row, ("prop_id", "entity_id", "id", "prop"))
            for row in raw_props
        )
    if any(value is None for value in (*characters, *scenes, *props)):
        raise AssetPlanRefused("GENERATION_CONTRACT_ENTITY_ID_MISSING")
    character_ids = [str(value) for value in characters]
    scene_ids = [str(value) for value in scenes]
    prop_ids = [str(value) for value in props]
    if not character_ids:
        raise AssetPlanRefused("GENERATION_CONTRACT_CHARACTERS_EMPTY")
    if not scene_ids:
        raise AssetPlanRefused("GENERATION_CONTRACT_SCENES_EMPTY")
    if len(set(character_ids)) != len(character_ids):
        raise AssetPlanRefused("GENERATION_CONTRACT_CHARACTER_IDS_DUPLICATE")
    if len(set(scene_ids)) != len(scene_ids):
        raise AssetPlanRefused("GENERATION_CONTRACT_SCENE_IDS_DUPLICATE")
    protagonist_ids = contract.get("protagonist_ids")
    if protagonist_ids is None:
        leads = [character_ids[0]]
    elif not isinstance(protagonist_ids, list) or not protagonist_ids:
        raise AssetPlanRefused("GENERATION_CONTRACT_PROTAGONISTS_INVALID")
    else:
        leads = [str(value or "").strip() for value in protagonist_ids]
        if any(not value for value in leads):
            raise AssetPlanRefused("GENERATION_CONTRACT_PROTAGONIST_ID_MISSING")
    if not set(leads).issubset(set(character_ids)):
        raise AssetPlanRefused("GENERATION_CONTRACT_PROTAGONIST_UNKNOWN")
    return {
        "character": sorted(set(character_ids)),
        "scene": sorted(set(scene_ids)),
        "prop": sorted(set(prop_ids)),
        "protagonists": sorted(set(leads)),
    }


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _matched_rows(
    plan: Mapping[str, Any],
    *,
    roots: Sequence[Path],
    requirements: Mapping[str, list[str]],
    failures: list[str],
) -> dict[str, dict[str, dict[str, Any]]]:
    matches: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in ENTITY_TYPES}
    for kind, field in MATCH_LISTS.items():
        rows = plan.get(field)
        if not isinstance(rows, list):
            failures.append(f"MATCH_LIST_MISSING:{field}")
            continue
        for index, row in enumerate(rows):
            label = f"{field}:{index}"
            if not isinstance(row, dict):
                failures.append(f"MATCH_ROW_INVALID:{label}")
                continue
            if row.get("entity_type") != kind:
                failures.append(f"MATCH_ENTITY_TYPE_INVALID:{label}")
            entity_id = str(row.get("entity_id") or "").strip()
            if not entity_id:
                failures.append(f"MATCH_ENTITY_ID_MISSING:{label}")
                continue
            if entity_id not in set(requirements[kind]):
                failures.append(f"MATCH_ENTITY_UNKNOWN:{kind}:{entity_id}")
            if entity_id in matches[kind]:
                failures.append(f"MATCH_ENTITY_DUPLICATE:{kind}:{entity_id}")
                continue
            matches[kind][entity_id] = row
            if not str(row.get("rights_basis") or "").strip():
                failures.append(f"MATCH_RIGHTS_BASIS_MISSING:{kind}:{entity_id}")
            raw_path = str(row.get("source_path") or "").strip()
            path = Path(raw_path).expanduser() if raw_path else Path()
            if not raw_path or not path.is_absolute():
                failures.append(f"MATCH_SOURCE_PATH_NOT_ABSOLUTE:{kind}:{entity_id}")
                continue
            if not path.is_file():
                failures.append(f"MATCH_SOURCE_FILE_MISSING:{kind}:{entity_id}")
                continue
            if not _inside(path, roots):
                failures.append(f"MATCH_SOURCE_NOT_PRIVATE:{kind}:{entity_id}")
            expected_sha = str(row.get("source_sha256") or "")
            if not _SHA256_RE.fullmatch(expected_sha):
                failures.append(f"MATCH_SOURCE_SHA256_INVALID:{kind}:{entity_id}")
            elif sha256_file(path) != expected_sha:
                failures.append(f"MATCH_SOURCE_SHA256_MISMATCH:{kind}:{entity_id}")
    return matches


def _proposal_rows(
    plan: Mapping[str, Any],
    *,
    allowed_models: Collection[str],
    requirements: Mapping[str, list[str]],
    failures: list[str],
) -> tuple[dict[str, dict[str, dict[str, Any]]], Decimal]:
    proposals: dict[str, dict[str, dict[str, Any]]] = {kind: {} for kind in ENTITY_TYPES}
    rows = plan.get("ai_generation_proposals")
    if not isinstance(rows, list):
        failures.append("AI_GENERATION_PROPOSALS_MISSING")
        return proposals, Decimal(0)
    allowed = {str(value).strip() for value in allowed_models if str(value).strip()}
    if not allowed:
        failures.append("ALLOWED_GENERATION_MODELS_EMPTY")
    total = Decimal(0)
    for index, row in enumerate(rows):
        label = f"ai_generation_proposals:{index}"
        if not isinstance(row, dict):
            failures.append(f"AI_PROPOSAL_INVALID:{label}")
            continue
        kind = str(row.get("entity_type") or "").strip()
        entity_id = str(row.get("entity_id") or "").strip()
        if kind not in ENTITY_TYPES:
            failures.append(f"AI_PROPOSAL_ENTITY_TYPE_INVALID:{label}")
            continue
        if not entity_id:
            failures.append(f"AI_PROPOSAL_ENTITY_ID_MISSING:{label}")
            continue
        if entity_id not in set(requirements[kind]):
            failures.append(f"AI_PROPOSAL_ENTITY_UNKNOWN:{kind}:{entity_id}")
        if entity_id in proposals[kind]:
            failures.append(f"AI_PROPOSAL_ENTITY_DUPLICATE:{kind}:{entity_id}")
            continue
        proposals[kind][entity_id] = row
        model = str(row.get("model") or "").strip()
        if not model:
            failures.append(f"AI_PROPOSAL_MODEL_MISSING:{kind}:{entity_id}")
        elif model not in allowed:
            failures.append(f"AI_PROPOSAL_MODEL_NOT_ALLOWED:{kind}:{entity_id}")
        if not str(row.get("prompt") or "").strip():
            failures.append(f"AI_PROPOSAL_PROMPT_MISSING:{kind}:{entity_id}")
        if not str(row.get("rights_and_identity_note") or "").strip():
            failures.append(
                f"AI_PROPOSAL_RIGHTS_IDENTITY_NOTE_MISSING:{kind}:{entity_id}"
            )
        credits = _decimal(row.get("estimated_credits"))
        if credits is None:
            failures.append(f"AI_PROPOSAL_ESTIMATED_CREDITS_INVALID:{kind}:{entity_id}")
        else:
            total += credits
    return proposals, total


def validate_asset_plan(
    plan_path: Path,
    *,
    episode: str,
    series_scope_id: str,
    generation_contract_path: Path,
    layer_paths: Mapping[str, Path],
    s1_gate_evidence_path: Path,
    s2_gate_evidence_path: Path,
    seq29_report_path: Path,
    private_roots: Sequence[Path],
    allowed_models: Collection[str] = DEFAULT_ALLOWED_GENERATION_MODELS,
) -> dict[str, Any]:
    """Validate a complete, script-derived private asset proposal."""
    failures: list[str] = []
    roots, root_failures = _normalise_private_roots(private_roots)
    failures.extend(root_failures)
    path = Path(plan_path).expanduser()
    if not path.is_absolute():
        failures.append("ASSET_PLAN_PATH_NOT_ABSOLUTE")
    elif not path.is_file():
        failures.append("ASSET_PLAN_FILE_MISSING")
    elif not _inside(path, roots):
        failures.append("ASSET_PLAN_NOT_PRIVATE")
    plan = _json(path) if path.is_file() else None
    if not isinstance(plan, dict):
        failures.append("ASSET_PLAN_JSON_INVALID")
        plan = {}

    evidence, evidence_failures = _script_evidence(
        episode=episode,
        series_scope_id=series_scope_id,
        generation_contract_path=generation_contract_path,
        layer_paths=layer_paths,
        s1_gate_evidence_path=s1_gate_evidence_path,
        s2_gate_evidence_path=s2_gate_evidence_path,
        seq29_report_path=seq29_report_path,
        private_roots=private_roots,
    )
    failures.extend(evidence_failures)
    if plan.get("schema") != PLAN_SCHEMA:
        failures.append("ASSET_PLAN_SCHEMA_INVALID")
    if plan.get("status") != "PROPOSED":
        failures.append("ASSET_PLAN_STATUS_INVALID")
    if plan.get("episode") != episode:
        failures.append("ASSET_PLAN_EPISODE_MISMATCH")
    if plan.get("series_scope_id") != series_scope_id:
        failures.append("ASSET_PLAN_SCOPE_MISMATCH")
    if not str(plan.get("script_summary") or "").strip():
        failures.append("HUMAN_READABLE_SCRIPT_SUMMARY_MISSING")
    for field in ("assumptions", "risks"):
        value = plan.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            failures.append(f"PLAN_{field.upper()}_LIST_INVALID")
    rights_notes = plan.get("rights_and_identity_notes")
    if (
        not isinstance(rights_notes, list)
        or not rights_notes
        or any(not isinstance(item, str) or not item.strip() for item in rights_notes)
    ):
        failures.append("PLAN_RIGHTS_IDENTITY_NOTES_INVALID")
    if evidence is not None:
        if plan.get("script_evidence") != evidence:
            failures.append("SCRIPT_EVIDENCE_BINDING_MISMATCH")
        if plan.get("script_evidence_sha256") != evidence["script_evidence_sha256"]:
            failures.append("SCRIPT_EVIDENCE_SHA256_MISMATCH")

    contract = _json(Path(generation_contract_path))
    try:
        requirements = extract_requirements(contract if isinstance(contract, dict) else {})
    except AssetPlanRefused as exc:
        failures.extend(str(exc).split(";"))
        requirements = {kind: [] for kind in (*ENTITY_TYPES, "protagonists")}

    matches = _matched_rows(
        plan, roots=roots, requirements=requirements, failures=failures
    )
    proposals, proposal_total = _proposal_rows(
        plan,
        allowed_models=allowed_models,
        requirements=requirements,
        failures=failures,
    )
    for kind in ENTITY_TYPES:
        for entity_id in requirements[kind]:
            covered = int(entity_id in matches[kind]) + int(entity_id in proposals[kind])
            if covered == 0:
                failures.append(f"REQUIRED_ENTITY_UNCOVERED:{kind}:{entity_id}")
            elif covered > 1:
                failures.append(f"REQUIRED_ENTITY_AMBIGUOUS:{kind}:{entity_id}")

    for lead in requirements["protagonists"]:
        if lead in proposals["character"]:
            continue
        row = matches["character"].get(lead) or {}
        media_kind = str(row.get("media_kind") or "").strip().lower()
        source_kind = str(
            row.get("source_kind") or row.get("source_origin") or ""
        ).strip().lower()
        if media_kind not in _PHOTO_KINDS or source_kind not in _USER_UPLOAD_KINDS:
            failures.append(f"PROTAGONIST_REQUIRES_USER_PHOTO_OR_AI:{lead}")

    declared_total = _decimal(plan.get("total_estimated_credits"))
    if declared_total is None:
        failures.append("TOTAL_ESTIMATED_CREDITS_INVALID")
    elif declared_total != proposal_total:
        failures.append("TOTAL_ESTIMATED_CREDITS_MISMATCH")

    # Stable, unique failures make adapter logs and tests deterministic.
    failures = list(dict.fromkeys(failures))
    plan_sha = sha256_file(path) if path.is_file() else None
    return {
        "schema": REPORT_SCHEMA,
        "status": "PASS" if not failures else "BLOCKED",
        "episode": episode,
        "series_scope_id": series_scope_id,
        "asset_plan_path": str(path.resolve()) if path.is_absolute() else str(path),
        "asset_plan_sha256": plan_sha,
        "script_evidence_sha256": (
            evidence.get("script_evidence_sha256") if evidence else None
        ),
        "required_entities": requirements,
        "coverage": {
            kind: {
                "matched": sorted(matches[kind]),
                "ai_generation": sorted(proposals[kind]),
            }
            for kind in ENTITY_TYPES
        },
        "total_estimated_credits": str(proposal_total),
        "failures": failures,
    }


def require_valid_asset_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    report = validate_asset_plan(*args, **kwargs)
    if report["status"] != "PASS":
        raise AssetPlanRefused(";".join(report["failures"]))
    return report


def _valid_utc_timestamp(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)


def validate_confirmation_receipt(
    receipt_path: Path,
    *,
    receipt_root: Path,
    expected_receipt_sha256: str,
    expected_line_owner_id: str,
    plan_path: Path,
    episode: str,
    series_scope_id: str,
    generation_contract_path: Path,
    layer_paths: Mapping[str, Path],
    s1_gate_evidence_path: Path,
    s2_gate_evidence_path: Path,
    seq29_report_path: Path,
    private_roots: Sequence[Path],
    allowed_models: Collection[str] = DEFAULT_ALLOWED_GENERATION_MODELS,
) -> dict[str, Any]:
    """Validate a private line-owner confirmation of the current exact plan."""
    plan_report = validate_asset_plan(
        plan_path,
        episode=episode,
        series_scope_id=series_scope_id,
        generation_contract_path=generation_contract_path,
        layer_paths=layer_paths,
        s1_gate_evidence_path=s1_gate_evidence_path,
        s2_gate_evidence_path=s2_gate_evidence_path,
        seq29_report_path=seq29_report_path,
        private_roots=private_roots,
        allowed_models=allowed_models,
    )
    failures = [f"ASSET_PLAN_NOT_VALID:{value}" for value in plan_report["failures"]]

    root = Path(receipt_root).expanduser()
    if not root.is_absolute():
        failures.append("RECEIPT_ROOT_NOT_ABSOLUTE")
    elif not root.is_dir():
        failures.append("RECEIPT_ROOT_MISSING")
    else:
        roots, _root_failures = _normalise_private_roots(private_roots)
        if not _inside(root, roots):
            failures.append("RECEIPT_ROOT_NOT_PRIVATE")
    path = Path(receipt_path).expanduser()
    if not path.is_absolute():
        failures.append("RECEIPT_PATH_NOT_ABSOLUTE")
    elif not path.is_file():
        failures.append("RECEIPT_FILE_MISSING")
    elif root.is_dir() and not _inside(path, [root]):
        failures.append("RECEIPT_OUTSIDE_CONFIGURED_ROOT")

    actual_receipt_sha = sha256_file(path) if path.is_file() else None
    if not _SHA256_RE.fullmatch(str(expected_receipt_sha256 or "")):
        failures.append("EXPECTED_RECEIPT_SHA256_INVALID")
    elif actual_receipt_sha != expected_receipt_sha256:
        failures.append("RECEIPT_SHA256_MISMATCH")

    receipt = _json(path) if path.is_file() else None
    if not isinstance(receipt, dict):
        failures.append("RECEIPT_JSON_INVALID")
        receipt = {}
    expected = {
        "schema": CONFIRMATION_RECEIPT_SCHEMA,
        "status": "CONFIRMED",
        "episode": episode,
        "series_scope_id": series_scope_id,
        "line_owner_id": expected_line_owner_id,
        "asset_plan_sha256": plan_report.get("asset_plan_sha256"),
        "script_evidence_sha256": plan_report.get("script_evidence_sha256"),
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            failures.append(f"RECEIPT_FIELD_MISMATCH:{field}")
    if not str(expected_line_owner_id or "").strip():
        failures.append("EXPECTED_LINE_OWNER_ID_MISSING")
    if not str(receipt.get("verbatim") or "").strip():
        failures.append("RECEIPT_VERBATIM_MISSING")
    if not str(receipt.get("message_or_event_id") or "").strip():
        failures.append("RECEIPT_MESSAGE_OR_EVENT_ID_MISSING")
    if not _valid_utc_timestamp(receipt.get("confirmed_at_utc")):
        failures.append("RECEIPT_CONFIRMED_AT_UTC_INVALID")

    failures = list(dict.fromkeys(failures))
    return {
        "schema": "storyclaw.asset_plan_confirmation_gate.v1",
        "status": "PASS" if not failures else "BLOCKED",
        "episode": episode,
        "series_scope_id": series_scope_id,
        "asset_plan_sha256": plan_report.get("asset_plan_sha256"),
        "script_evidence_sha256": plan_report.get("script_evidence_sha256"),
        "receipt_path": str(path.resolve()) if path.is_absolute() else str(path),
        "receipt_sha256": actual_receipt_sha,
        "failures": failures,
        "plan_gate": plan_report,
    }


def require_valid_confirmation(*args: Any, **kwargs: Any) -> dict[str, Any]:
    report = validate_confirmation_receipt(*args, **kwargs)
    if report["status"] != "PASS":
        raise AssetPlanRefused(";".join(report["failures"]))
    return report
