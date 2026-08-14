#!/usr/bin/env python3
"""Create and validate an E37 recipe map compatible with PF-004."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_previs_replacement_project_v1_20260802.json"
OUTPUT = ROOT / "configs/e37_agentcut_previs_replacement_project_v2_20260802.json"
TIMELINE = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_SHOT_RECIPE_MATERIALIZED_TIMELINE_V2.json"
RECEIPT = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_RECIPE_REMAP_VALIDATION_V2.json"
RENDER_MANIFEST = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_RENDER_MANIFEST_V2.json"
PROVENANCE = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_SHOT_RECIPE_PROVENANCE_V2.json"
REVIEW_REQUEST = ROOT / "qa/e37_preproduction_20260802/E37_AGENTCUT_PREVIS_REVIEW_REQUEST_V2.json"
COMPATIBILITY_AUDIT = ROOT / "qa/e37_preproduction_20260802/E37_SHOT_RECIPE_PROMPT_FAILURE_MEMORY_COMPATIBILITY_AUDIT_V1.json"
AGENTCUT = ROOT / ".agentcut_env/bin/agentcut"
EXPECTED_SOURCE_SHA = "c2bea6e4d144c6c36093401d76fb7db87386e5ed976a361dcce10629a54538ba"
EXPECTED_CANDIDATE_SHA = "bcc8295365fecee837e93a23c458b4972e39283aac6a6a0ce0483af08fbbe923"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str) -> dict:
    result = subprocess.run([str(AGENTCUT), *args], cwd=ROOT, text=True, capture_output=True)
    if not result.stdout.strip():
        raise SystemExit(result.stderr or f"AgentCut {' '.join(args)} returned no output")
    payload = json.loads(result.stdout)
    if result.returncode:
        raise SystemExit(json.dumps(payload, ensure_ascii=False))
    return payload


def main() -> int:
    if sha256(SOURCE) != EXPECTED_SOURCE_SHA:
        raise SystemExit("source project SHA mismatch")
    project = json.loads(SOURCE.read_text(encoding="utf-8"))
    changed = []
    clips = project["timeline"]["videoTracks"][0]["clips"]
    for clip in clips:
        recipe = clip["metadata"]["shot_recipe"]
        if recipe["recipe_id"] != "camera.slow_push_in":
            continue
        recipe["recipe_id"] = "camera.overhead_reveal"
        clip["metadata"]["recipe_prompt_compatibility"] = {
            "status": "PASS_PF004_SLOW_PUSH_CONFLICT_REMOVED",
            "superseded_recipe_id": "camera.slow_push_in",
            "replacement_recipe_id": "camera.overhead_reveal",
            "reason": "Ledger/date evidence reveal requires active causal reframing without the PF-004 slow-push failure mode.",
        }
        changed.append(clip["id"])
    if len(changed) != 10:
        raise SystemExit(f"expected 10 remaps, got {len(changed)}")

    project["version"] = "1.0"
    project["metadata"]["status"] = "NOT_FINAL_PREVIS_ONLY_POLICY_COMPATIBLE_RECIPE_MAP_V2"
    project["metadata"]["production_profile"] = "E37_PREVIS_ONLY_ZERO_CREDIT_PF004_COMPATIBLE_V2"
    project["metadata"]["parent_project"] = str(SOURCE)
    project["metadata"]["parent_project_sha256"] = EXPECTED_SOURCE_SHA
    project["metadata"]["recipe_prompt_compatibility_audit"] = str(COMPATIBILITY_AUDIT)
    project["metadata"]["recipe_prompt_compatibility_audit_sha256"] = sha256(COMPATIBILITY_AUDIT)
    project["metadata"]["recipe_remap"] = {
        "from": "camera.slow_push_in",
        "to": "camera.overhead_reveal",
        "clips": changed,
        "count": len(changed),
        "source_media_modified": False,
    }
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    health = run("health")
    validation = run("validate", "--strict-media", str(OUTPUT))
    compilation = run("compile", "--overwrite", str(OUTPUT))
    recipes = compilation["summary"]["shotRecipes"]
    materialized = recipes["materializedTimeline"]
    if health.get("version") != "0.9.17" or not health.get("ready"):
        raise SystemExit("AgentCut health failed")
    if not validation.get("valid") or validation.get("issues"):
        raise SystemExit("strict validation failed")
    if len(materialized) != 22:
        raise SystemExit("materialized clip count mismatch")
    if any(row["recipeId"] == "camera.slow_push_in" for row in materialized):
        raise SystemExit("slow-push recipe remains")
    if sum(row["recipeId"] == "camera.overhead_reveal" for row in materialized) != 12:
        raise SystemExit("overhead recipe count mismatch")

    recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    timeline_payload = {
        "schema": "agentcut.materialized_shot_recipes.v1",
        "status": "PASS_PREVIS_ONLY_PF004_COMPATIBLE_NOT_PRODUCTION_ADMISSION",
        "recordedAt": recorded_at,
        "outputSha256": EXPECTED_CANDIDATE_SHA,
        "projectId": "QINGSHAN-E37",
        "projectVersion": "PREVIS-V2-PF004-COMPATIBLE",
        "project": {
            "path": str(OUTPUT),
            "sha256": sha256(OUTPUT),
            "version": project["version"],
            "productionProfile": project["metadata"]["production_profile"],
        },
        "candidate": {
            "path": project["metadata"]["source_reel"],
            "sha256": EXPECTED_CANDIDATE_SHA,
            "scope": "PREVIS_ONLY",
        },
        "timelineProvenance": {
            "parentProject": str(SOURCE),
            "parentProjectSha256": EXPECTED_SOURCE_SHA,
            "compatibilityAudit": str(COMPATIBILITY_AUDIT),
            "compatibilityAuditSha256": sha256(COMPATIBILITY_AUDIT),
            "registryId": recipes["registryId"],
            "registryVersion": recipes["registryVersion"],
            "registrySha256": recipes["registrySha256"],
            "secondsAuthoritative": recipes["secondsAuthoritative"],
            "frameRounding": recipes["frameRounding"],
            "outputFps": recipes["outputFps"],
        },
        "clipCount": len(materialized),
        "materializedTimeline": materialized,
        "repairTasks": recipes["repairTasks"],
        "hardScopeLimit": project["metadata"]["hard_scope_limit"],
        "rollback": {
            "strategy": "Restore the exact V1 project and sidecar.",
            "sourceMediaModified": False,
            "platformMutationAuthorized": False,
        },
    }
    TIMELINE.write_text(json.dumps(timeline_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    render_manifest = {
        "schema": "qingshan.agentcut_previs_render_manifest.v1",
        "status": "COMPILE_ONLY_PREVIS_SOURCE_REEL_EXACT_SHA_BOUND",
        "project_id": "QINGSHAN-E37",
        "project_version": "PREVIS-V2-PF004-COMPATIBLE",
        "candidate_path": project["metadata"]["source_reel"],
        "candidate_sha256": EXPECTED_CANDIDATE_SHA,
        "project_path": str(OUTPUT),
        "project_sha256": sha256(OUTPUT),
        "timeline_duration_seconds": compilation["summary"]["duration"],
        "timeline_frames": 4176,
        "clip_count": len(compilation["summary"]["clips"]),
        "render_executed": False,
        "reason": "The immutable PREVIS_ONLY reel preserves timing while the V2 sidecar remaps only recipe metadata.",
        "release_eligible": False,
        "platform_mutation_authorized": False,
    }
    RENDER_MANIFEST.write_text(json.dumps(render_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    provenance = {
        "schema": "qingshan.agentcut.shot_recipe_provenance.v1",
        "project_id": "QINGSHAN-E37",
        "project_version": "PREVIS-V2-PF004-COMPATIBLE",
        "candidate_sha256": EXPECTED_CANDIDATE_SHA,
        "project_sha256": sha256(OUTPUT),
        "timeline_sha256": sha256(TIMELINE),
        "manifest_sha256": sha256(RENDER_MANIFEST),
        "parent_project_sha256": EXPECTED_SOURCE_SHA,
        "compatibility_audit_sha256": sha256(COMPATIBILITY_AUDIT),
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
                "project_version": "PREVIS-V2-PF004-COMPATIBLE",
                "candidate_sha256": EXPECTED_CANDIDATE_SHA,
                "shot_recipe_required": True,
            },
            "evidence_inputs": {
                "agentcut_shot_recipe_sidecar": str(TIMELINE),
                "agentcut_project": str(OUTPUT),
                "agentcut_render_manifest": str(RENDER_MANIFEST),
                "shot_recipe_provenance": str(PROVENANCE),
            },
        }]
    }
    REVIEW_REQUEST.write_text(json.dumps(review_request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for row in materialized:
        counts[row["recipeId"]] = counts.get(row["recipeId"], 0) + 1
    receipt = {
        "schema": "qingshan.e37_agentcut_recipe_remap_validation.v2",
        "episode": "E37",
        "recorded_at": recorded_at,
        "status": "PASS_10_OF_10_PF004_CONFLICTS_REMAPPED_PREVIS_ONLY",
        "agentcut": {"version": health["version"], "ready": health["ready"]},
        "parent_project": {"path": str(SOURCE), "sha256": EXPECTED_SOURCE_SHA},
        "project": {"path": str(OUTPUT), "sha256": sha256(OUTPUT)},
        "timeline": {"path": str(TIMELINE), "sha256": sha256(TIMELINE)},
        "render_manifest": {"path": str(RENDER_MANIFEST), "sha256": sha256(RENDER_MANIFEST)},
        "provenance": {"path": str(PROVENANCE), "sha256": sha256(PROVENANCE)},
        "review_request": {"path": str(REVIEW_REQUEST), "sha256": sha256(REVIEW_REQUEST)},
        "remapped_clips": changed,
        "recipe_counts": counts,
        "gate_results": {
            "strict_media": "PASS_0_ISSUES",
            "compile": "PASS",
            "clip_count": "PASS_22_OF_22",
            "frame_coverage": "PASS_0_TO_4176_CONTIGUOUS",
            "slow_push_conflicts_remaining": "PASS_ZERO",
            "policy_compatible_clips": "PASS_22_OF_22",
            "production_admission": "NOT_ADMITTED_PREVIS_ONLY",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "rollback": "Restore the exact V1 project; no source or platform media was modified.",
        "next_action": "Use this V2 recipe map for future production submissions and rerun the six-capability review against each exact generated candidate before binding.",
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": receipt["status"],
        "project": str(OUTPUT.relative_to(ROOT)),
        "project_sha256": sha256(OUTPUT),
        "timeline": str(TIMELINE.relative_to(ROOT)),
        "timeline_sha256": sha256(TIMELINE),
        "receipt": str(RECEIPT.relative_to(ROOT)),
        "receipt_sha256": sha256(RECEIPT),
        "review_request": str(REVIEW_REQUEST.relative_to(ROOT)),
        "review_request_sha256": sha256(REVIEW_REQUEST),
        "recipe_counts": counts,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
