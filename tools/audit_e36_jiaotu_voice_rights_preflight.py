#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_PATH = ROOT / "workflow/tasks/AGENTCUT_CHARACTER_VOICE_REFERENCE_BATCH_V1_20260723_R1.json"
POLICY_PATH = ROOT / (
    "workflow/cloud_factory_migration_v1_20260724/dist_pipeline_parity/"
    "qingshan-ai-drama-pipeline/configs/agentcut_character_voice_reference_policy_v1.json"
)
SCRIPT_PATH = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST_PATH = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
OUTPUT_PATH = ROOT / (
    "qa/e36_agentcut_20260730/voice_rights_runtime/"
    "E36_JIAOTU_VOICE_RIGHTS_PREFLIGHT_V1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    batch = json.loads(BATCH_PATH.read_text())
    policy = json.loads(POLICY_PATH.read_text())
    manifest = json.loads(MANIFEST_PATH.read_text())

    role = next(item for item in policy["roles"] if item["entity_id"] == "jiaotu")
    generation = next(
        item for item in batch["generation_results"] if item["entity_id"] == "jiaotu"
    )
    result = generation["agentcut_result"]
    commercial = result.get("commercialUseMetadata", {})
    canonical_matches_manifest = sha256(SCRIPT_PATH) == manifest["sha256"]
    voice_matches_policy = result.get("voiceId") == role.get("voice_id")
    rights_present = commercial.get("present") is True
    release_blocked = commercial.get("releaseBlocked") is True
    release_eligible = result.get("releaseEligible") is True

    verdict = (
        "PASS_COMMERCIAL_RIGHTS_VERIFIED"
        if rights_present and release_eligible and not release_blocked
        else "BLOCK_JIAOTU_SOURCE_GENERATION_PENDING_COMMERCIAL_RIGHTS"
    )
    report = {
        "schema": "qingshan.e36.voice_rights_preflight.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-841",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if verdict.startswith("PASS_") else "BLOCKED",
        "verdict": verdict,
        "scope": {
            "entity_id": "jiaotu",
            "name": role["name"],
            "canonical_line_numbers": [11, 12, 27],
            "decision_scope": "new_source_audio_generation_and_release_admission",
        },
        "canonical_gate": {
            "script_path": str(SCRIPT_PATH),
            "script_sha256": sha256(SCRIPT_PATH),
            "manifest_path": str(MANIFEST_PATH),
            "manifest_file_sha256": sha256(MANIFEST_PATH),
            "manifest_script_sha256": manifest["sha256"],
            "matches": canonical_matches_manifest,
        },
        "voice_authority": {
            "policy_path": str(POLICY_PATH),
            "policy_sha256": sha256(POLICY_PATH),
            "batch_path": str(BATCH_PATH),
            "batch_sha256": sha256(BATCH_PATH),
            "policy_voice_id": role.get("voice_id"),
            "batch_voice_id": result.get("voiceId"),
            "voice_id_matches": voice_matches_policy,
            "reference_generation_task_id": result.get("taskId"),
            "commercial_use_metadata": commercial,
            "release_eligible": result.get("releaseEligible"),
            "required_post_generation_gates": result.get("requiredPostGenerationGates", []),
        },
        "gate_results": {
            "canonical_script_manifest": "PASS" if canonical_matches_manifest else "FAIL",
            "voice_id_binding": "PASS" if voice_matches_policy else "FAIL",
            "commercial_rights_metadata_present": "PASS" if rights_present else "FAIL",
            "release_blocked": "FAIL" if release_blocked else "PASS",
            "release_eligible": "PASS" if release_eligible else "FAIL",
            "new_paid_generation": "PASS_NONE",
            "credits": 0,
        },
        "blocked_by": (
            "The registered JiaoTu reference records commercialUseMetadata.present=false, "
            "releaseBlocked=true, and releaseEligible=false. New JiaoTu source generation and "
            "release admission remain closed until commercial-rights evidence is attached."
        ),
        "next_action": (
            "Preserve JiaoTu lines 11, 12, and 27 as rights-blocked without spending credits; "
            "continue E36 on a non-JiaoTu independent line whose voice authority and changed-input "
            "path are already admissible."
        ),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
