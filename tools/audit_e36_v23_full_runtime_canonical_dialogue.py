#!/usr/bin/env python3
"""Run materially distinct full-runtime ASR alignment over E36 V23."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / (
    "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/"
    "E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
)
CONTRACT = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e36_claude_writer_v2_4e46c013_20260728/E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json"
)
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
ACCEPTED_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V15.json"
OUT_DIR = ROOT / "qa/e36_agentcut_20260730/v23_full_runtime_canonical_dialogue_asr_v1"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_V23_FULL_RUNTIME_CANONICAL_DIALOGUE_ASR_ALIGNMENT_QA_V1.json"
SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
MANIFEST_SHA = "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5"
MEDIA_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"
MAILBOX_SHA = "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7"
MISSING = {4, 5, 11, 12, 23, 24, 27, 28}
T2S = OpenCC("t2s")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def norm(text: str) -> str:
    converted = T2S.convert(text).replace("**", "")
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", converted)).lower()


def best_diagnostic(expected: str, segments: list[dict]) -> dict:
    target = norm(expected)
    best = {"ratio": 0.0, "text": "", "start": None, "end": None}
    for width in (1, 2, 3):
        for index in range(max(0, len(segments) - width + 1)):
            group = segments[index:index + width]
            text = "".join(row["text"] for row in group)
            ratio = SequenceMatcher(None, target, norm(text)).ratio()
            if ratio > best["ratio"]:
                best = {
                    "ratio": round(ratio, 4),
                    "text": text,
                    "start": group[0]["start"],
                    "end": group[-1]["end"],
                }
    return best


def exact_segment_hits(expected: str, segments: list[dict]) -> list[dict]:
    target = norm(expected)
    hits = []
    for width in (1, 2, 3, 4):
        for index in range(max(0, len(segments) - width + 1)):
            group = segments[index:index + width]
            if target and target in norm("".join(row["text"] for row in group)):
                hits.append({
                    "start": group[0]["start"],
                    "end": group[-1]["end"],
                    "text": "".join(row["text"] for row in group),
                    "segment_count": width,
                })
                break
        if hits:
            break
    return hits


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    accepted = json.loads(ACCEPTED_AUDIT.read_text(encoding="utf-8"))
    accepted_missing = {row["contract_line_number"] for row in accepted["unproven_lines"]}
    gates = {
        "script_sha_exact": sha(SCRIPT) == SCRIPT_SHA,
        "manifest_file_sha_exact": sha(MANIFEST) == MANIFEST_SHA,
        "manifest_declares_script_sha": manifest.get("sha256") == SCRIPT_SHA,
        "contract_script_sha_exact": contract.get("source_script_sha256") == SCRIPT_SHA,
        "contract_line_count_47": len(contract.get("lines", [])) == 47,
        "v23_media_sha_exact": sha(MEDIA) == MEDIA_SHA,
        "accepted_audit_current_39_of_47": accepted["binding_summary"].get(
            "canonical_lines_covered_by_bound_transcript_stream"
        ) == 39,
        "accepted_missing_set_exact": accepted_missing == MISSING,
    }
    if not all(gates.values()):
        raise SystemExit(json.dumps(gates, ensure_ascii=False, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for vad_filter in (False, True):
            segments_iter, info = model.transcribe(
                str(MEDIA),
                language="zh",
                beam_size=5,
                best_of=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=vad_filter,
                word_timestamps=True,
            )
            segments = [{
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
            } for segment in segments_iter]
            run_id = f"{model_name}_beam5_vad_{str(vad_filter).lower()}"
            raw = {
                "run_id": run_id,
                "model": model_name,
                "beam_size": 5,
                "vad_filter": vad_filter,
                "condition_on_previous_text": False,
                "language": info.language,
                "language_probability": round(float(info.language_probability), 6),
                "segments": segments,
                "transcript": "".join(row["text"] for row in segments),
            }
            raw_path = OUT_DIR / f"E36_V23_FULL_RUNTIME_ASR_{run_id}.json"
            raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            runs.append({
                "run_id": run_id,
                "raw_path": rel(raw_path),
                "raw_sha256": sha(raw_path),
                "segments": segments,
                "normalized_transcript": norm(raw["transcript"]),
            })

    line_rows = []
    for line_number, line in enumerate(contract["lines"], 1):
        per_run = []
        for run in runs:
            exact_global = norm(line["text"]) in run["normalized_transcript"]
            exact_hits = exact_segment_hits(line["text"], run["segments"])
            per_run.append({
                "run_id": run["run_id"],
                "exact_contiguous_global": exact_global,
                "exact_timestamp_hits": exact_hits,
                "best_diagnostic_only": best_diagnostic(line["text"], run["segments"]),
            })
        exact_count = sum(row["exact_contiguous_global"] for row in per_run)
        line_rows.append({
            "line_number": line_number,
            "speaker": line["speaker"],
            "canonical_text": line["text"],
            "accepted_before_this_audit": line_number not in MISSING,
            "exact_full_runtime_asr_runs": exact_count,
            "results": per_run,
            "admission_result": (
                "NO_CHANGE_ALREADY_ACCEPTED" if line_number not in MISSING else
                "HOLD_ASR_IS_DIAGNOSTIC_NOT_ACCEPTED_SOURCE_PROVENANCE_AND_VIDEO_GATE"
            ),
        })

    missing_rows = [row for row in line_rows if row["line_number"] in MISSING]
    missing_exact = [row["line_number"] for row in missing_rows if row["exact_full_runtime_asr_runs"]]
    raw_inventory = [{
        "run_id": run["run_id"],
        "path": run["raw_path"],
        "sha256": run["raw_sha256"],
        "segment_count": len(run["segments"]),
    } for run in runs]
    payload = {
        "schema": "qingshan.e36.v23_full_runtime_canonical_dialogue_asr_alignment.v1",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-924",
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical_gate": {"status": "PASS", "checks": gates},
        "inputs": {
            "media": {"path": rel(MEDIA), "sha256": MEDIA_SHA},
            "contract": {"path": rel(CONTRACT), "sha256": sha(CONTRACT)},
            "accepted_transcript_authority": {"path": rel(ACCEPTED_AUDIT), "sha256": sha(ACCEPTED_AUDIT)},
        },
        "method": {
            "scope": "FULL_293P942_SECOND_V23_RUNTIME_MATERIALLY_DISTINCT_FROM_PRIOR_BOUNDED_GAP_WINDOWS",
            "decodes": "BASE_AND_SMALL_X_VAD_OFF_ON_X_BEAM5_UNPROMPTED_UNCONDITIONED_WITH_TIMESTAMPS",
            "exact_rule": "OPENCC_T2S_ALNUM_CJK_NORMALIZED_CANONICAL_TEXT_CONTIGUOUS_IN_FULL_TRANSCRIPT",
            "diagnostic_rule": "BEST_SEQUENCE_MATCH_OVER_ONE_TO_THREE_ASR_SEGMENTS_NEVER_USED_FOR_ADMISSION",
            "admission_policy": "ASR_ALONE_CANNOT_ADD_ACCEPTED_TRANSCRIPT_COVERAGE_WITHOUT_EXACT_ACCEPTED_SOURCE_SHA_PROVENANCE_AND_ALL_NATIVE_VIDEO_GATES",
        },
        "raw_asr_runs": raw_inventory,
        "line_results": line_rows,
        "summary": {
            "canonical_lines": 47,
            "full_runtime_asr_decodes": len(runs),
            "accepted_transcript_before": "39_OF_47",
            "missing_lines_audited": sorted(MISSING),
            "missing_lines_with_any_exact_full_runtime_asr": missing_exact,
            "new_lines_admitted": [],
            "accepted_transcript_after": "39_OF_47",
            "materially_distinct_full_runtime_evidence": "COMPLETE",
        },
        "gate_results": {
            "canonical_script_manifest_contract": "PASS_EXACT",
            "v23_media_sha": "PASS_EXACT",
            "full_runtime_asr": "PASS_4_OF_4_DECODES_COMPLETE",
            "missing_line_exact_diagnostic": (
                "NONE_DETECTED" if not missing_exact else f"DETECTED_LINES_{'_'.join(map(str, missing_exact))}_NOT_ADMITTED"
            ),
            "accepted_transcript": "HOLD_39_OF_47",
            "motion": "PASS_30_OF_30",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "V23_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
            "platform_action": "NONE",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
            "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": (
            "Ran four unprompted, unconditioned full-runtime V23 ASR decodes with timestamps and aligned all47 "
            "canonical lines. This materially differs from prior bounded gap-window scans. Exact ASR remains "
            "diagnostic only; no missing line is admitted without accepted-source SHA provenance and native-video gates."
        ),
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000, "headroom": 24},
        "next_action": (
            "Continue uninterrupted audiovisual review with the five bounded V23 reels and search only materially "
            "distinct source-native evidence for lines4/5/11/12/23/24/27/28; preserve V15 canonical and perform no platform submission."
        ),
        "status": "PASS_FULL_RUNTIME_ASR_ALIGNMENT_TRANSCRIPT_HOLD",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": rel(OUT),
        "sha256": sha(OUT),
        "raw_runs": raw_inventory,
        "missing_exact": missing_exact,
        "transcript": "39_OF_47_HOLD",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
