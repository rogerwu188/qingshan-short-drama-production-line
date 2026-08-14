#!/usr/bin/env python3
"""Verify every V10 accepted source and QA binding without changing media."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = ROOT / os.environ.get("E36_SOURCE_MAP", "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json")
TRANSCRIPT = ROOT / os.environ.get("E36_TRANSCRIPT_AUDIT", "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V14.json")
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
OUT = ROOT / os.environ.get("E36_CHAIN_QA_OUT", "qa/e36_agentcut_20260730/E36_ACCEPTED_PACKAGE_48_SOURCE_CHAIN_OF_CUSTODY_INTEGRITY_QA_V4.json")
TSV = ROOT / os.environ.get("E36_CHAIN_TSV_OUT", "qa/e36_agentcut_20260730/accepted_package_chain_of_custody_20260731/E36_ACCEPTED_PACKAGE_48_SOURCE_CHAIN_OF_CUSTODY_EVIDENCE_V4.tsv")
SOURCE_CL2X = os.environ.get("E36_SOURCE_CL2X", "CL2X-908")
MAILBOX_SHA = os.environ.get("E36_MAILBOX_SHA", "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


source_map = load(SOURCE_MAP)
transcript = load(TRANSCRIPT)
manifest = load(MANIFEST)
failures: list[str] = []
rows: list[dict] = []
media_paths: dict[str, list[str]] = {}
media_shas: dict[str, list[str]] = {}
qa_shas: dict[str, list[str]] = {}
runtime_sum = 0.0
previous_end = 0.0
timeline_discontinuities = 0
duration_mismatches = 0

script_sha = sha(SCRIPT)
declared_sha = manifest.get("sha256") or manifest.get("script_sha256") or manifest.get("canonical_script_sha256")
if script_sha != declared_sha:
    failures.append("CANONICAL_SCRIPT_MANIFEST_SHA_MISMATCH")

for source in source_map["sources"]:
    source_id = source["source_id"]
    media = ROOT / source["media"]
    authority = ROOT / source["qa_authority"]
    media_exists = media.is_file()
    qa_exists = authority.is_file()
    actual_media_sha = sha(media) if media_exists else None
    actual_qa_sha = sha(authority) if qa_exists else None
    media_match = actual_media_sha == source["media_sha256"]
    qa_match = actual_qa_sha == source["qa_sha256"]
    start, end = [float(value) for value in source["accepted_only_timeline_seconds"]]
    duration = float(source["duration_seconds"])
    continuity_delta = start - previous_end
    duration_delta = (end - start) - duration
    if abs(continuity_delta) > 0.001:
        timeline_discontinuities += 1
        failures.append(f"TIMELINE_DISCONTINUITY:{source_id}:{continuity_delta:.6f}")
    if abs(duration_delta) > 0.001:
        duration_mismatches += 1
        failures.append(f"DURATION_TIMELINE_MISMATCH:{source_id}:{duration_delta:.6f}")
    if not media_exists:
        failures.append(f"MISSING_MEDIA:{source_id}")
    elif not media_match:
        failures.append(f"MEDIA_SHA_MISMATCH:{source_id}")
    if not qa_exists:
        failures.append(f"MISSING_QA:{source_id}")
    elif not qa_match:
        failures.append(f"QA_SHA_MISMATCH:{source_id}")
    runtime_sum += duration
    previous_end = end
    media_paths.setdefault(source["media"], []).append(source_id)
    media_shas.setdefault(source["media_sha256"], []).append(source_id)
    qa_shas.setdefault(source["qa_sha256"], []).append(source_id)
    rows.append({
        "source_id": source_id,
        "media": source["media"],
        "media_exists": media_exists,
        "declared_media_sha256": source["media_sha256"],
        "actual_media_sha256": actual_media_sha,
        "media_sha_match": media_match,
        "qa_authority": source["qa_authority"],
        "qa_exists": qa_exists,
        "declared_qa_sha256": source["qa_sha256"],
        "actual_qa_sha256": actual_qa_sha,
        "qa_sha_match": qa_match,
        "duration_seconds": duration,
        "timeline_start_seconds": start,
        "timeline_end_seconds": end,
        "continuity_delta_seconds": round(continuity_delta, 6),
        "duration_delta_seconds": round(duration_delta, 6),
    })

binding = transcript["binding_summary"]
count = int(source_map["accepted_source_count"])
if len(rows) != count:
    failures.append("SOURCE_COUNT_MISMATCH")
if len(transcript["source_results"]) != count or binding["accepted_sources"] != count:
    failures.append("MAP_TRANSCRIPT_ACCEPTED_COUNT_MISMATCH")
if round(runtime_sum, 6) != round(float(source_map["accepted_only_runtime_seconds"]), 6):
    failures.append("ACCEPTED_RUNTIME_SUM_MISMATCH")
if abs(previous_end - float(source_map["accepted_only_runtime_seconds"])) > 0.001:
    failures.append("TIMELINE_FINAL_END_MISMATCH")

duplicate_path_groups = [ids for ids in media_paths.values() if len(ids) > 1]
duplicate_sha_groups = [ids for ids in media_shas.values() if len(ids) > 1]
if duplicate_path_groups:
    failures.append("DUPLICATE_ACCEPTED_MEDIA_PATH")
if duplicate_sha_groups:
    failures.append("DUPLICATE_ACCEPTED_MEDIA_SHA")

TSV.parent.mkdir(parents=True, exist_ok=True)
with TSV.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)

shared_qa = [
    {"qa_sha256": value, "source_ids": ids}
    for value, ids in qa_shas.items()
    if len(ids) > 1
]
report = {
    "schema": "qingshan.e36.accepted_package_chain_of_custody_integrity_qa.v4",
    "episode": "E36",
    "source_cl2x": SOURCE_CL2X,
    "source_mailbox_sha256": MAILBOX_SHA,
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "authority_inputs": {
        "canonical_script": rel(SCRIPT), "canonical_script_sha256": script_sha,
        "manifest": rel(MANIFEST), "manifest_sha256": sha(MANIFEST), "manifest_declared_script_sha256": declared_sha,
        "source_map": rel(SOURCE_MAP), "source_map_sha256": sha(SOURCE_MAP),
        "transcript_audit": rel(TRANSCRIPT), "transcript_audit_sha256": sha(TRANSCRIPT),
    },
    "gate_results": {
        "canonical_script_manifest": "PASS_EXACT" if script_sha == declared_sha else "FAIL",
        "accepted_source_count": count,
        "media_path_exists": f"PASS_{sum(row['media_exists'] for row in rows)}_OF_{count}",
        "media_sha256_matches_declared": f"PASS_{sum(row['media_sha_match'] for row in rows)}_OF_{count}",
        "qa_authority_path_exists": f"PASS_{sum(row['qa_exists'] for row in rows)}_OF_{count}",
        "qa_authority_sha256_matches_declared": f"PASS_{sum(row['qa_sha_match'] for row in rows)}_OF_{count}",
        "unique_media_path_count": len(media_paths),
        "unique_media_sha256_count": len(media_shas),
        "duplicate_media_aliases": len(duplicate_path_groups) + len(duplicate_sha_groups),
        "unique_qa_sha256_count": len(qa_shas),
        "shared_qa_authority_groups": shared_qa,
        "accepted_only_duration_sum_seconds": round(runtime_sum, 6),
        "accepted_only_timeline_final_end_seconds": round(previous_end, 6),
        "timeline_discontinuity_count": timeline_discontinuities,
        "duration_timeline_mismatch_count": duration_mismatches,
        "transcript_coverage": f"{binding['canonical_lines_covered_by_bound_transcript_stream']}/{binding['canonical_line_count']}",
        "motion_coverage": f"{source_map['accepted_canonical_unit_count']}/{source_map['canonical_unit_count']}",
        "overall": "PASS" if not failures else "FAIL",
    },
    "failures": failures,
    "evidence": {"tsv": rel(TSV), "tsv_sha256": sha(TSV), "rows": len(rows)},
    "blocked_by": os.environ.get("E36_CHAIN_BLOCKED_BY", "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE"),
    "workaround_executed": f"Recomputed all{count} accepted media and QA hashes and audited every accepted-only timeline interval at zero credits.",
    "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "limit": 10000, "headroom": 24},
    "next_action": os.environ.get("E36_CHAIN_NEXT_ACTION", "Bind this verified accepted-source chain to the latest AgentCut candidate and continue unresolved gates."),
    "status": f"PASS_{count}_SOURCE_ACCEPTED_PACKAGE_CHAIN_OF_CUSTODY" if not failures else "FAIL_ACCEPTED_PACKAGE_CHAIN_OF_CUSTODY",
}
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": rel(OUT), "sha256": sha(OUT), "status": report["status"], "failures": failures}, ensure_ascii=False))
