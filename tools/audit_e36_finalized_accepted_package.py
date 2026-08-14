#!/usr/bin/env python3
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAP_REL = "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V7.json"
TRANSCRIPT_REL = "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V11.json"
DISPATCH_REL = "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
OUT_REL = "qa/e36_agentcut_20260730/E36_FINALIZED_ACCEPTED_PACKAGE_INTEGRITY_QA_V1.json"
SCRIPT_REL = "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST_REL = "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel):
    return json.loads((ROOT / rel).read_text())


source_map = load(MAP_REL)
transcript = load(TRANSCRIPT_REL)
dispatch = load(DISPATCH_REL)
manifest = load(MANIFEST_REL)
failures = []
rows = []
seen_media_sha = {}
runtime_sum = 0.0

script_sha = digest(ROOT / SCRIPT_REL)
declared_script_sha = manifest.get("script_sha256") or manifest.get("canonical_script_sha256") or manifest.get("sha256")
if script_sha != declared_script_sha:
    failures.append("CANONICAL_SCRIPT_MANIFEST_SHA_MISMATCH")

for source in source_map["sources"]:
    media = ROOT / source["media"]
    qa = ROOT / source["qa_authority"]
    media_exists = media.is_file()
    qa_exists = qa.is_file()
    media_sha = digest(media) if media_exists else None
    qa_sha = digest(qa) if qa_exists else None
    media_sha_match = media_sha == source["media_sha256"]
    qa_sha_match = qa_sha == source["qa_sha256"]
    if not media_exists:
        failures.append(f"MISSING_MEDIA:{source['source_id']}")
    elif not media_sha_match:
        failures.append(f"MEDIA_SHA_MISMATCH:{source['source_id']}")
    if not qa_exists:
        failures.append(f"MISSING_QA:{source['source_id']}")
    elif not qa_sha_match:
        failures.append(f"QA_SHA_MISMATCH:{source['source_id']}")
    runtime_sum += float(source["duration_seconds"])
    seen_media_sha.setdefault(source.get("media_sha256"), []).append(source["source_id"])
    rows.append({
        "source_id": source["source_id"],
        "media": source["media"],
        "media_exists": media_exists,
        "media_sha256": media_sha,
        "media_sha_match": media_sha_match,
        "qa_authority": source["qa_authority"],
        "qa_exists": qa_exists,
        "qa_sha256": qa_sha,
        "qa_sha_match": qa_sha_match,
        "duration_seconds": source["duration_seconds"]
    })

duplicate_groups = [ids for ids in seen_media_sha.values() if len(ids) > 1]
if duplicate_groups:
    failures.append("DUPLICATE_ACCEPTED_MEDIA_SHA")

binding = transcript["binding_summary"]
if len(source_map["sources"]) != source_map["accepted_source_count"]:
    failures.append("SOURCE_COUNT_MISMATCH")
if len(transcript["source_results"]) != binding["accepted_sources"]:
    failures.append("TRANSCRIPT_SOURCE_COUNT_MISMATCH")
if binding["accepted_sources"] != source_map["accepted_source_count"]:
    failures.append("MAP_TRANSCRIPT_ACCEPTED_COUNT_MISMATCH")
if len(transcript["unproven_lines"]) != binding["canonical_lines_unproven"]:
    failures.append("UNPROVEN_LINE_COUNT_MISMATCH")
if binding["canonical_lines_covered_by_bound_transcript_stream"] + binding["canonical_lines_unproven"] != binding["canonical_line_count"]:
    failures.append("CANONICAL_TRANSCRIPT_ARITHMETIC_MISMATCH")
if abs(runtime_sum - float(source_map["accepted_only_runtime_seconds"])) > 0.001:
    failures.append("ACCEPTED_RUNTIME_SUM_MISMATCH")

integrity = dispatch["subsequent_attempts"]["accepted_only_integrity"]
if digest(ROOT / MAP_REL) != integrity["source_map_sha256"]:
    failures.append("DISPATCH_SOURCE_MAP_SHA_MISMATCH")
if digest(ROOT / TRANSCRIPT_REL) != integrity["transcript_audit_sha256"]:
    failures.append("DISPATCH_TRANSCRIPT_SHA_MISMATCH")

report = {
    "schema": "qingshan.e36.finalized_accepted_package_integrity_qa.v1",
    "episode": "E36",
    "source_cl2x": "CL2X-880",
    "source_mailbox_sha256": "479543efc236ef7a42651b4533b70ed730972d3c58fd7b2186416c6866583fd8",
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "inputs": {
        "canonical_script": SCRIPT_REL,
        "canonical_script_sha256": script_sha,
        "manifest": MANIFEST_REL,
        "manifest_sha256": digest(ROOT / MANIFEST_REL),
        "manifest_declared_script_sha256": declared_script_sha,
        "source_map": MAP_REL,
        "source_map_sha256": digest(ROOT / MAP_REL),
        "transcript_audit": TRANSCRIPT_REL,
        "transcript_audit_sha256": digest(ROOT / TRANSCRIPT_REL),
        "dispatch": DISPATCH_REL,
        "dispatch_sha256": digest(ROOT / DISPATCH_REL)
    },
    "summary": {
        "accepted_sources_checked": len(rows),
        "media_files_present_and_sha_exact": sum(1 for r in rows if r["media_exists"] and r["media_sha_match"]),
        "qa_files_present_and_sha_exact": sum(1 for r in rows if r["qa_exists"] and r["qa_sha_match"]),
        "duplicate_accepted_media_sha_groups": len(duplicate_groups),
        "accepted_runtime_seconds_recomputed": round(runtime_sum, 6),
        "accepted_runtime_seconds_declared": source_map["accepted_only_runtime_seconds"],
        "transcript_coverage": f"{binding['canonical_lines_covered_by_bound_transcript_stream']}/{binding['canonical_line_count']}",
        "motion_coverage": f"{source_map['accepted_canonical_unit_count']}/{source_map['canonical_unit_count']}",
        "credits": source_map["credits"]
    },
    "source_results": rows,
    "duplicate_groups": duplicate_groups,
    "failures": failures,
    "status": "PASS_ACCEPTED_PACKAGE_INTEGRITY_AGENTCUT_RELEASE_STILL_BLOCKED" if not failures else "FAIL_ACCEPTED_PACKAGE_INTEGRITY",
    "blocked_by": source_map["blocked_by"],
    "next_action": "Preserve this verified accepted package. No AgentCut or release until transcript, U08 motion and credit gates are resolved."
}

out = ROOT / OUT_REL
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"report": OUT_REL, "sha256": digest(out), "status": report["status"], "failures": failures}, ensure_ascii=False))
