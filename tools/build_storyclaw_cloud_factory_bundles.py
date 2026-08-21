#!/usr/bin/env python3
"""Build auditable StoryClaw bundles for the five-agent AI drama factory."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "workflow/cloud_factory_migration_v1_20260724"
DEFAULT_DIST = DEFAULT_SOURCE / "dist"
REGISTRY = ROOT / "configs/GATE_REGISTRY_v3_20260716.json"
FIX_REGISTRY = (
    ROOT
    / "workflow/cloud_factory_migration_v1_20260724/contracts/VERIFIED_FIX_REGISTRY_V1.json"
)

SHARED_FILES = {
    "configs/GATE_REGISTRY_v3_20260716.json",
    "configs/project_init_schema_v1.json",
    "codex_docs/青山AI_Factory_客户版产品架构_v2_20260724.md",
    "workflow/intake/new_project_intake.html",
    "workflow/intake/new_project_intake_schema_v2.json",
    "workflow/cloud_factory_migration_v1_20260724/FACTORY_PRODUCT_MANIFEST.json",
    "workflow/cloud_factory_migration_v1_20260724/SHARED_DIRECTORY_PROTOCOL_V2.md",
    "workflow/cloud_factory_migration_v1_20260724/TALENT_HUB_PORTABILITY_CONTRACT.md",
    "workflow/cloud_factory_migration_v1_20260724/contracts/SOURCE_CANON_READ_BINDING_V1.md",
    "workflow/cloud_factory_migration_v1_20260724/contracts/PRODUCTION_PROVEN_QUALITY_BASELINE_V1.md",
    "workflow/cloud_factory_migration_v1_20260724/contracts/LOCAL_PROCESS_CAPABILITY_PARITY_V1.md",
    "workflow/cloud_factory_migration_v1_20260724/contracts/PIPELINE_LOCAL_CAPABILITY_PARITY_V2.md",
    "workflow/cloud_factory_migration_v1_20260724/contracts/VERIFIED_FIX_REGISTRY_V1.json",
    "workflow/cloud_factory_migration_v1_20260724/configs/FACTORY_AGENT_ROUTES_V1.json",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.8_PRODUCTION_PROVEN_WRITER_AUDIT_BASELINE.md",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.9_LOCAL_CAPABILITY_PARITY_CORE.md",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.10_PORTABLE_RUNTIME_AND_LIVE_PARITY.md",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.11_WRITER_EXEC_RECOVERY_AND_FIX_PROPAGATION.md",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.12_RESTRICTED_SESSION_DISPATCH_ROUTING.md",
    "workflow/cloud_factory_migration_v1_20260724/migrations/2.0.13_WRITER_STAGED_FACTS_RESUME.md",
    "tools/portable_runtime.py",
    "tools/tests/test_portable_runtime.py",
    "tools/durable_exec_probe.py",
    "tools/tests/test_durable_exec_probe.py",
    "tools/agent_task_journal.py",
    "tools/tests/test_agent_task_journal.py",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/README.md",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/build_status.py",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/index.html",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/status.js",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/status.example.json",
    "workflow/cloud_factory_migration_v1_20260724/customer_workbench/status_schema_v1.json",
}

ROLE_SEEDS = {
    "qingshan-producer-supervisor": {
        "charter": "charters/青山AI_Factory_制片监制_云端可移植宪章.md",
        "requirements": "runtime_requirements/青山AI_Factory_制片监制_requirements.md",
        "stage_tokens": (),
        "files": {
            "tools/supervisor_script_gate.py",
            "tools/release_gate_check.py",
            "tools/release_gate_apply_approval.py",
            "tools/platform_release_preflight.py",
            "tools/source_canon_binding_gate.py",
            "tools/script_readiness_gate.py",
            "tools/us_drama_event_density_gate.py",
            "tools/canonical_writer_provenance.py",
            "tools/canonical_writer_dispatcher.py",
            "tools/dramatic_quality_gate.py",
            "tools/shot_duration_policy.py",
            "tools/common_sense_causality_gate.py",
            "tools/factory_dispatcher.py",
            "tools/factory_cron_contract.py",
            "tools/tests/test_factory_dispatcher.py",
            "tools/tests/test_factory_cron_contract.py",
            "tools/tests/test_script_readiness_gate.py",
            "tools/tests/test_us_drama_event_density_gate.py",
            "tools/tests/test_canonical_writer_dispatcher.py",
            "tools/tests/test_dramatic_quality_gate.py",
            "tools/tests/test_shot_duration_policy.py",
            "tools/tests/test_common_sense_causality_gate.py",
        },
    },
    "qingshan-claude-writer": {
        "charter": "charters/青山AI_剧本创作_云端可移植宪章.md",
        "requirements": "runtime_requirements/青山AI_剧本创作_requirements.md",
        "stage_tokens": (),
        "files": {
            "configs/schemas/narrative_canonical_v3.schema.json",
            "codex_docs/美剧叙事节奏标准_v3_因果层_20260821.md",
            "tools/script_readiness_gate.py",
            "tools/script_density_gate_preflight.py",
            "tools/script_scene_diversity_gate.py",
            "tools/action_visualization_readability_gate.py",
            "tools/video_prompt_action_density_gate.py",
            "tools/canonical_script_activation_gate.py",
            "tools/source_canon_binding_gate.py",
            "tools/script_readiness_gate.py",
            "tools/us_drama_event_density_gate.py",
            "tools/canonical_writer_provenance.py",
            "tools/canonical_writer_dispatcher.py",
            "tools/dramatic_quality_gate.py",
            "tools/shot_duration_policy.py",
            "tools/common_sense_causality_gate.py",
            "tools/writer_checkpoint_guard.py",
            "tools/factory_cron_contract.py",
            "tools/tests/test_script_readiness_gate.py",
            "tools/tests/test_us_drama_event_density_gate.py",
            "tools/tests/test_canonical_writer_dispatcher.py",
            "tools/tests/test_dramatic_quality_gate.py",
            "tools/tests/test_shot_duration_policy.py",
            "tools/tests/test_common_sense_causality_gate.py",
            "tools/tests/test_writer_checkpoint_guard.py",
            "tools/tests/test_factory_cron_contract.py",
        },
    },
    "qingshan-ai-drama-pipeline": {
        "charter": "charters/青山AI_Drama_Pipeline_云端可移植宪章.md",
        "requirements": "runtime_requirements/青山AI_Drama_Pipeline_requirements.md",
        "stage_tokens": (
            "GENERATION_SUBMIT",
            "PRE_SUBMISSION",
            "RELEASE_FINANCE_CLOSURE",
            "GENERATION_PRE_SUBMISSION",
            "VIDEO_GENERATION_SUBMIT",
            "SCRIPT_PLAN_AND_GENERATION_SUBMIT",
            "IMAGE_PLAN_AND_VIDEO_GENERATION_SUBMIT",
            "WORLD_PLAN_AND_GENERATION_SUBMIT",
            "VIDEO_GENERATION_SUBMIT_AND_SOURCE_ADMISSION",
            "STORAGE_RETENTION",
        ),
        "files": {
            "configs/schemas/production_asset_requirements.schema.json",
            "configs/schemas/production_asset_library.schema.json",
            "configs/schemas/pipeline_environment_baseline.schema.json",
            "configs/templates/production_asset_requirements.template.json",
            "tools/initial_asset_library.py",
            "tools/tests/test_initial_asset_library.py",
            "tools/pipeline_environment_baseline.py",
            "tools/tests/test_pipeline_environment_baseline.py",
            "tools/giggle_asset_factory.py",
            "tools/asset_binding_validator.py",
            "tools/submit_giggle_task_manifest.py",
            "tools/submit_giggle_image_manifest.py",
            "tools/poll_giggle_submit_report.py",
            "tools/build_giggle_credit_ledger.py",
            "tools/generate_live_giggle_credit_ledger.py",
            "tools/build_remote_generation_credit_ledger.py",
            "tools/reconcile_legacy_video_credit_ledgers.py",
            "tools/audit_account_video_credit_window.py",
            "tools/giggle_credit_closure_gate.py",
            "tools/source_canon_binding_gate.py",
            "tools/episode_parallel_batch_supervisor.py",
            "tools/episode_video_generation_guard.py",
            "tools/tests/test_episode_video_generation_guard.py",
            "tools/shot_space_camera_constraint_gate.py",
            "tools/tests/test_shot_space_camera_constraint_gate.py",
            "tools/scene_authority_lock.py",
            "tools/tests/test_scene_authority_lock.py",
            "tools/global_space_layout_gate.py",
            "tools/tests/test_global_space_layout_gate.py",
            "tools/action_shot_design_gate.py",
            "tools/tests/test_action_shot_design_gate.py",
            "tools/shot_media_admission_gate.py",
            "tools/tests/test_shot_media_admission_gate.py",
            "tools/tests/test_submit_keyframe_admission_gate.py",
            "tools/video_prompt_action_density_gate.py",
            "tools/tests/test_video_prompt_action_density_gate.py",
            "tools/frame_cadence_audit.py",
            "tools/tests/test_frame_cadence_audit.py",
            "tools/final_video_ocr_audit.py",
            "tools/tests/test_final_video_ocr_audit.py",
            "tools/qa_multimodal_dialogue_batch.py",
            "tools/tests/test_qa_multimodal_dialogue_batch.py",
            "tools/source_video_dialogue_gate.py",
            "tools/tests/test_source_video_dialogue_gate.py",
            "configs/schemas/episode_post_publish_retention.schema.json",
            "configs/schemas/s3_episode_archive_receipt.schema.json",
            "tools/s3_episode_archive.py",
            "tools/tests/test_s3_episode_archive.py",
            "tools/episode_post_publish_cleanup.py",
            "tools/tests/test_episode_post_publish_cleanup.py",
            "workflow/cloud_factory_migration_v1_20260724/templates/PIPELINE_INITIAL_ASSET_UPLOAD_GUIDE.md",
        },
    },
    "qingshan-agent-cut-cloud": {
        "charter": "charters/青山Agent_cut_cloud_云端可移植宪章.md",
        "requirements": "runtime_requirements/青山Agent_cut_cloud_requirements.md",
        "stage_tokens": (
            "EDIT_ADMISSION",
            "PACKAGE",
            "FINAL_MIX",
            "EDIT_ASSEMBLY",
            "SOURCE_QA_AND_ASSEMBLY",
            "EDIT_PLAN_PRE_RENDER",
            "SCRIPT_AND_FINAL_CUT",
        ),
        "files": {
            "tools/run_agentcut.sh",
            "tools/bootstrap_cloud_agentcut_runtime.sh",
            "tools/agentcut_project_to_shot_timeline.py",
            "tools/add_agentcut_subtitle_track.py",
            "tools/agentcut_ci_watch.py",
            "tools/agentcut_character_voice_reference_guard.py",
            "tools/render_agentcut_audio_master.py",
            "tools/align_agentcut_captions_to_native_source_asr.py",
            "tools/rebuild_agentcut_dialogue_windows_from_asr.py",
            "tools/qa_bgm_candidates.py",
            "tools/bgm_authenticity_gate.py",
            "tools/final_audio_provenance_gate.py",
            "tools/dialogue_audio_release_gate.py",
            "tools/youtube_shorts_runtime_gate.py",
            "tools/source_canon_binding_gate.py",
            "workflow/cloud_factory_migration_v1_20260724/runtime_wheels_portable/agentcut-0.9.16-py3-none-any.whl",
        },
    },
    "qingshan-ai-aduit": {
        "charter": "charters/青山AI_aduit_云端可移植宪章.md",
        "requirements": "runtime_requirements/青山AI_aduit_requirements.md",
        "stage_tokens": (
            "SOURCE",
            "SCRIPT",
            "FULL_SERIES_SCRIPT_GATE",
            "SCRIPT_APPROVAL_BEFORE_GENERATION",
            "SCRIPT_PLAN_AND_GENERATION_SUBMIT",
            "WORLD_PLAN_AND_GENERATION_SUBMIT",
            "GENERATION_PRE_SUBMISSION",
            "GENERATION_SUBMIT",
            "IMAGE_PLAN_AND_VIDEO_GENERATION_SUBMIT",
            "VIDEO_GENERATION_SUBMIT",
            "CI_START",
            "FINAL_CI",
            "SOURCE_QA",
            "SOURCE_QA_AND_ASSEMBLY",
            "SCRIPT_SOURCE_QA_AND_FINAL_SIGNOFF",
            "SOURCE_QA_AND_FINAL_WATCH",
            "SOURCE_QA_EDIT_ADMISSION_AND_PRE_RELEASE",
            "VIDEO_GENERATION_SUBMIT_AND_SOURCE_ADMISSION",
            "EDIT_ADMISSION",
            "EDIT_PLAN_PRE_RENDER",
            "EDIT_ASSEMBLY",
            "FINAL_MIX",
            "FINAL_SIGNOFF",
            "SCRIPT_AND_FINAL_CUT",
            "PRE_RELEASE_AUDIENCE",
            "PRE_RELEASE_ADJUDICATION",
            "POST_TECHNICAL_PRE_SUPERVISOR_RELEASE",
            "PACKAGE",
            "RELEASE",
        ),
        "files": {
            "tools/run_episode_qa.sh",
            "tools/run_regression_ci.py",
            "tools/parallel_source_qa.py",
            "tools/final_cut_quality_gates.py",
            "tools/gate_registry_v3_check.py",
            "tools/regression_ci_component_gate.py",
            "tools/final_video_ocr_audit.py",
            "tools/frame_cadence_audit.py",
            "tools/audit_final_native_source_audio_binding.py",
            "tools/audit_final_dialogue_windows.py",
            "tools/speaker_identity_voice_release_gate.py",
            "tools/source_canon_binding_gate.py",
            "tools/scene_authority_lock.py",
            "tools/shot_duration_policy.py",
            "tools/common_sense_causality_gate.py",
            "tools/cut_motivation_gate.py",
            "tools/audience_score_gate.py",
            "tools/defect_tolerance_gate.py",
            "tools/final_package_blocker_gate.py",
            "tools/source_brightness_jump_audit.py",
            "tools/tests/test_scene_authority_lock.py",
            "tools/tests/test_shot_duration_policy.py",
            "tools/tests/test_common_sense_causality_gate.py",
            "tools/tests/test_cut_motivation_gate_portable.py",
            "tools/tests/test_audience_score_gate.py",
            "tools/tests/test_defect_tolerance_gate.py",
            "tools/tests/test_final_cut_quality_gates_portable.py",
            "tools/tests/test_final_package_blocker_gate.py",
            "tools/tests/test_frame_cadence_audit.py",
            "tools/tests/test_source_brightness_jump_audit.py",
        },
    },
}

LOCAL_PATH_RE = re.compile(
    r"(?P<path>(?:tools|configs|workflow|codex_docs)/[A-Za-z0-9_./\-\u4e00-\u9fff]+\.(?:py|sh|json|md|txt|html))"
)

FORBIDDEN_BUNDLE_SUBSTRINGS = (
    ".secrets",
    "QINGSHAN_PIPELINE_EFFECTIVE_RULESET",
    "series_character_asset_registry",
    "series_continuity_asset_registry",
    "series_voice_reference_registry",
    "codex_docs/CLAUDE_TO_CODEX.md",
    "workflow/CODEX_TO_CLAUDE.md",
    "workflow/work_queue.json",
    "workflow/agent_mistake_ledger.json",
    "workflow/storyclaw_outbox/",
    "workflow/claude_writer_agent/production/",
    "workflow/claude_writer_agent/scripts/",
    "workflow/release/",
    "workflow/script_review/剧本审核_经验记忆_MEMORY.md",
    "workflow/credit_reports/",
    "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json",
)

FORBIDDEN_BUNDLE_PATH_RE = re.compile(
    r"^(?:configs|workflow|qa|exports)/e\d+(?:[_/.-]|$)",
    re.IGNORECASE,
)

FORBIDDEN_TEXT_MARKERS = (
    "/Users/rogerwu/qingshan_short_drama",
    "codex_docs/CLAUDE_TO_CODEX.md",
    "workflow/CODEX_TO_CLAUDE.md",
    "workflow/claude_writer_agent/production/",
)

PACKAGE_SCRIPTS = (
    "install.py",
    "bootstrap_dependencies.py",
    "run_in_runtime.py",
    "configure_runtime.py",
    "doctor.py",
    "self_test.py",
    "parity_check.py",
    "test_parity_check.py",
    "test_install_upgrade.py",
    "migrate.py",
    "rollback.py",
)

ROLE_REGRESSION_TESTS = {
    "qingshan-claude-writer": (
        "tools/tests/test_durable_exec_probe.py",
        "tools/tests/test_writer_checkpoint_guard.py",
    ),
    "qingshan-producer-supervisor": (
        "tools/tests/test_durable_exec_probe.py",
    ),
    "qingshan-ai-drama-pipeline": (
        "tools/tests/test_durable_exec_probe.py",
        "tools/tests/test_initial_asset_library.py",
        "tools/tests/test_pipeline_environment_baseline.py",
        "tools/tests/test_episode_parallel_batch_supervisor.py",
        "tools/tests/test_episode_video_generation_guard.py",
        "tools/tests/test_shot_space_camera_constraint_gate.py",
        "tools/tests/test_scene_authority_lock.py",
        "tools/tests/test_global_space_layout_gate.py",
        "tools/tests/test_action_shot_design_gate.py",
        "tools/tests/test_shot_media_admission_gate.py",
        "tools/tests/test_submit_keyframe_admission_gate.py",
        "tools/tests/test_video_prompt_action_density_gate.py",
        "tools/tests/test_frame_cadence_audit.py",
        "tools/tests/test_final_video_ocr_audit.py",
        "tools/tests/test_qa_multimodal_dialogue_batch.py",
        "tools/tests/test_source_video_dialogue_gate.py",
        "tools/tests/test_episode_post_publish_cleanup.py",
        "tools/tests/test_s3_episode_archive.py",
    ),
    "qingshan-agent-cut-cloud": (
        "tools/tests/test_durable_exec_probe.py",
    ),
    "qingshan-ai-aduit": (
        "tools/tests/test_durable_exec_probe.py",
    ),
}


def verified_fixes_for_role(role: str) -> list[dict[str, object]]:
    data = json.loads(FIX_REGISTRY.read_text(encoding="utf-8"))
    fixes: list[dict[str, object]] = []
    for fix in data.get("fixes", []):
        if fix.get("status") != "VERIFIED":
            continue
        owners = {str(item) for item in fix.get("owner_roles", [])}
        if role not in owners:
            continue
        required = ("id", "required_files", "regression_tests", "migration_path")
        missing = [field for field in required if not fix.get(field)]
        if missing:
            raise RuntimeError(
                f"Verified fix {fix.get('id', '<missing-id>')} lacks closure: "
                + ", ".join(missing)
            )
        fixes.append(fix)
    return fixes


def verified_fix_files(role: str) -> set[str]:
    selected: set[str] = set()
    for fix in verified_fixes_for_role(role):
        selected.update(str(item) for item in fix["required_files"])
        selected.update(str(item) for item in fix["regression_tests"])
        selected.add(str(fix["migration_path"]))
    return selected


def verified_fix_tests(role: str) -> set[str]:
    selected: set[str] = set()
    for fix in verified_fixes_for_role(role):
        selected.update(str(item) for item in fix["regression_tests"])
    return selected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def registry_files(stage_tokens: tuple[str, ...]) -> set[str]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    selected: set[str] = set()
    allowed_stages = set(stage_tokens)
    for gate in data.get("gates", []):
        stage = str(gate.get("stage", "")).upper()
        if stage in allowed_stages:
            for field in ("code_paths", "test_paths", "stage_runner_paths"):
                selected.update(str(item) for item in gate.get(field, []) if item)
            checklist = gate.get("manual_checklist_path")
            if checklist:
                selected.add(str(checklist))
    return selected


def write_scoped_registry(
    destination: Path,
    role: str,
    stage_tokens: tuple[str, ...],
) -> dict[str, object] | None:
    """Replace the full factory registry with a self-contained role view."""
    if not stage_tokens:
        return None
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    allowed_stages = set(stage_tokens)
    scoped = dict(data)
    scoped["gates"] = [
        gate
        for gate in data.get("gates", [])
        if str(gate.get("stage", "")).upper() in allowed_stages
    ]
    scoped["withdrawn_gates"] = [
        gate
        for gate in data.get("withdrawn_gates", [])
        if any(
            str(path) in registry_files(stage_tokens)
            for path in gate.get("code_paths", [])
        )
    ]
    scoped["package_scope"] = {
        "role": role,
        "source_registry_sha256": sha256(REGISTRY),
        "allowed_stages": sorted(allowed_stages),
        "gate_count": len(scoped["gates"]),
        "project_agnostic": True,
    }
    target = destination / "configs/GATE_REGISTRY_v3_20260716.json"
    target.write_text(
        json.dumps(scoped, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "source_path": "generated/role_scoped_gate_registry.json",
        "target_path": "configs/GATE_REGISTRY_v3_20260716.json",
        "bytes": target.stat().st_size,
        "sha256": sha256(target),
    }


def local_import_candidates(path: Path) -> set[str]:
    if path.suffix != ".py":
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    candidates: set[str] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            parts = module.split(".")
            if parts[0] == "tools" and len(parts) > 1:
                candidate = ROOT / "tools" / (parts[1] + ".py")
            else:
                candidate = ROOT / "tools" / (parts[0] + ".py")
            if candidate.is_file():
                candidates.add(candidate.relative_to(ROOT).as_posix())
    return candidates


def referenced_paths(path: Path) -> set[str]:
    if path.suffix not in {".py", ".sh"}:
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return set()
    found = {match.group("path") for match in LOCAL_PATH_RE.finditer(text)}
    return {item for item in found if (ROOT / item).is_file()}


def dependency_closure(paths: set[str]) -> set[str]:
    pending = list(paths)
    resolved: set[str] = set()
    while pending:
        rel = pending.pop()
        if rel in resolved:
            continue
        source = ROOT / rel
        if not source.is_file():
            raise FileNotFoundError(f"Required bundle source is missing: {rel}")
        resolved.add(rel)
        dependencies = local_import_candidates(source) | referenced_paths(source)
        pending.extend(sorted(dependencies - resolved))
    return resolved


def test_support_files(paths: set[str]) -> set[str]:
    """Include portable fixture data whenever bundled registered tests need it."""
    tests = [
        ROOT / path
        for path in paths
        if path.startswith("tools/tests/") and (ROOT / path).is_file()
    ]
    if not tests:
        return set()
    fixture_root = ROOT / "tools/tests/fixtures"
    test_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore") for path in tests
    )
    selected: set[str] = set()
    for path in fixture_root.rglob("*"):
        if path.is_file() and path.name in test_text:
            selected.add(path.relative_to(ROOT).as_posix())
    return selected


def is_forbidden_bundle_path(path: str) -> bool:
    return any(token in path for token in FORBIDDEN_BUNDLE_SUBSTRINGS) or bool(
        FORBIDDEN_BUNDLE_PATH_RE.search(path)
    )


def scan_forbidden_content(paths: set[str]) -> list[str]:
    failures: list[str] = []
    for rel in sorted(paths):
        if rel.endswith("package_runtime/self_test.py"):
            continue
        path = ROOT / rel
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".txt", ".json", ".py", ".sh", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in FORBIDDEN_TEXT_MARKERS:
            if marker in text:
                failures.append(f"{rel}:{marker}")
    return failures


def copy_with_manifest(paths: set[str], destination: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for rel in sorted(paths):
        source = ROOT / rel
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append(
            {
                "source_path": rel,
                "target_path": rel,
                "bytes": source.stat().st_size,
                "sha256": sha256(source),
            }
        )
    return entries


def write_package_scaffold(
    destination: Path,
    role: str,
    source_root: Path,
    package_version: str | None = None,
) -> list[dict[str, object]]:
    roster = json.loads((source_root / "AGENT_ROSTER.json").read_text(encoding="utf-8"))
    product = json.loads(
        (source_root / "FACTORY_PRODUCT_MANIFEST.json").read_text(encoding="utf-8")
    )
    agent = next(item for item in roster["agents"] if item["slug"] == role)
    package_dir = destination / "package"
    package_dir.mkdir(parents=True, exist_ok=True)
    hire = {
        "schema": "storyclaw.talent_hub.hire.v1",
        "slug": role,
        "display_name": agent["display_name"],
        "agent_id": agent["agent_id"],
        "role": agent["role"],
        "package_version": package_version or product["product"]["version"],
        "protocol_version": product["product"]["protocol_version"],
        "protocol_range": agent["protocol_range"],
        "customer_entry": role == product["product"]["customer_entry_slug"],
        "model": agent["model"],
        "runtime_policy": roster["runtime_policy"],
        "official_claim_allowed": False,
        "signature": {"status": "UNSIGNED_DEV"},
    }
    contract = {
        "schema": "qingshan.factory.install_contract.v1",
        "slug": role,
        "mode": "two_phase_shadow_stage_then_quiescent_atomic_switch",
        "required_protocol": agent["protocol_range"],
        "preserve_project_data": True,
        "preserve_runtime_receipts": True,
        "preserve_original_failures": True,
        "rollback_required": True,
        "running_job_version_pinning_required": True,
        "active_job_restart_forbidden": True,
        "upgrade_stage_must_not_change_current": True,
        "activation_requires_quiescence_receipt": True,
        "active_uncheckpointed_jobs_must_equal": 0,
        "checkpoint_receipts_must_be_verified": True,
        "new_jobs_use_current_only_after_atomic_switch": True,
        "external_connections_default": "needs_live_probe",
        "post_install_runtime_configurator": "package/configure_runtime.py",
        "runtime_policy_apply_after_all_five_registered": True,
        "gateway_reload_required_after_runtime_policy": True,
        "gateway_reload_deferred_until_quiescence": True,
    }
    if role == "qingshan-ai-drama-pipeline":
        contract.update(
            {
                "installation_scope": "capability_overlay",
                "capability_versions_directory": "capability_versions",
                "capability_current_link": "capabilities-current",
                "pre_upgrade_live_state_probe_required": True,
                "environment_baseline_receipt_required_for_activation": True,
                "preserve_existing_agent_crons": True,
                "preserve_role_contracts": True,
                "preserve_executor_bridge_and_poller": True,
                "preserve_shared_mailbox_protocol": True,
                "preserve_active_version_root": True,
                "in_place_protocol_mutation_forbidden": True,
                "runtime_policy_apply_after_all_five_registered": False,
                "gateway_reload_required_after_runtime_policy": False,
                "gateway_reload_deferred_until_quiescence": False,
            }
        )
    generated: list[dict[str, object]] = []
    for name, data in (
        ("talent_hub_hire.json", hire),
        ("install_contract.json", contract),
    ):
        path = package_dir / name
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated.append(
            {
                "source_path": f"generated/package/{name}",
                "target_path": f"package/{name}",
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    runtime_root = source_root / "package_runtime"
    for name in PACKAGE_SCRIPTS:
        source = runtime_root / name
        target = package_dir / name
        shutil.copy2(source, target)
        target.chmod(0o755)
        generated.append(
            {
                "source_path": source.relative_to(ROOT).as_posix(),
                "target_path": f"package/{name}",
                "bytes": target.stat().st_size,
                "sha256": sha256(target),
            }
        )
    return generated


def write_package_sha_manifest(destination: Path) -> Path:
    manifest_path = destination / "package/SHA256_MANIFEST.json"
    files: list[dict[str, object]] = []
    for path in sorted(destination.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        rel = path.relative_to(destination).as_posix()
        files.append(
            {
                "path": rel,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema": "qingshan.factory.package_sha256_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def remove_transient_python_cache(root: Path) -> None:
    for cache in sorted(root.rglob("__pycache__"), reverse=True):
        if cache.is_dir():
            shutil.rmtree(cache)
    for compiled in root.rglob("*.py[co]"):
        compiled.unlink()


def build_bundle(
    role: str,
    spec: dict[str, object],
    source_root: Path,
    dist: Path,
    package_version: str | None = None,
) -> dict[str, object]:
    product = json.loads(
        (source_root / "FACTORY_PRODUCT_MANIFEST.json").read_text(encoding="utf-8")
    )["product"]
    stage_tokens = tuple(spec["stage_tokens"])
    fixes = verified_fixes_for_role(role)
    paths = (
        set(spec["files"])
        | SHARED_FILES
        | registry_files(stage_tokens)
        | verified_fix_files(role)
    )
    paths.add(f"workflow/cloud_factory_migration_v1_20260724/{spec['charter']}")
    paths.add(f"workflow/cloud_factory_migration_v1_20260724/{spec['requirements']}")
    paths.add("workflow/cloud_factory_migration_v1_20260724/AGENT_ROSTER.json")
    paths.add("workflow/cloud_factory_migration_v1_20260724/README.md")
    bootstrap = source_root / "bootstrap_messages" / f"{role}.md"
    if bootstrap.is_file():
        paths.add(bootstrap.relative_to(ROOT).as_posix())
    prompt_root = source_root / "prompt_files" / role
    paths.update(
        path.relative_to(ROOT).as_posix()
        for path in prompt_root.glob("*.md")
        if path.is_file()
    )
    paths.update(test_support_files(paths))
    paths = dependency_closure(paths)
    paths = {
        path
        for path in paths
        if not is_forbidden_bundle_path(path)
    }
    content_failures = scan_forbidden_content(paths)
    if content_failures:
        raise RuntimeError(
            f"{role} contains customer-package forbidden references:\n"
            + "\n".join(content_failures)
        )

    bundle_dir = dist / role
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)
    entries = copy_with_manifest(paths, bundle_dir)
    scoped_registry = write_scoped_registry(bundle_dir, role, stage_tokens)
    if scoped_registry:
        entries = [
            entry
            for entry in entries
            if entry["target_path"] != "configs/GATE_REGISTRY_v3_20260716.json"
        ]
        entries.append(scoped_registry)
    effective_version = package_version or product["version"]
    entries.extend(
        write_package_scaffold(
            bundle_dir,
            role,
            source_root,
            package_version=effective_version,
        )
    )
    manifest = {
        "schema": "storyclaw.cloud_agent_bundle_manifest.v2",
        "role": role,
        "factory_product_version": effective_version,
        "protocol_version": product["protocol_version"],
        "official_claim_allowed": False,
        "content_policy": {
            "project_agnostic": True,
            "customer_history_included": False,
            "runtime_history_included": False,
            "secret_values_included": False,
            "privacy_scan": "PASS",
        },
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_root": "BUILD_WORKSPACE_REDACTED",
        "verified_fix_ids": [str(fix["id"]) for fix in fixes],
        "file_count": len(entries),
        "files": entries,
    }
    manifest_path = bundle_dir / "BUNDLE_SHA256_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    package_manifest_path = write_package_sha_manifest(bundle_dir)
    self_test = subprocess.run(
        [sys.executable, str(bundle_dir / "package/self_test.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if self_test.returncode != 0:
        raise RuntimeError(f"{role} package self-test failed:\n{self_test.stdout}\n{self_test.stderr}")
    package_unit_test = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "test_parity_check.py",
            "test_install_upgrade.py",
        ],
        cwd=bundle_dir / "package",
        capture_output=True,
        text=True,
        check=False,
    )
    if package_unit_test.returncode != 0:
        raise RuntimeError(
            f"{role} package unit test failed:\n"
            f"{package_unit_test.stdout}\n{package_unit_test.stderr}"
        )
    scoped_test_paths = {
        path
        for path in registry_files(stage_tokens) | set(spec["files"])
        if path.startswith("tools/tests/test_") and path.endswith(".py")
    }
    regression_tests = (
        set(ROLE_REGRESSION_TESTS.get(role, ()))
        | verified_fix_tests(role)
        | scoped_test_paths
    )
    for regression_test in sorted(regression_tests):
        regression_module = regression_test[:-3].replace("/", ".")
        regression = subprocess.run(
            [sys.executable, "-m", "unittest", regression_module],
            cwd=bundle_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if regression.returncode != 0:
            raise RuntimeError(
                f"{role} capability regression failed ({regression_test}):\n"
                f"{regression.stdout}\n{regression.stderr}"
            )
    parity_check = subprocess.run(
        [sys.executable, str(bundle_dir / "package/parity_check.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        parity_check.returncode != 0
        or '"status": "PACKAGED_UNPROVEN"' not in parity_check.stdout
    ):
        raise RuntimeError(
            f"{role} static parity check failed:\n"
            f"{parity_check.stdout}\n{parity_check.stderr}"
        )

    remove_transient_python_cache(bundle_dir)
    final_self_test = subprocess.run(
        [sys.executable, str(bundle_dir / "package/self_test.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    if final_self_test.returncode != 0:
        raise RuntimeError(
            f"{role} final package self-test failed:\n"
            f"{final_self_test.stdout}\n{final_self_test.stderr}"
        )

    archive = dist / f"{role}.tar.gz"
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(bundle_dir, arcname=role)
    archive_sha = sha256(archive)
    archive_sidecar = archive.with_name(f"{archive.name}.sha256")
    archive_sidecar.write_text(f"{archive_sha}  {archive.name}\n", encoding="ascii")
    return {
        "role": role,
        "bundle_dir": role,
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": archive_sha,
        "archive_sha256_sidecar": archive_sidecar.name,
        "file_count": len(entries),
        "manifest_sha256": sha256(manifest_path),
        "package_manifest_sha256": sha256(package_manifest_path),
        "package_self_test": "PASS",
        "package_unit_test": "PASS",
        "capability_regression_tests": "PASS",
        "verified_fix_ids": [str(fix["id"]) for fix in fixes],
        "static_parity_status": "PACKAGED_UNPROVEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--role", choices=sorted(ROLE_SEEDS))
    parser.add_argument("--package-version")
    args = parser.parse_args()
    if not args.source.is_dir():
        raise FileNotFoundError(args.source)
    args.dist.mkdir(parents=True, exist_ok=True)
    if args.role:
        (args.dist / f"{args.role}.tar.gz").unlink(missing_ok=True)
        (args.dist / f"{args.role}.tar.gz.sha256").unlink(missing_ok=True)
    else:
        for stale in args.dist.glob("qingshan-*.tar.gz"):
            stale.unlink()
    product = json.loads(
        (args.source / "FACTORY_PRODUCT_MANIFEST.json").read_text(encoding="utf-8")
    )["product"]
    selected_roles = (
        {args.role: ROLE_SEEDS[args.role]} if args.role else ROLE_SEEDS
    )
    receipts = [
        build_bundle(
            role,
            spec,
            args.source,
            args.dist,
            package_version=args.package_version,
        )
        for role, spec in selected_roles.items()
    ]
    if args.role:
        receipt = {
            "schema": "storyclaw.cloud_factory_bundle_build_receipt.v2",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "factory_product_version": args.package_version or product["version"],
            "protocol_version": product["protocol_version"],
            "migration_status": "PIPELINE_CAPABILITY_OVERLAY_BUILT_PENDING_LIVE_BASELINE",
            "official_claim_allowed": False,
            "bundles": receipts,
        }
        receipt_path = args.dist / "BUILD_RECEIPT.json"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    aggregate_name = (
        f"qingshan-ai-factory-{product['version']}-all-five.tar.gz"
    )
    aggregate_path = args.dist / aggregate_name
    with tarfile.open(aggregate_path, "w:gz") as tar:
        for item in receipts:
            archive = args.dist / str(item["archive"])
            tar.add(archive, arcname=f"bundles/{archive.name}")
        tar.add(
            args.source / "FACTORY_PRODUCT_MANIFEST.json",
            arcname="FACTORY_PRODUCT_MANIFEST.json",
        )
        tar.add(
            args.source / "AGENT_ROSTER.json",
            arcname="AGENT_ROSTER.json",
        )
        tar.add(
            args.source
            / "migrations/2.0.11_WRITER_EXEC_RECOVERY_AND_FIX_PROPAGATION.md",
            arcname="migrations/2.0.11_WRITER_EXEC_RECOVERY_AND_FIX_PROPAGATION.md",
        )
        tar.add(
            args.source
            / "migrations/2.0.12_RESTRICTED_SESSION_DISPATCH_ROUTING.md",
            arcname="migrations/2.0.12_RESTRICTED_SESSION_DISPATCH_ROUTING.md",
        )
        tar.add(
            args.source
            / "migrations/2.0.13_WRITER_STAGED_FACTS_RESUME.md",
            arcname="migrations/2.0.13_WRITER_STAGED_FACTS_RESUME.md",
        )
    receipt = {
        "schema": "storyclaw.cloud_factory_bundle_build_receipt.v2",
        "built_at": datetime.now(timezone.utc).isoformat(),
        "factory_product_version": product["version"],
        "protocol_version": product["protocol_version"],
        "migration_status": "BUNDLES_BUILT_LOCAL_PENDING_CLOUD_RUNTIME_VALIDATION",
        "official_claim_allowed": False,
        "bundles": receipts,
        "aggregate": {
            "archive": aggregate_name,
            "archive_bytes": aggregate_path.stat().st_size,
            "archive_sha256": sha256(aggregate_path),
            "contains_roles": sorted(ROLE_SEEDS),
        },
    }
    receipt_path = args.dist / "BUILD_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
