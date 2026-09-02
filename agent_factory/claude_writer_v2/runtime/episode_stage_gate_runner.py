#!/usr/bin/env python3
"""Run registered episode gates from one fail-closed stage entry point.

The evidence bundle maps stable evidence names to repository-relative files.
Commands are owned here rather than supplied by callers, so a task cannot
silently replace a gate with a different command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from gate_result_contract import write_gate_result
except ModuleNotFoundError:
    from tools.gate_result_contract import write_gate_result


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"


EXECUTORS: dict[str, dict[str, Any]] = {
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF": {
        "tool": "tools/fight_cut_plan_gate.py",
        "arguments": [("--plan", "fight_cut_plan")],
        "optional_arguments": [("--canonical-script", "canonical_script")],
        "passing_statuses": ("PASS", "ADVISE"),
    },
    "SOURCE-READ-COMPLETENESS": {
        "tool": "tools/source_canon_binding_gate.py",
        "arguments": [
            ("--source-manifest", "source_ingest_manifest"),
            ("--canon-facts", "canon_facts"),
            ("--beat-map", "chapter_beat_map"),
        ],
        "extra": ["--mode", "source"],
        "skip_canonical_script_binding": True,
    },
    "SCRIPT-SOURCE-CANON-BINDING": {
        "tool": "tools/source_canon_binding_gate.py",
        "arguments": [
            ("--source-manifest", "source_ingest_manifest"),
            ("--canon-facts", "canon_facts"),
            ("--beat-map", "chapter_beat_map"),
            ("--full-series-manifest", "full_series_manifest"),
        ],
        "value_arguments": [
            ("--canonical-script-sha256", "canonical_script_sha256"),
        ],
        "extra": ["--mode", "script"],
        "episode_flag": "--episode",
    },
    "FULL-SERIES-SOURCE-FIDELITY": {
        "tool": "tools/source_canon_binding_gate.py",
        "arguments": [
            ("--source-manifest", "source_ingest_manifest"),
            ("--canon-facts", "canon_facts"),
            ("--beat-map", "chapter_beat_map"),
            ("--full-series-manifest", "full_series_manifest"),
            ("--fidelity-report", "full_series_source_fidelity"),
        ],
        "extra": ["--mode", "fidelity"],
    },
    "FINAL-AUDIT-COMPLETENESS": {
        "tool": "tools/run_regression_ci.py",
        "arguments": [("--video", "final_video")],
        "optional_arguments": [
            ("--coverage-manifest-json", "coverage_manifest_json"),
            ("--audio-boundary-json", "audio_boundary_json"),
            ("--action-audit-json", "action_audit_json"),
            ("--sentence-audit-json", "sentence_audit_json"),
            ("--asr-json", "asr_json"),
            ("--scene-brightness-json", "scene_brightness_json"),
            ("--ocr-audit-json", "ocr_audit_json"),
        ],
        "list_arguments": [("--source-brightness-audit-json", "source_brightness_audit_jsons")],
        "boolean_flags": [
            ("--require-forward-source-gates", "require_forward_source_gates"),
            ("--require-source-brightness-audits", "require_source_brightness_audits"),
        ],
        "episode_flag": "--episode-id",
    },
    "GATE-REGISTRY-INTEGRITY": {
        "tool": "tools/regression_ci_component_gate.py",
        "arguments": [("--report", "ci_report")],
        "extra": ["--gate-id", "GATE-REGISTRY-INTEGRITY"],
    },
    "INITIAL-PRODUCTION-ASSET-LIBRARY": {
        "tool": "tools/initial_asset_library.py",
        "subcommand": "gate",
        "arguments": [
            ("--requirements", "asset_requirements"),
            ("--library", "production_asset_library"),
        ],
        "episode_flag": "--episode",
    },
    "FINAL-AUDIO-BED-CONTINUITY": {
        "tool": "tools/regression_ci_component_gate.py",
        "arguments": [("--report", "ci_report")],
        "extra": ["--gate-id", "FINAL-AUDIO-BED-CONTINUITY"],
    },
    "FINAL-STATIC-HOLD": {
        "tool": "tools/regression_ci_component_gate.py",
        "arguments": [("--report", "ci_report")],
        "extra": ["--gate-id", "FINAL-STATIC-HOLD"],
    },
    "FROZEN-THRESHOLD-PROFILE": {
        "tool": "tools/regression_ci_component_gate.py",
        "arguments": [("--report", "ci_report")],
        "extra": ["--gate-id", "FROZEN-THRESHOLD-PROFILE"],
    },
    "SCRIPT-READINESS-EXCITEMENT-SHA": {
        "tool": "tools/script_readiness_gate.py",
        "arguments": [("--beat-sheet", "beat_sheet")],
        "optional_arguments": [("--blind-tests-report", "blind_tests_report")],
        "script_bound_arguments": ["beat_sheet"],
    },
    "SCRIPT-US-DRAMA-EVENT-DENSITY": {
        "tool": "tools/us_drama_event_density_gate.py",
        "arguments": [("--script", "script")],
        "optional_arguments": [
            ("--narrative-canonical", "narrative_canonical"),
            ("--writer-receipt", "writer_receipt"),
        ],
        "script_bound_arguments": ["script"],
    },
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY": {
        "tool": "tools/dramatic_quality_gate.py",
        "arguments": [("--report", "dramatic_quality_report")],
        "script_bound_arguments": ["dramatic_quality_report"],
    },
    "MECHANICAL-DEFAULT-META-GATE": {
        "tool": "tools/mechanical_default_gate.py",
        "arguments": [("--plan", "unit_plan")],
        "script_bound_arguments": ["unit_plan"],
    },
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL": {
        "tool": "tools/common_sense_causality_gate.py",
        "arguments": [("--plan", "causality_plan")],
        "script_bound_arguments": ["causality_plan"],
    },
    "PERIOD-ANACHRONISM-LOCK": {
        "tool": "tools/anachronism_lock_gate.py",
        "arguments": [("--plan", "period_lock_plan")],
        "script_bound_arguments": ["period_lock_plan"],
    },
    "SCRIPT-SCENE-DIVERSITY-PREFLIGHT": {
        "tool": "tools/script_scene_diversity_gate.py",
        "arguments": [("--scene-history", "scene_history")],
        "script_bound_arguments": ["scene_history"],
    },
    "EDIT-PLAN-NATIVE-CADENCE": {
        "tool": "tools/edit_plan_integrity_gate.py",
        "arguments": [("--render-plan", "render_plan"), ("--renderer", "renderer")],
        "value_arguments": [("--target-fps", "target_fps")],
        "optional_arguments": [("--ffmpeg", "ffmpeg")],
    },
    "FINAL-FRAME-CADENCE-FREEZE": {
        "tool": "tools/frame_cadence_audit.py",
        "arguments": [("--video", "final_video")],
        "optional_arguments": [("--render-plan", "render_plan"), ("--ffmpeg", "ffmpeg")],
    },
    "FINAL-OCR-POLICY": {
        "tool": "tools/final_video_ocr_audit.py",
        "arguments": [("--video", "final_video")],
    },
    "SOURCE-BRIGHTNESS-JUMP": {
        "tool": "tools/source_brightness_jump_audit.py",
        "arguments": [("--video", "source_video"), ("--ffmpeg", "ffmpeg")],
    },
    "FINAL-PACKAGE-BLOCKERS": {
        "tool": "tools/final_package_blocker_gate.py",
        "arguments": [("--manifest", "final_package_manifest")],
    },
    "RELEASE-BRANDING-CONTRACT": {
        "tool": "tools/release_branding_contract_gate.py",
        "arguments": [("--project", "agentcut_project")],
        "optional_arguments": [
            ("--render-manifest", "render_manifest"),
            ("--final-video", "final_video"),
        ],
    },
    "AUDIO-SOURCE-PUBLISHED-MIX-BINDING": {
        "tool": "tools/audio_source_binding_gate.py",
        "arguments": [("--plan", "audio_source_plan"), ("--published-mix", "published_mix"), ("--ffmpeg", "ffmpeg")],
    },
    "AUDIENCE-SCORE-PRE-RELEASE": {
        "tool": "tools/audience_score_gate.py",
        "arguments": [("--report", "audience_report")],
        "extra": ["--base", str(ROOT)],
    },
    "DEFECT-TIER-TOLERANCE": {
        "tool": "tools/defect_tolerance_gate.py",
        "arguments": [("--report", "defect_report")],
    },
    "GIGGLE-REROLL-COST-GUARD": {
        "tool": "tools/reroll_cost_guard.py",
        "arguments": [("--policy", "reroll_policy"), ("--ledger", "reroll_ledger")],
        "value_arguments": [
            ("--shot-id", "shot_id"),
            ("--reroll-number", "reroll_number"),
            ("--failure-tier", "failure_tier"),
            ("--failure-reason", "failure_reason"),
            ("--total-paid-tasks", "total_paid_tasks"),
        ],
    },
    "GIGGLE-CREDIT-LEDGER-CLOSURE": {
        "tool": "tools/giggle_credit_closure_gate.py",
        "arguments": [("--ledger", "credit_ledger")],
        "extra": ["--require-actual-credits"],
    },
    "FINAL-AUDIO-PROVENANCE": {
        "tool": "tools/final_audio_provenance_gate.py",
        "arguments": [
            ("--manifest", "audio_provenance_manifest"),
            ("--published-mix", "published_mix"),
            ("--candidate", "final_video"),
            ("--ffmpeg", "ffmpeg"),
        ],
    },
    "MARKET-CALIBRATION-ANTI-OVERFIT": {
        "tool": "tools/market_calibration_gate.py",
        "arguments": [("--policy", "market_policy"), ("--ledger", "market_ledger")],
        "optional_arguments": [("--proposal", "market_proposal")],
    },
    "FRAME-EXACT-RENDER-MATERIALIZATION": {
        "tool": "tools/frame_exact_materialization_gate.py",
        "arguments": [
            ("--plan", "render_plan"),
            ("--render-report", "render_report"),
            ("--video", "picture_only_video"),
        ],
    },
    "AGENT-MISTAKE-ANTI-RECURRENCE": {
        "tool": "tools/validate_agent_mistake_ledger.py",
        "arguments": [("--ledger", "agent_mistake_ledger")],
    },
    "THREE-EPISODE-CONCURRENCY": {
        "tool": "tools/validate_three_episode_concurrency.py",
        "arguments": [("--policy", "concurrency_policy"), ("--ledger", "active_episode_ledger")],
    },
    "SPEAKER-VOICE-GENDER-BINDING": {
        "tool": "tools/multimodal_character_binding_guard.py",
        "arguments": [("--config", "video_batch_config")],
    },
    "VIDEO-PERFORMANCE-NATURAL-SPLIT": {
        "tool": "tools/performance_unit_split_gate.py",
        "arguments": [("--contract", "split_performance_contract")],
        "optional_arguments": [
            ("--config", "split_performance_config"),
            ("--admission", "split_performance_admission"),
        ],
    },
    "VIDEO-UNIT-GROUPED-CONTINUITY-PREFLIGHT": {
        "tool": "tools/grouped_continuity_gate.py",
        "arguments": [
            ("--grouping-plan", "video_unit_grouping_plan"),
            ("--anchor-plan", "video_unit_anchor_plan"),
            ("--editorial-seedance-manifest", "editorial_seedance_manifest"),
        ],
    },
    "VIDEO-UNIT-BOUNDARY-CONTINUITY": {
        "tool": "tools/video_unit_boundary_continuity_gate.py",
        "arguments": [
            ("--grouped-manifest", "grouped_seedance_manifest"),
            ("--media-map", "accepted_media_map"),
            ("--decision-dir", "boundary_continuity_decision_dir"),
        ],
    },
    "BGM-SOURCE-PRIORITY-AUTHENTICITY": {
        "tool": "tools/bgm_authenticity_gate.py",
        "arguments": [("--project", "edit_project"), ("--stem", "bgm_stem"), ("--final", "final_video")],
        "optional_arguments": [("--generation-log", "bgm_generation_log")],
    },
    "PACING-STYLE-BAN-V2_3": {
        "tool": "tools/pacing_style_gate.py",
        "arguments": [("--ci-report", "ci_report"), ("--edit-plan", "render_plan")],
    },
    "TRANSITION-SMOOTHNESS": {
        "tool": "tools/transition_smoothness_gate.py",
        "arguments": [("--plan", "transition_plan"), ("--contract", "transition_contract")],
    },
    "INSERT-SOURCE-NONADJACENCY": {
        "tool": "tools/transition_smoothness_gate.py",
        "arguments": [("--plan", "transition_plan"), ("--contract", "transition_contract")],
    },
    "SYMBOLIC-SHOT-LEGIBILITY": {
        "tool": "tools/symbolic_shot_legibility_gate.py",
        "arguments": [("--input", "symbolic_shot_evidence")],
    },
    "CHARACTER-IDENTITY-ADMISSION": {
        "tool": "tools/character_identity_admission_gate.py",
        "arguments": [("--manifest", "character_manifest"), ("--registry", "character_registry")],
    },
    "EDIT-CUT-MOTIVATION": {
        "tool": "tools/cut_motivation_gate.py",
        "arguments": [("--project", "edit_project")],
        "optional_arguments": [("--metrics", "final_cut_metrics")],
    },
    "EDIT-VIEWING-CONSISTENCY": {
        "tool": "tools/cut_motivation_gate.py",
        "arguments": [("--project", "edit_project")],
        "optional_arguments": [("--metrics", "final_cut_metrics")],
    },
    "SOURCE-BRIGHTNESS-JUMP": {
        "tool": "tools/source_brightness_jump_audit.py",
        "arguments": [("--video", "source_video"), ("--ffmpeg", "ffmpeg")],
    },
    "RELEASE-SIGNOFF-INTEGRITY": {
        "tool": "tools/release_signoff_integrity_gate.py",
        "arguments": [("--ci-report", "ci_report"), ("--watch-report", "watch_report")],
        "episode_argument": True,
    },
}

FINAL_CUT_GATE_IDS = {
    "FINAL-CUT-VIEWING-EVIDENCE",
    "FINAL-CUT-PICTURE-REPETITION",
    "FINAL-CUT-GATE-NAMING-HONESTY",
    "FINAL-CUT-WEAKEST-LINK-SCORING",
    "FINAL-CUT-NO-SELF-WAIVER",
    "FINAL-CUT-EVENT-LEDGER",
    "FINAL-CUT-DIALOGUE-LEGIBILITY",
}
for gate_id in FINAL_CUT_GATE_IDS:
    EXECUTORS[gate_id] = {
        "tool": "tools/final_cut_quality_gates.py",
        "arguments": [
            ("--report", "audience_report"),
            ("--metrics", "final_cut_metrics"),
        ],
        "optional_arguments": [
            ("--adjudication", "adjudication"),
            ("--event-ledger", "event_ledger"),
            ("--script", "dialogue_script"),
        ],
        "extra": ["--base", str(ROOT)],
    }

RUNTIME_GATE_IDS = frozenset({
    "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
    "AGENT-MISTAKE-ANTI-RECURRENCE",
    "AUDIENCE-SCORE-PRE-RELEASE",
    "AUDIO-SOURCE-PUBLISHED-MIX-BINDING",
    "BGM-SOURCE-PRIORITY-AUTHENTICITY",
    "CHARACTER-IDENTITY-ADMISSION",
    "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
    "DEFECT-TIER-TOLERANCE",
    "EDIT-CUT-MOTIVATION",
    "EDIT-PLAN-NATIVE-CADENCE",
    "EDIT-VIEWING-CONSISTENCY",
    "FINAL-AUDIO-PROVENANCE",
    "FINAL-AUDIO-BED-CONTINUITY",
    "FINAL-AUDIT-COMPLETENESS",
    "FINAL-CUT-DIALOGUE-LEGIBILITY",
    "FINAL-CUT-EVENT-LEDGER",
    "FINAL-CUT-GATE-NAMING-HONESTY",
    "FINAL-CUT-NO-SELF-WAIVER",
    "FINAL-CUT-PICTURE-REPETITION",
    "FINAL-CUT-VIEWING-EVIDENCE",
    "FINAL-CUT-WEAKEST-LINK-SCORING",
    "FINAL-FRAME-CADENCE-FREEZE",
    "FINAL-OCR-POLICY",
    "FINAL-PACKAGE-BLOCKERS",
    "FINAL-STATIC-HOLD",
    "FULL-SERIES-SOURCE-FIDELITY",
    "FROZEN-THRESHOLD-PROFILE",
    "GATE-REGISTRY-INTEGRITY",
    "FRAME-EXACT-RENDER-MATERIALIZATION",
    "GIGGLE-CREDIT-LEDGER-CLOSURE",
    "GIGGLE-REROLL-COST-GUARD",
    "INSERT-SOURCE-NONADJACENCY",
    "INITIAL-PRODUCTION-ASSET-LIBRARY",
    "MARKET-CALIBRATION-ANTI-OVERFIT",
    "MECHANICAL-DEFAULT-META-GATE",
    "PACING-STYLE-BAN-V2_3",
    "PERIOD-ANACHRONISM-LOCK",
    # Added 2026-08-03 to EXECUTORS and to GATE_REGISTRY_v3, but not here, so
    # the assert below has been firing at import time ever since: the entire
    # stage gate runner was unimportable, all 50 gates with it. Restored
    # CL2X-1039. The assert did its job; nothing was running it.
    "RELEASE-BRANDING-CONTRACT",
    "RELEASE-SIGNOFF-INTEGRITY",
    "SCRIPT-COUNCIL-DRAMATIC-QUALITY",
    "SCRIPT-READINESS-EXCITEMENT-SHA",
    "SCRIPT-SCENE-DIVERSITY-PREFLIGHT",
    "SCRIPT-SOURCE-CANON-BINDING",
    "SCRIPT-US-DRAMA-EVENT-DENSITY",
    "SOURCE-BRIGHTNESS-JUMP",
    "SOURCE-READ-COMPLETENESS",
    "SPEAKER-VOICE-GENDER-BINDING",
    "SYMBOLIC-SHOT-LEGIBILITY",
    "THREE-EPISODE-CONCURRENCY",
    "TRANSITION-SMOOTHNESS",
    "VIDEO-PERFORMANCE-NATURAL-SPLIT",
    "VIDEO-UNIT-GROUPED-CONTINUITY-PREFLIGHT",
    "VIDEO-UNIT-BOUNDARY-CONTINUITY",
})
assert RUNTIME_GATE_IDS == frozenset(EXECUTORS), "runtime gate list must match executable dispatch map"


PHASE_GATES: dict[str, tuple[str, ...]] = {
    "script": (
        "SCRIPT-SOURCE-CANON-BINDING",
        "FULL-SERIES-SOURCE-FIDELITY",
        "SCRIPT-READINESS-EXCITEMENT-SHA",
        "SCRIPT-US-DRAMA-EVENT-DENSITY",
        "SCRIPT-COUNCIL-DRAMATIC-QUALITY",
        "SCRIPT-SCENE-DIVERSITY-PREFLIGHT",
        "MECHANICAL-DEFAULT-META-GATE",
        "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
        "PERIOD-ANACHRONISM-LOCK",
    ),
    "edit": (
        "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
        "EDIT-PLAN-NATIVE-CADENCE",
        "EDIT-CUT-MOTIVATION",
        "EDIT-VIEWING-CONSISTENCY",
        "FRAME-EXACT-RENDER-MATERIALIZATION",
        "AUDIO-SOURCE-PUBLISHED-MIX-BINDING",
        "TRANSITION-SMOOTHNESS",
        "INSERT-SOURCE-NONADJACENCY",
        "VIDEO-UNIT-BOUNDARY-CONTINUITY",
    ),
    "source": (
        "SOURCE-READ-COMPLETENESS",
        "SOURCE-BRIGHTNESS-JUMP",
        "CHARACTER-IDENTITY-ADMISSION",
        "SYMBOLIC-SHOT-LEGIBILITY",
        "DEFECT-TIER-TOLERANCE",
        "VIDEO-UNIT-GROUPED-CONTINUITY-PREFLIGHT",
    ),
    "final": (
        "FINAL-AUDIT-COMPLETENESS",
        "GATE-REGISTRY-INTEGRITY",
        "FINAL-AUDIO-BED-CONTINUITY",
        "FINAL-STATIC-HOLD",
        "FROZEN-THRESHOLD-PROFILE",
        "FINAL-FRAME-CADENCE-FREEZE",
        "FINAL-OCR-POLICY",
        "PACING-STYLE-BAN-V2_3",
        "FINAL-AUDIO-PROVENANCE",
        "BGM-SOURCE-PRIORITY-AUTHENTICITY",
        "FINAL-PACKAGE-BLOCKERS",
        "AUDIENCE-SCORE-PRE-RELEASE",
        "FINAL-CUT-VIEWING-EVIDENCE",
        "FINAL-CUT-PICTURE-REPETITION",
        "FINAL-CUT-GATE-NAMING-HONESTY",
        "FINAL-CUT-WEAKEST-LINK-SCORING",
        "FINAL-CUT-NO-SELF-WAIVER",
        "FINAL-CUT-EVENT-LEDGER",
        "FINAL-CUT-DIALOGUE-LEGIBILITY",
    ),
    "release": (
        "RELEASE-SIGNOFF-INTEGRITY",
        "GIGGLE-CREDIT-LEDGER-CLOSURE",
    ),
}


def _resolve(bundle_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _script_sha_from_payload(payload: dict[str, Any]) -> str:
    for key in ("script_sha256", "source_script_sha256", "beat_sheet_sha256"):
        value = str(payload.get(key) or "").lower()
        if len(value) == 64:
            return value
    return ""


def validate_canonical_script_binding(evidence: dict[str, Any]) -> list[str]:
    expected = str(evidence.get("canonical_script_sha256") or "").lower()
    script_ref = evidence.get("canonical_script")
    failures: list[str] = []
    if len(expected) != 64:
        failures.append("canonical_script_sha256_missing_or_invalid")
    if not script_ref:
        failures.append("canonical_script_missing")
        return failures
    script_path = _resolve(ROOT, str(script_ref))
    if not script_path.is_file():
        failures.append(f"canonical_script_not_found:{script_path}")
    elif expected and hashlib.sha256(script_path.read_bytes()).hexdigest() != expected:
        failures.append("canonical_script_sha256_mismatch")
    return failures


def _result_status(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    payload = _load(path)
    return str(
        payload.get("status")
        or payload.get("gate_status")
        or payload.get("verdict")
        or "UNKNOWN"
    ).upper()


def execute_gate(
    gate_id: str,
    episode: str,
    evidence: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = EXECUTORS.get(gate_id)
    if not spec:
        return {
            "gate_id": gate_id,
            "invoked": False,
            "status": "FAIL",
            "failures": ["registered_gate_has_no_stage_executor"],
        }

    canonical_failures = (
        []
        if spec.get("skip_canonical_script_binding")
        else validate_canonical_script_binding(evidence)
    )
    if canonical_failures:
        return {
            "gate_id": gate_id,
            "invoked": False,
            "status": "FAIL",
            "failures": canonical_failures,
        }

    missing: list[str] = []
    cmd = [sys.executable, str(ROOT / spec["tool"])]
    if spec.get("subcommand"):
        cmd.append(str(spec["subcommand"]))
    for flag, key in spec.get("arguments", []):
        value = evidence.get(key)
        if not value:
            missing.append(key)
            continue
        path = _resolve(ROOT, str(value))
        if not path.exists():
            missing.append(f"{key}:missing:{path}")
            continue
        cmd.extend([flag, str(path)])
    if missing:
        return {
            "gate_id": gate_id,
            "invoked": False,
            "status": "FAIL",
            "failures": [f"required_evidence_missing:{item}" for item in missing],
        }

    expected_script_sha = str(evidence["canonical_script_sha256"]).lower()
    binding_failures: list[str] = []
    for key in spec.get("script_bound_arguments", []):
        value = evidence.get(key)
        if not value:
            continue
        path = _resolve(ROOT, str(value))
        try:
            bound_sha = _script_sha_from_payload(_load(path))
        except (OSError, json.JSONDecodeError, TypeError):
            bound_sha = ""
        if not bound_sha:
            binding_failures.append(f"script_binding_sha_missing:{key}:{path}")
        elif bound_sha != expected_script_sha:
            binding_failures.append(
                f"script_binding_sha_mismatch:{key}:expected={expected_script_sha}:actual={bound_sha}"
            )
    if binding_failures:
        return {
            "gate_id": gate_id,
            "invoked": False,
            "status": "FAIL",
            "failures": binding_failures,
        }

    for flag, key in spec.get("optional_arguments", []):
        value = evidence.get(key)
        if value:
            cmd.extend([flag, str(_resolve(ROOT, str(value)))])
    for flag, key in spec.get("list_arguments", []):
        for value in evidence.get(key) or []:
            cmd.extend([flag, str(_resolve(ROOT, str(value)))])
    for flag, key in spec.get("boolean_flags", []):
        if evidence.get(key) is True:
            cmd.append(flag)
    missing_values: list[str] = []
    for flag, key in spec.get("value_arguments", []):
        value = evidence.get(key)
        if value is None or value == "":
            missing_values.append(key)
            continue
        cmd.extend([flag, str(value)])
    if missing_values:
        return {
            "gate_id": gate_id,
            "invoked": False,
            "status": "FAIL",
            "failures": [f"required_value_missing:{item}" for item in missing_values],
        }
    episode_flag = spec.get("episode_flag") or ("--episode" if spec.get("episode_argument") else None)
    if episode_flag:
        cmd.extend([episode_flag, episode])
    cmd.extend(spec.get("extra", []))

    out_path = out_dir / f"{gate_id}.json"
    cmd.extend(["--out", str(out_path)])
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    result_status = _result_status(out_path)
    passing_statuses = tuple(spec.get("passing_statuses") or ("PASS", "APPROVED"))
    passed = proc.returncode == 0 and any(
        result_status == value or result_status.startswith(f"{value}_")
        for value in passing_statuses
    )
    return {
        "gate_id": gate_id,
        "invoked": True,
        "status": "PASS" if passed else "FAIL",
        "implementation": spec["tool"],
        "output": str(out_path),
        "implementation_status": result_status,
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-1200:],
        "stderr_tail": proc.stderr[-1200:],
        "failures": [] if passed else ["gate_execution_failed"],
    }


def run_registered_gates(
    *,
    episode: str,
    gates: list[str],
    phases: list[str],
    evidence_bundle: Path,
    out_dir: Path,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Run registered gates for CLI callers and release builders alike."""
    registry = _load(registry_path.resolve())
    registered = {row.get("gate_id") for row in registry.get("gates", [])}
    requested = list(gates)
    for phase in phases:
        requested.extend(PHASE_GATES[phase])
    requested = list(dict.fromkeys(requested))
    if not requested:
        raise ValueError("at least one gate or phase is required")
    unknown = sorted(set(requested) - registered)
    evidence = _load(evidence_bundle.resolve())
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for gate_id in requested:
        if gate_id not in registered:
            continue
        result = execute_gate(gate_id, episode, evidence, out_dir)
        results.append(result)
        if result.get("invoked") is True:
            write_gate_result(
                episode,
                gate_id,
                invoked=True,
                status=result["status"],
                runner="tools/episode_stage_gate_runner.py",
                evidence=result.get("output") or out_dir,
            )
        if gate_id == "FINAL-AUDIT-COMPLETENESS" and result.get("output"):
            evidence["ci_report"] = result["output"]
    failures = [f"gate_not_registered:{gate_id}" for gate_id in unknown]
    failures.extend(
        f"gate_failed:{row['gate_id']}" for row in results if row["status"] != "PASS"
    )
    summary = {
        "schema": "qingshan.episode_stage_gate_execution.v1",
        "episode": episode,
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "requested_gate_count": len(requested),
        "requested_phases": phases,
        "invoked_gate_count": sum(1 for row in results if row.get("invoked")),
        "all_requested_gates_invoked": bool(results) and all(row.get("invoked") for row in results),
        "results": results,
        "failures": failures,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    summary_path = out_dir / "episode_stage_gate_execution_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary["summary_path"] = str(summary_path)
    return summary


def require_release_builder_gate_admission(
    *,
    episode: str,
    evidence_bundle: Path,
    out_dir: Path,
    registry_path: Path = DEFAULT_REGISTRY,
) -> dict[str, Any]:
    """Fail closed before a per-episode release builder may render media."""
    if not evidence_bundle.is_file():
        raise RuntimeError(f"RELEASE_EDIT_GATE_EVIDENCE_BUNDLE_MISSING:{evidence_bundle}")
    summary = run_registered_gates(
        episode=episode,
        gates=[],
        phases=["edit"],
        evidence_bundle=evidence_bundle,
        out_dir=out_dir,
        registry_path=registry_path,
    )
    if summary["status"] != "PASS" or not summary["all_requested_gates_invoked"]:
        raise RuntimeError(
            f"RELEASE_RENDER_BLOCKED_BY_UNIFIED_EDIT_GATES:{summary['summary_path']}"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--gate", action="append", default=[])
    parser.add_argument("--phase", action="append", choices=sorted(PHASE_GATES), default=[])
    parser.add_argument("--evidence-bundle", required=True, type=Path)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        summary = run_registered_gates(
            episode=args.episode,
            gates=args.gate,
            phases=args.phase,
            evidence_bundle=args.evidence_bundle,
            out_dir=args.out_dir,
            registry_path=args.registry,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "status": summary["status"],
        "out": summary["summary_path"],
        "failures": summary["failures"],
    }, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
