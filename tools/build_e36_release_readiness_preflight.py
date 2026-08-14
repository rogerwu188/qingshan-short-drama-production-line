#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_REL = "workflow/releases/E36_ACHIEVABLE_FINAL_RELEASE_READINESS_PREFLIGHT_20260731.json"


def load(rel):
    return json.loads((ROOT / rel).read_text())


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


source_map_rel = "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V7.json"
transcript_rel = "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V11.json"
integrity_rel = "qa/e36_agentcut_20260730/E36_FINALIZED_ACCEPTED_PACKAGE_INTEGRITY_QA_V1.json"
queue_rel = "workflow/work_queue.json"
prior_release_rel = "workflow/releases/E35_FINAL_V2_PLATFORM_RELEASE_20260724.json"

source_map = load(source_map_rel)
transcript = load(transcript_rel)
integrity = load(integrity_rel)
queue = load(queue_rel)
prior_release = load(prior_release_rel)

all_exported_mp4s = sorted(
    str(p.relative_to(ROOT))
    for p in (ROOT / "exports/e36").rglob("*.mp4")
) if (ROOT / "exports/e36").is_dir() else []
final_candidates = [p for p in all_exported_mp4s if "NOT_FINAL" not in Path(p).name.upper()]
not_final_exports = [p for p in all_exported_mp4s if p not in final_candidates]
final_locks = sorted(
    str(p.relative_to(ROOT))
    for p in (ROOT / "workflow").rglob("*E36*FINAL*LOCK*.json")
)
agentcut_outputs = sorted(
    str(p.relative_to(ROOT))
    for p in (ROOT / "qa/e36_agentcut_20260730").rglob("*.mp4")
)

blocking_gates = []
if transcript["binding_summary"]["canonical_lines_covered_by_bound_transcript_stream"] != transcript["binding_summary"]["canonical_line_count"]:
    blocking_gates.append("CANONICAL_TRANSCRIPT_NOT_47_OF_47")
if source_map["accepted_canonical_unit_count"] != source_map["canonical_unit_count"]:
    blocking_gates.append("CANONICAL_MOTION_NOT_30_OF_30_U08_MISSING")
if not final_candidates:
    blocking_gates.append("FINAL_MEDIA_MISSING")
if not final_locks:
    blocking_gates.append("FINAL_LOCK_MISSING")
if not agentcut_outputs:
    blocking_gates.append("AGENTCUT_OUTPUT_MISSING")
if source_map["credits"]["headroom"] < 96:
    blocking_gates.append("CREDIT_RUNWAY_INSUFFICIENT_FOR_MINIMUM_COMPLIANT_FAST6_VIDEO")

report = {
    "schema": "qingshan.e36.release_readiness_preflight.v1",
    "episode": "E36",
    "source_cl2x": "CL2X-880",
    "source_mailbox_sha256": "479543efc236ef7a42651b4533b70ed730972d3c58fd7b2186416c6866583fd8",
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "status": "HARD_HOLD_PRODUCTION_GATES_NO_PLATFORM_ACTION",
    "release_allowed": False,
    "irreversible_platform_action_attempted": False,
    "title_candidate": "青山EP36：假谍探真棋子",
    "release_targets": {
        "youtube": {
            "target": "YouTube Shorts",
            "prior_episode_evidence": prior_release_rel,
            "prior_episode_status": prior_release["youtube"]["submission_status"],
            "account_identity": "NOT_LOCALLY_DECLARED_IN_AUTHORITY_FILES",
            "credential_probe": "NOT_RUN_BECAUSE_FINAL_PACKAGE_AND_RELEASE_GATES_ARE_MISSING"
        },
        "douyin": {
            "target": "Douyin creator publication",
            "prior_episode_evidence": prior_release_rel,
            "prior_episode_status": prior_release["douyin"]["submission_status"],
            "account_identity": "NOT_LOCALLY_DECLARED_IN_AUTHORITY_FILES",
            "credential_probe": "NOT_RUN_BECAUSE_FINAL_PACKAGE_AND_RELEASE_GATES_ARE_MISSING"
        }
    },
    "production_inputs": {
        "source_map": {"path": source_map_rel, "sha256": sha(source_map_rel)},
        "transcript_audit": {"path": transcript_rel, "sha256": sha(transcript_rel)},
        "accepted_package_integrity": {"path": integrity_rel, "sha256": sha(integrity_rel)},
        "work_queue": {"path": queue_rel, "sha256": sha(queue_rel)},
        "prior_release_pattern": {"path": prior_release_rel, "sha256": sha(prior_release_rel)}
    },
    "readiness": {
        "accepted_media_integrity": integrity["status"],
        "accepted_source_count": source_map["accepted_source_count"],
        "transcript_coverage": f"{transcript['binding_summary']['canonical_lines_covered_by_bound_transcript_stream']}/{transcript['binding_summary']['canonical_line_count']}",
        "motion_coverage": f"{source_map['accepted_canonical_unit_count']}/{source_map['canonical_unit_count']}",
        "agentcut_outputs": agentcut_outputs,
        "final_candidates": final_candidates,
        "not_final_exports_excluded": not_final_exports,
        "final_locks": final_locks,
        "final_watch_gate": "NOT_RUN_NO_FINAL_MEDIA",
        "platform_package": "NOT_BUILT_NO_FINAL_MEDIA",
        "credits": source_map["credits"]
    },
    "blocking_gates": blocking_gates,
    "blocked_by": ";".join(blocking_gates),
    "next_action": "Preserve release targets and metadata candidate. Do not probe credentials or perform platform actions until a gate-complete final package exists."
}

out = ROOT / OUT_REL
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"report": OUT_REL, "sha256": sha(OUT_REL), "status": report["status"], "blocking_gates": blocking_gates}, ensure_ascii=False))
