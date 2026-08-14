#!/usr/bin/env python3
"""Bind accepted E36 motion sources to existing native-dialogue QA evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V5.json"
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V9.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    text = text.replace("**", "").replace("……", "")
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)).lower()


def accepted_media_sha(payload: dict) -> str | None:
    """Resolve direct QA bindings used by source and consensus reports."""
    direct = payload.get("video_sha256") or payload.get("accepted_video_sha256")
    if direct:
        return str(direct)
    video = payload.get("video")
    if isinstance(video, dict) and video.get("sha256"):
        return str(video["sha256"])
    salvage = payload.get("zero_credit_local_salvage")
    if isinstance(salvage, dict) and salvage.get("sha256"):
        return str(salvage["sha256"])
    return None


def transcript_text(payload: dict) -> str:
    if payload.get("transcript"):
        return str(payload["transcript"])
    dialogue_timing = payload.get("dialogue_timing")
    if isinstance(dialogue_timing, dict) and dialogue_timing.get("detected_text"):
        return str(dialogue_timing["detected_text"])
    windows = payload.get("gates", {}).get("native_dialogue_per_window", {}).get("windows", [])
    window_text = "".join(str(row.get("transcript") or "") for row in windows)
    if window_text:
        return window_text
    canonical = payload.get("canonical_dialogue")
    if isinstance(canonical, dict):
        for key in ("salvage_transcript", "asr_transcript", "transcript"):
            if canonical.get(key):
                return str(canonical[key])
    direct = payload.get("evidence")
    if isinstance(direct, dict) and direct.get("asr_transcript"):
        return str(direct["asr_transcript"])
    exact = [
        str(row.get("transcript") or "")
        for row in payload.get("evidence", [])
        if isinstance(row, dict) and row.get("exact_match") is True
    ]
    return exact[0] if exact else ""


def expected_text(payload: dict) -> str:
    if payload.get("expected_text"):
        return str(payload["expected_text"])
    dialogue_timing = payload.get("dialogue_timing")
    if isinstance(dialogue_timing, dict) and dialogue_timing.get("expected_text"):
        return str(dialogue_timing["expected_text"])
    windows = payload.get("gates", {}).get("native_dialogue_per_window", {}).get("windows", [])
    window_text = "".join(str(row.get("expected") or "") for row in windows)
    if window_text:
        return window_text
    canonical = payload.get("canonical_dialogue")
    if isinstance(canonical, dict) and canonical.get("text"):
        return str(canonical["text"])
    direct = payload.get("evidence")
    if isinstance(direct, dict) and direct.get("expected_exact_text"):
        return str(direct["expected_exact_text"])
    return ""


def direct_canonical_adjudication(payload: dict) -> str | None:
    """Return why expected text is direct-review-authoritative, when applicable."""
    verdict = str(payload.get("verdict") or payload.get("status") or "")
    if not verdict.startswith("PASS"):
        return None
    dialogue_timing = payload.get("dialogue_timing")
    if (
        isinstance(dialogue_timing, dict)
        and str(dialogue_timing.get("status") or "").startswith("PASS")
        and dialogue_timing.get("recall") == 1.0
    ):
        return "PASS_DIRECT_DIALOGUE_TIMING_RECALL_1P0"
    canonical = payload.get("canonical_dialogue")
    if isinstance(canonical, dict):
        result = str(canonical.get("result") or "")
        homophone = str(canonical.get("homophone_adjudication") or "")
        if result.startswith("PASS"):
            return result
        if homophone.startswith("PASS"):
            return homophone
    direct = payload.get("evidence")
    if isinstance(direct, dict) and direct.get("asr_recall") == 1.0 and not payload.get("failures"):
        return "PASS_DIRECT_ASR_RECALL_1P0_AND_AUDIO_TAIL_REVIEW"
    return None


def recall_score(payload: dict) -> float | None:
    if payload.get("recall_score") is not None:
        return payload["recall_score"]
    dialogue_timing = payload.get("dialogue_timing")
    if isinstance(dialogue_timing, dict) and dialogue_timing.get("recall") is not None:
        return dialogue_timing["recall"]
    canonical = payload.get("canonical_dialogue")
    if isinstance(canonical, dict):
        for key in ("asr_exact_recall", "asr_normalized_recall"):
            if canonical.get(key) is not None:
                return canonical[key]
    direct = payload.get("evidence")
    if isinstance(direct, dict) and direct.get("asr_recall") is not None:
        return direct["asr_recall"]
    return None


def main() -> int:
    source_map = load(SOURCE_MAP)
    contract = load(CONTRACT)
    accepted_shas = {row["media_sha256"] for row in source_map["sources"]}
    evidence: dict[str, list[dict]] = {value: [] for value in accepted_shas}

    for path in (ROOT / "qa").rglob("*.json"):
        try:
            payload = load(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        media_sha = accepted_media_sha(payload)
        if media_sha not in evidence:
            continue
        transcript = transcript_text(payload)
        expected = expected_text(payload)
        adjudication = direct_canonical_adjudication(payload)
        if not transcript and not expected and "dialogue_required" not in payload:
            continue
        evidence[media_sha].append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256(path),
                "status": payload.get("status") or payload.get("verdict"),
                "dialogue_required": payload.get("dialogue_required"),
                "dialogue_ids": payload.get("dialogue_ids") or [],
                "expected_text": expected,
                "transcript": transcript,
                "recall_score": recall_score(payload),
                "direct_canonical_adjudication": adjudication,
                "coverage_text": expected if adjudication else transcript,
            }
        )

    source_results = []
    accepted_transcript_stream = ""
    for source in source_map["sources"]:
        records = sorted(evidence[source["media_sha256"]], key=lambda row: row["path"])
        passing = [row for row in records if str(row.get("status") or "").startswith("PASS")]
        speaking = [row for row in passing if row["transcript"] or row["expected_text"]]
        chosen = speaking[-1] if speaking else (passing[-1] if passing else None)
        if chosen and chosen["coverage_text"]:
            accepted_transcript_stream += normalize(chosen["coverage_text"])
        source_results.append(
            {
                "source_id": source["source_id"],
                "canonical_units": source["canonical_units"],
                "media": source["media"],
                "media_sha256": source["media_sha256"],
                "dialogue_evidence_status": "PASS_BOUND" if chosen else "UNPROVEN_NO_PASSING_DIALOGUE_QA_BOUND_TO_ACCEPTED_SHA",
                "selected_evidence": chosen,
                "all_matching_evidence": records,
            }
        )

    line_results = []
    for index, line in enumerate(contract["lines"], start=1):
        normalized = normalize(line["text"])
        covered = bool(normalized) and normalized in accepted_transcript_stream
        line_results.append(
            {
                "contract_line_number": index,
                "speaker": line["speaker"],
                "text": line["text"],
                "normalized_text": normalized,
                "covered_by_bound_accepted_transcripts": covered,
            }
        )

    covered_count = sum(row["covered_by_bound_accepted_transcripts"] for row in line_results)
    bound_sources = sum(row["dialogue_evidence_status"] == "PASS_BOUND" for row in source_results)
    payload = {
        "schema": "qingshan.e36_accepted_source_transcript_binding_audit.v9",
        "episode": "E36",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_cl2x": "CL2X-872",
        "source_mailbox_sha256": "2f2a1470cf865b528df1df042d9c3eb8efcfc8dd0eaf217b6377231f3e700dc5",
        "inputs": {
            "accepted_only_source_map": {"path": str(SOURCE_MAP.relative_to(ROOT)), "sha256": sha256(SOURCE_MAP)},
            "canonical_dialogue_contract": {"path": str(CONTRACT.relative_to(ROOT)), "sha256": sha256(CONTRACT)},
        },
        "binding_summary": {
            "accepted_sources": len(source_results),
            "sources_with_passing_dialogue_qa_bound_to_exact_accepted_sha": bound_sources,
            "sources_without_bound_passing_dialogue_qa": len(source_results) - bound_sources,
            "canonical_lines_covered_by_bound_transcript_stream": covered_count,
            "canonical_line_count": len(line_results),
            "canonical_lines_unproven": len(line_results) - covered_count,
            "status": "PASS" if covered_count == len(line_results) else "FAIL_ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_INCOMPLETE",
        },
        "source_results": source_results,
        "line_results": line_results,
        "unproven_lines": [row for row in line_results if not row["covered_by_bound_accepted_transcripts"]],
        "gate_results": {
            "accepted_source_sha_binding": f"PASS_{len(source_results)}_SOURCES_INDEXED",
            "dialogue_QA_binding": (
                f"PASS_{bound_sources}_OF_{len(source_results)}"
                if bound_sources == len(source_results)
                else f"PARTIAL_{bound_sources}_OF_{len(source_results)}"
            ),
            "canonical_transcript_coverage": f"FAIL_{covered_count}_OF_{len(line_results)}" if covered_count != len(line_results) else "PASS",
            "agentcut_dialogue_gate": "BLOCKED",
        },
        "blocked_by": "ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_INCOMPLETE",
        "next_action": "Generate or locate exact native-dialogue QA bound to every accepted source SHA, and produce missing canonical video sources; rerun until47/47 before AgentCut render.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "sha256": sha256(OUT), "binding_summary": payload["binding_summary"]}, ensure_ascii=False))
    return 1 if payload["binding_summary"]["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
