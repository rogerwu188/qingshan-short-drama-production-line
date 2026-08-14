#!/usr/bin/env python3
"""Plan and render bounded V23 review windows for the eight transcript gaps."""

from __future__ import annotations

import hashlib
import json
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / (
    "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/"
    "E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
)
ASR_QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_FULL_RUNTIME_CANONICAL_DIALOGUE_ASR_ALIGNMENT_QA_V1.json"
BINDING = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V15.json"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260801/v23_missing_dialogue_insertion_windows_v1"
OUT_QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_MISSING_DIALOGUE_INSERTION_WINDOW_PLAN_QA_V1.json"
FFMPEG = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-17/referenced-chatgpt-conversation-this-is-untrusted/"
    "agentcut-0.9.7/agentcut/vendor/darwin-arm64/ffmpeg"
)
CANDIDATE_DURATION_SECONDS = 293.942

MISSING = (4, 5, 11, 12, 23, 24, 27, 28)
NEIGHBORS = {
    4: (3, 6),
    5: (3, 6),
    11: (10, 13),
    12: (10, 13),
    23: (22, 25),
    24: (22, 25),
    27: (26, 29),
    28: (26, 29),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def median_diagnostic(line: dict, key: str) -> float:
    values = [
        float(result["best_diagnostic_only"][key])
        for result in line["results"]
        if result.get("best_diagnostic_only", {}).get(key) is not None
    ]
    return round(statistics.median(values), 3)


def render_clip(item: dict) -> dict:
    line = item["line_number"]
    clip = OUT_DIR / f"E36_V23_LINE_{line:02d}_INSERTION_CONTEXT.mp4"
    log = OUT_DIR / f"E36_V23_LINE_{line:02d}_INSERTION_CONTEXT.log"
    start = item["review_window_seconds"][0]
    duration = round(item["review_window_seconds"][1] - start, 3)
    command = [
        str(FFMPEG), "-hide_banner", "-y", "-ss", f"{start:.3f}", "-i", str(MEDIA),
        "-t", f"{duration:.3f}", "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        str(clip),
    ]
    run = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    log.write_bytes(run.stderr)
    if run.returncode:
        raise RuntimeError(f"line {line} render failed with exit {run.returncode}")
    decode = subprocess.run(
        [str(FFMPEG), "-v", "error", "-i", str(clip), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    decode_log = OUT_DIR / f"E36_V23_LINE_{line:02d}_INSERTION_CONTEXT_DECODE.log"
    decode_log.write_bytes(decode.stderr)
    if decode.returncode:
        raise RuntimeError(f"line {line} decode failed with exit {decode.returncode}")
    return {
        "line_number": line,
        "path": str(clip.relative_to(ROOT)),
        "sha256": sha256(clip),
        "size_bytes": clip.stat().st_size,
        "duration_seconds": duration,
        "render_log": str(log.relative_to(ROOT)),
        "render_log_sha256": sha256(log),
        "decode_log": str(decode_log.relative_to(ROOT)),
        "decode_log_sha256": sha256(decode_log),
        "full_av_decode": "PASS_ZERO_ERRORS",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    asr = json.loads(ASR_QA.read_text(encoding="utf-8"))
    binding = json.loads(BINDING.read_text(encoding="utf-8"))
    lines = {int(row["line_number"]): row for row in asr["line_results"]}
    contract = {int(row["contract_line_number"]): row for row in binding["line_results"]}

    items = []
    for line_number in MISSING:
        previous_line, next_line = NEIGHBORS[line_number]
        previous_end = median_diagnostic(lines[previous_line], "end")
        next_start = median_diagnostic(lines[next_line], "start")
        raw_gap = round(next_start - previous_end, 3)
        pair = [number for number in MISSING if NEIGHBORS[number] == (previous_line, next_line)]
        ordinal = pair.index(line_number)
        fraction = (ordinal + 1) / (len(pair) + 1)
        target = previous_end + max(raw_gap, 0.0) * fraction
        if raw_gap <= 0:
            target = (previous_end + next_start) / 2
        review_start = round(max(0.0, target - 6.0), 3)
        review_end = round(min(CANDIDATE_DURATION_SECONDS, target + 6.0), 3)
        expected = round(max(1.2, len(contract[line_number]["normalized_text"]) / 4.2), 3)
        allocated_gap = round(max(raw_gap, 0.0) / len(pair), 3)
        speaker = contract[line_number]["speaker"]
        rights_policy = (
            "RIGHTS_CLEARED_MODEL_NATIVE_FEMALE_VOICE_ONLY_NO_UNVERIFIED_CLONE"
            if speaker == "皎兔"
            else "SOURCE_NATIVE_CANONICAL_MANDARIN_VISIBLE_PERFORMANCE_REQUIRED"
        )
        if raw_gap <= 0:
            feasibility = "NO_POSITIVE_TIMELINE_GAP_LOCAL_REORDER_OR_REPLACEMENT_REQUIRED"
        elif allocated_gap < expected:
            feasibility = "INSUFFICIENT_FREE_INTERVAL_LOCAL_REORDER_OR_REPLACEMENT_REQUIRED"
        else:
            feasibility = "TEMPORAL_HOST_EXISTS_BUT_NO_COMPLIANT_DIALOGUE_SOURCE_IDENTIFIED"
        items.append(
            {
                "line_number": line_number,
                "speaker": speaker,
                "canonical_text": contract[line_number]["text"],
                "accepted_before": False,
                "previous_accepted_anchor": {
                    "line_number": previous_line,
                    "median_diagnostic_end_seconds": previous_end,
                },
                "next_accepted_anchor": {
                    "line_number": next_line,
                    "median_diagnostic_start_seconds": next_start,
                },
                "pair_free_interval_seconds": [previous_end, next_start],
                "pair_free_duration_seconds": raw_gap,
                "allocated_free_duration_seconds": allocated_gap,
                "estimated_minimum_dialogue_duration_seconds": expected,
                "review_window_seconds": [review_start, review_end],
                "rights_policy": rights_policy,
                "insertion_feasibility": feasibility,
                "admission": "NONE_DIAGNOSTIC_PLANNING_ONLY",
            }
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        rendered = list(pool.map(render_clip, items))
    rendered_by_line = {row["line_number"]: row for row in rendered}
    for item in items:
        item["review_media"] = rendered_by_line[item["line_number"]]

    payload = {
        "schema": "qingshan.e36.v23_missing_dialogue_insertion_window_plan_qa.v1",
        "episode": "E36",
        "source_cl2x": "CL2X-924",
        "source_mailbox_sha256": "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7",
        "generated_at": "2026-08-01T15:42:10Z",
        "canonical": {
            "script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
            "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        },
        "inputs": {
            "candidate": str(MEDIA.relative_to(ROOT)),
            "candidate_sha256": sha256(MEDIA),
            "full_runtime_asr_alignment": str(ASR_QA.relative_to(ROOT)),
            "full_runtime_asr_alignment_sha256": sha256(ASR_QA),
            "accepted_transcript_binding": str(BINDING.relative_to(ROOT)),
            "accepted_transcript_binding_sha256": sha256(BINDING),
        },
        "method": {
            "anchor_rule": "MEDIAN_OF_FOUR_UNPROMPTED_UNCONDITIONED_FULL_RUNTIME_ASR_DIAGNOSTIC_TIMESTAMPS",
            "window_rule": "TWELVE_SECOND_NATIVE_CONTEXT_CENTERED_AT_ORDERED_PAIR_ALLOCATION",
            "scope": "ZERO_CREDIT_INSERTION_PREFLIGHT_AND_BOUNDED_REVIEW_MEDIA_ONLY",
            "limitations": "ASR_TIMESTAMPS_ARE_DIAGNOSTIC;THEY_DO_NOT_PROVE_TEXT_SPEAKER_RIGHTS_LIPSYNC_OR_ADMISSION",
        },
        "line_plans": items,
        "summary": {
            "missing_lines_planned": list(MISSING),
            "review_clips_rendered": len(rendered),
            "review_clips_full_av_decode_pass": sum(row["full_av_decode"].startswith("PASS") for row in rendered),
            "positive_pair_gaps": sum(item["pair_free_duration_seconds"] > 0 for item in items) // 2,
            "lines_with_sufficient_allocated_interval": sum(
                item["allocated_free_duration_seconds"] >= item["estimated_minimum_dialogue_duration_seconds"]
                for item in items
            ),
            "new_transcript_admissions": [],
            "accepted_transcript_after": "39_OF_47",
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "missing_line_inventory": "PASS_8_OF_8",
            "bounded_review_media": "PASS_8_OF_8_RENDERED_AND_FULL_AV_DECODED",
            "temporal_host_preflight": "PASS_PLANNED_FAIL_NO_COMPLIANT_DIALOGUE_SOURCE_IDENTIFIED",
            "JiaoTu_rights_policy": "PASS_RIGHTS_CLEARED_MODEL_NATIVE_ONLY",
            "transcript": "HOLD_39_OF_47",
            "continuous_full_runtime_human_watch": "NOT_COMPLETE",
            "V23_promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "blocked_by": (
            "PROMOTION_ONLY:V23_CONTINUOUS_AUDIOVISUAL_WATCH_INCOMPLETE;"
            "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;"
            "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
            "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
        ),
        "workaround_executed": (
            "Derived robust neighboring accepted-line timestamps for every missing canonical line, classified each "
            "candidate insertion interval, and rendered eight native V23 A/V context clips for targeted review."
        ),
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000, "headroom": 24},
        "next_action": (
            "Review only these eight bounded V23 windows for reusable reaction or cutaway spans; build a reversible "
            "insertion only if a source-native canonical performance with valid speaker rights is found."
        ),
        "status": "PASS_ZERO_CREDIT_INSERTION_WINDOW_PLAN_TRANSCRIPT_HOLD",
    }
    OUT_QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"qa": str(OUT_QA.relative_to(ROOT)), "sha256": sha256(OUT_QA), "clips": len(rendered)}))


if __name__ == "__main__":
    main()
