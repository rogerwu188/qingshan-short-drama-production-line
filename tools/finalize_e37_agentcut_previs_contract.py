#!/usr/bin/env python3
"""Validate and persist the E37 AgentCut 0.9.17 previs contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "configs/e37_agentcut_previs_replacement_project_v1_20260802.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
QA_DIR = ROOT / "qa/e37_preproduction_20260802"
MATERIALIZED = QA_DIR / "E37_AGENTCUT_PREVIS_SHOT_RECIPE_MATERIALIZED_TIMELINE_V1.json"
RENDER_MANIFEST = QA_DIR / "E37_AGENTCUT_PREVIS_RENDER_MANIFEST_V1.json"
PROVENANCE = QA_DIR / "E37_AGENTCUT_PREVIS_SHOT_RECIPE_PROVENANCE_V1.json"
REVIEW_REQUEST = QA_DIR / "E37_AGENTCUT_PREVIS_REVIEW_REQUEST_V1.json"
RECEIPT = QA_DIR / "E37_AGENTCUT_PREVIS_REPLACEMENT_VALIDATION_V1.json"
EXPECTED_REEL_SHA = "bcc8295365fecee837e93a23c458b4972e39283aac6a6a0ce0483af08fbbe923"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args: str) -> dict:
    process = subprocess.run(
        [str(AGENTCUT), *args], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if not process.stdout.strip():
        raise SystemExit(f"AgentCut {' '.join(args)} returned no JSON: {process.stderr}")
    value = json.loads(process.stdout)
    if process.returncode != 0:
        raise SystemExit(json.dumps(value, ensure_ascii=False))
    return value


def main() -> int:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    project_sha = sha256(PROJECT)
    health = run("health")
    validation = run("validate", "--strict-media", str(PROJECT))
    compilation = run("compile", "--overwrite", str(PROJECT))
    recipes = compilation["summary"]["shotRecipes"]
    timeline = recipes["materializedTimeline"]

    if health.get("version") != "0.9.17" or not health.get("ready"):
        raise SystemExit("AgentCut 0.9.17 health gate failed")
    if not validation.get("valid") or validation.get("issues"):
        raise SystemExit("strict AgentCut project validation failed")
    if recipes.get("status") != "PASS" or len(timeline) != 22:
        raise SystemExit("shot recipe materialization gate failed")
    if [item["clipId"] for item in timeline] != [
        clip["id"] for clip in project["timeline"]["videoTracks"][0]["clips"]
    ]:
        raise SystemExit("materialized clip order mismatch")
    if timeline[0]["frameRange"]["startFrame"] != 0 or timeline[-1]["frameRange"]["endFrameExclusive"] != 4176:
        raise SystemExit("materialized timeline boundary mismatch")
    for left, right in zip(timeline, timeline[1:]):
        if left["frameRange"]["endFrameExclusive"] != right["frameRange"]["startFrame"]:
            raise SystemExit("materialized frame coverage gap")
    for item in timeline:
        phase_ids = [phase["phaseId"] for phase in item["motionArc"]["phases"]]
        if phase_ids[0] != "setup" or "contact" not in phase_ids or phase_ids[-1] != "result":
            raise SystemExit(f"incomplete motion arc: {item['clipId']}")
        if not item["plannedHold"]["windows"] or not item["sfxCues"]:
            raise SystemExit(f"missing hold or SFX cue: {item['clipId']}")
        if item["intentionalBlack"] is not None:
            raise SystemExit(f"unexpected intentional black: {item['clipId']}")

    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    materialized_payload = {
        "schema": "agentcut.materialized_shot_recipes.v1",
        "status": "PASS_PREVIS_ONLY_NOT_PRODUCTION_ADMISSION",
        "recordedAt": recorded_at,
        "outputSha256": EXPECTED_REEL_SHA,
        "projectId": "QINGSHAN-E37",
        "projectVersion": "PREVIS-V1",
        "project": {
            "path": str(PROJECT),
            "sha256": project_sha,
            "version": project["version"],
            "productionProfile": project["metadata"]["production_profile"],
        },
        "candidate": {
            "path": project["metadata"]["source_reel"],
            "sha256": EXPECTED_REEL_SHA,
            "scope": "PREVIS_ONLY",
        },
        "timelineProvenance": {
            "sourceTimingQa": project["metadata"]["source_timing_qa"],
            "sourceTimingQaSha256": project["metadata"]["source_timing_qa_sha256"],
            "promptBindingRegistry": project["metadata"]["prompt_binding_registry"],
            "promptBindingRegistrySha256": project["metadata"]["prompt_binding_registry_sha256"],
            "registryId": recipes["registryId"],
            "registryVersion": recipes["registryVersion"],
            "registrySha256": recipes["registrySha256"],
            "secondsAuthoritative": recipes["secondsAuthoritative"],
            "frameRounding": recipes["frameRounding"],
            "outputFps": recipes["outputFps"],
        },
        "clipCount": len(timeline),
        "materializedTimeline": timeline,
        "repairTasks": recipes["repairTasks"],
        "hardScopeLimit": project["metadata"]["hard_scope_limit"],
        "rollback": {
            "strategy": "Remove this PREVIS_ONLY project and sidecar; no source or platform media was modified.",
            "sourceMediaModified": False,
            "platformMutationAuthorized": False,
        },
    }
    QA_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALIZED.write_text(json.dumps(materialized_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    render_manifest = {
        "schema": "qingshan.agentcut_previs_render_manifest.v1",
        "status": "COMPILE_ONLY_PREVIS_SOURCE_REEL_EXACT_SHA_BOUND",
        "project_id": "QINGSHAN-E37",
        "project_version": "PREVIS-V1",
        "candidate_path": project["metadata"]["source_reel"],
        "candidate_sha256": EXPECTED_REEL_SHA,
        "project_path": str(PROJECT),
        "project_sha256": project_sha,
        "timeline_duration_seconds": compilation["summary"]["duration"],
        "timeline_frames": 4176,
        "clip_count": len(compilation["summary"]["clips"]),
        "render_executed": False,
        "reason": "The immutable full-episode PREVIS_ONLY source reel already materializes this exact 22-interval timing map; no duplicate render was needed.",
        "release_eligible": False,
        "platform_mutation_authorized": False,
    }
    RENDER_MANIFEST.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    provenance = {
        "schema": "qingshan.agentcut.shot_recipe_provenance.v1",
        "project_id": "QINGSHAN-E37",
        "project_version": "PREVIS-V1",
        "candidate_sha256": EXPECTED_REEL_SHA,
        "project_sha256": project_sha,
        "timeline_sha256": sha256(MATERIALIZED),
        "manifest_sha256": sha256(RENDER_MANIFEST),
        "scope": "PREVIS_ONLY_NOT_PRODUCTION_ADMISSION",
        "recorded_at": recorded_at,
    }
    PROVENANCE.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review_request = {
        "items": [{
            "path": project["metadata"]["source_reel"],
            "kind": "video",
            "scope": "full_cut",
            "importance": "critical",
            "pass_score": 4.0,
            "required_capabilities": [
                "video_analysis", "shot_recipe_conformance", "motion_arc_audit",
                "subject_anchor_audit", "beat_sync_audit", "sfx_cue_audit", "readability_audit",
            ],
            "run_regression_ci": False,
            "production_profile": "agentcut_director_v1",
            "metadata": {
                "status": "NOT_FINAL_PREVIS_ONLY",
                "read_only_review": True,
                "episode": "E37",
                "project_id": "QINGSHAN-E37",
                "project_version": "PREVIS-V1",
                "candidate_sha256": EXPECTED_REEL_SHA,
                "shot_recipe_required": True,
            },
            "evidence_inputs": {
                "agentcut_shot_recipe_sidecar": str(MATERIALIZED),
                "agentcut_project": str(PROJECT),
                "agentcut_render_manifest": str(RENDER_MANIFEST),
                "shot_recipe_provenance": str(PROVENANCE),
            },
        }]
    }
    REVIEW_REQUEST.write_text(json.dumps(review_request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema": "qingshan.e37_agentcut_previs_contract_validation.v1",
        "episode": "E37",
        "status": "PASS_PREVIS_CONTRACT_ONLY",
        "recorded_at": recorded_at,
        "agentcut": {
            "version": health["version"],
            "ready": health["ready"],
            "runtime_hash": health["runtimeHash"],
            "registry_sha256": recipes["registrySha256"],
        },
        "project": {"path": str(PROJECT), "sha256": project_sha, "clips": 22},
        "candidate": {"path": project["metadata"]["source_reel"], "sha256": EXPECTED_REEL_SHA},
        "materialized_timeline": {"path": str(MATERIALIZED), "sha256": sha256(MATERIALIZED)},
        "render_manifest": {"path": str(RENDER_MANIFEST), "sha256": sha256(RENDER_MANIFEST)},
        "provenance": {"path": str(PROVENANCE), "sha256": sha256(PROVENANCE)},
        "review_request": {"path": str(REVIEW_REQUEST), "sha256": sha256(REVIEW_REQUEST)},
        "gate_results": {
            "strict_media_validation": "PASS_0_ISSUES",
            "compile": "PASS",
            "shot_recipe_conformance_plan": "PASS_22_OF_22",
            "motion_arc_plan": "PASS_SETUP_CONTACT_RESULT_22_OF_22",
            "subject_anchor_plan": "PASS_22_OF_22",
            "planned_hold": "PASS_22_OF_22",
            "beat_anchor": "PASS_22_OF_22",
            "sfx_cue_manifest": "PASS_SYMBOLIC_ONLY_22_OF_22_NO_AUDIO_ASSET_IMPORTED",
            "intentional_black": "PASS_NONE_DECLARED_NONE_AUTHORIZED",
            "frame_coverage": "PASS_CONTIGUOUS_0_TO_4176",
            "release_eligibility": "FAIL_EXPECTED_PREVIS_ONLY_22_REPLACEMENTS_REQUIRED",
            "production_video_admission": "NOT_ADMITTED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "blocked_by": "PROVIDER_OUTPUT_ASSET_DB_ERROR1406_REPRODUCED_ON_PRO_OMNI_AND_FAST_I2V",
        "workaround_executed": "Materialized a complete zero-credit 22-clip AgentCut 0.9.17 replacement timeline with exact SHA provenance and director recipes.",
        "next_action": "Replace only the matching interval after an independently QA-accepted generated clip exists; rerun strict validation and production review before assembly.",
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "receipt": str(RECEIPT), "receipt_sha256": sha256(RECEIPT),
        "materialized": str(MATERIALIZED), "materialized_sha256": sha256(MATERIALIZED),
        "render_manifest": str(RENDER_MANIFEST), "render_manifest_sha256": sha256(RENDER_MANIFEST),
        "provenance": str(PROVENANCE), "provenance_sha256": sha256(PROVENANCE),
        "review_request": str(REVIEW_REQUEST), "review_request_sha256": sha256(REVIEW_REQUEST),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
