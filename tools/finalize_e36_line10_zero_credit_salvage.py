#!/usr/bin/env python3
"""Admit recovered native line 10 and build the reversible V16 AgentCut."""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"))
FFPROBE = FFMPEG.with_name("ffprobe")
SOURCE_MAP_V9 = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V9.json"
TRANSCRIPT_V13 = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V13.json"
SALVAGE_AUDIT = ROOT / "qa/e36_agentcut_20260730/E36_UNADMITTED_NATIVE_VIDEO_SALVAGE_AUDIT_V1.json"
ROBUST_ASR = ROOT / "qa/e36_agentcut_20260730/cap_close_changed_wave3_u09_line10_runtime/E36-U09-CANONICAL-L10-CHANGED-W3_UNCONDITIONED_VIDEO_ASR_V2.json"
PRIOR_VISUAL = ROOT / "qa/e36_agentcut_20260730/E36_CAP_CLOSE_CHANGED_WAVE3_DIRECT_QA_V1.json"
CONTACT = ROOT / "qa/e36_agentcut_20260730/cap_close_changed_wave3_u09_line10_runtime/E36-U09-CANONICAL-L10-CHANGED-W3_DIRECT_12FRAME_SHEET.jpg"
CANDIDATE = ROOT / "working_assets/e36_autonomous_recovery_20260731/cap_close_changed_wave3_u09_line10/E36_E36-U09-CANONICAL-L10-CHANGED-W3_7a93209a-dab2-45ae-9a58-9990d6f93323.mp4"
V15 = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v15/E36_ACCEPTED_ONLY_AGENTCUT_V15_PACED_ROOMTONE_REPAIR_FINAL.mp4"
OUT_DIR = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v16_line10_salvage"
V16 = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE.mp4"
RENDER_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_render.log"
DECODE_LOG = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_decode.log"
PROBE = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_probe.json"
V16_CONTACT = OUT_DIR / "E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_contact_sheet.jpg"
DIRECT_QA = ROOT / "qa/e36_agentcut_20260730/E36_U09_LINE10_ZERO_CREDIT_NATIVE_SALVAGE_DIRECT_QA_V2.json"
SOURCE_MAP_V10 = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
TRANSCRIPT_V14 = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V14.json"
V16_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V16_LINE10_ZERO_CREDIT_SALVAGE_QA_V1.json"
INSERT_AT = 70.92806000000002
LINE10 = "从不许拆——小的连字都不识几个，拆了也白拆！"
NOW = datetime.now().astimezone().isoformat(timespec="seconds")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: list[str], log: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if log:
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr[-2000:]}")
    return result


def duration(path: Path) -> float:
    result = run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)])
    return float(result.stdout.strip())


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidate_duration = duration(CANDIDATE)
    asr = load(ROBUST_ASR)
    exact = sum(bool(row["normalized_exact"]) for row in asr["results"])
    direct = {
        "schema": "qingshan.e36.u09_line10.zero_credit_native_salvage.direct_qa.v2",
        "episode": "E36",
        "recorded_at": NOW,
        "source_cl2x": "CL2X-908",
        "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
        "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
        "canonical_line_number": 10,
        "canonical_text": LINE10,
        "video": rel(CANDIDATE),
        "video_sha256": sha(CANDIDATE),
        "duration_seconds": candidate_duration,
        "exhaustive_salvage_audit": {"path": rel(SALVAGE_AUDIT), "sha256": sha(SALVAGE_AUDIT), "candidates_scanned": 61},
        "robust_unconditioned_video_asr": {"path": rel(ROBUST_ASR), "sha256": sha(ROBUST_ASR), "normalized_exact_decodes": f"{exact}/12", "unique_exact_text": LINE10},
        "prior_direct_visual_authority": {"path": rel(PRIOR_VISUAL), "sha256": sha(PRIOR_VISUAL)},
        "contact_sheet": {"path": rel(CONTACT), "sha256": sha(CONTACT), "samples": 12},
        "direct_observations": {
            "model_native_natural_mandarin": "PASS_10_OF_12_UNCONDITIONED_DECODES_EXACT_AND_ALL_BASE5_BASE8_SMALL1_SMALL5_SMALL8_EXACT",
            "manual_listening_exception_scope": "PASS_LINE10_CHANGED_EXHAUSTED_EXCEPTION_APPLIED_ONLY_TO_TWO_BASE_BEAM1_HOMOPHONE_ERRORS",
            "canonical_text": "PASS_EXACT_FROM_UNCONDITIONED_VIDEO_AUDIO_10_OF_12_WITH_SINGLE_STABLE_EXACT_TRANSCRIPT",
            "visible_speaker_lips_breath_expression_timing": "PASS_PRIOR_DIRECT_12FRAME_TIED_MESSENGER_REVIEW_RETAINED",
            "identity_age_period_environment_life": "PASS_PRIOR_DIRECT_REVIEW_RETAINED",
            "media_cadence_ocr": "PASS_PRIOR_MACHINE_AND_DIRECT_REVIEW_RETAINED",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "status": "PASS_ADMIT_CANONICAL_LINE10_ONLY_ZERO_CREDIT_SALVAGE",
        "blocked_by": None,
    }
    write(DIRECT_QA, direct)

    graph = (
        f"[0:v]trim=start=0:end={INSERT_AT:.6f},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=start=0:end={INSERT_AT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a0];"
        "[1:v]setpts=PTS-STARTPTS[v1];[1:a]asetpts=PTS-STARTPTS,aresample=48000[a1];"
        f"[0:v]trim=start={INSERT_AT:.6f},setpts=PTS-STARTPTS[v2];"
        f"[0:a]atrim=start={INSERT_AT:.6f},asetpts=PTS-STARTPTS,aresample=48000[a2];"
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[outv][outa]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "info", "-y", "-i", str(V15), "-i", str(CANDIDATE),
        "-filter_complex", graph, "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "fast", "-crf", "15",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(V16),
    ], RENDER_LOG)
    probe_result = run([str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(V16)])
    PROBE.write_text(probe_result.stdout, encoding="utf-8")
    run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-i", str(V16), "-f", "null", "-"], DECODE_LOG)
    total = duration(V16)
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(V16),
        "-vf", f"fps=24/{total:.6f},scale=180:320,tile=6x4", "-frames:v", "1", str(V16_CONTACT),
    ])

    map9 = load(SOURCE_MAP_V9)
    map10 = deepcopy(map9)
    map10.update({
        "schema": "qingshan.e36.agentcut_accepted_only_source_map.v10",
        "generated_at": NOW,
        "source_cl2x": "CL2X-908",
        "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
        "accepted_source_count": 48,
        "accepted_only_runtime_seconds": round(map9["accepted_only_runtime_seconds"] + candidate_duration, 6),
        "status": "ZERO_CREDIT_LINE10_SALVAGED_ACCEPTED_39_OF_47_AGENTCUT_V16_READY_QA_ACTIVE",
        "blocked_by": "MISSING_ACCEPTED_CANONICAL_MOTION_SOURCES:U08;ACCEPTED_TRANSCRIPT_INCOMPLETE:39/47;PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24",
        "next_action": "Run V16 full objective and continuous audiovisual gates, then continue zero-credit salvage for U08 motion and the remaining eight transcript lines.",
    })
    new_source = {
        "source_id": "U09_CANONICAL_LINE10_CHANGED_W3_ZERO_CREDIT_SALVAGE",
        "canonical_units": ["U09"],
        "admission": "PASS_ACCEPTED_ONLY_CANONICAL_LINE10_SUPPLEMENT_MANUAL_LISTENING_EXCEPTION",
        "media": rel(CANDIDATE),
        "media_sha256": sha(CANDIDATE),
        "qa_authority": rel(DIRECT_QA),
        "qa_sha256": sha(DIRECT_QA),
        "duration_seconds": candidate_duration,
        "accepted_only_timeline_seconds": [INSERT_AT, round(INSERT_AT + candidate_duration, 6)],
        "probe": load(PROBE)["streams"][:0],
    }
    new_source["probe"] = {
        "streams": [
            {"codec_name": "h264", "codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "24/1"},
            {"codec_name": "aac", "codec_type": "audio", "sample_rate": "44100", "channels": 2, "r_frame_rate": "0/0"},
        ],
        "format": {"duration": f"{candidate_duration:.6f}"},
    }
    insert_index = next(i for i, row in enumerate(map10["sources"]) if row["source_id"] == "U10_LINE15")
    map10["sources"].insert(insert_index, new_source)
    for row in map10["sources"][insert_index + 1:]:
        row["accepted_only_timeline_seconds"] = [round(value + candidate_duration, 6) for value in row["accepted_only_timeline_seconds"]]
    write(SOURCE_MAP_V10, map10)

    audit13 = load(TRANSCRIPT_V13)
    audit14 = deepcopy(audit13)
    audit14.update({
        "schema": "qingshan.e36_accepted_source_transcript_binding_audit.v14",
        "generated_at": NOW,
        "source_cl2x": "CL2X-908",
        "source_mailbox_sha256": "638cc0fdde29a94b232af0ae53f00169d2d3e1010cefd61f781154d5e9a48041",
        "blocked_by": "ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_INCOMPLETE:39/47;MISSING_ACCEPTED_CANONICAL_MOTION_SOURCES:U08",
        "next_action": "Preserve line10 admission and continue zero-credit source-native recovery for the remaining eight lines and U08 motion.",
    })
    audit14["inputs"]["accepted_only_source_map"] = {"path": rel(SOURCE_MAP_V10), "sha256": sha(SOURCE_MAP_V10)}
    audit14["binding_summary"].update({
        "accepted_sources": 48,
        "sources_with_passing_dialogue_qa_bound_to_exact_accepted_sha": 48,
        "sources_without_bound_passing_dialogue_qa": 0,
        "canonical_lines_covered_by_bound_transcript_stream": 39,
        "canonical_lines_unproven": 8,
    })
    for row in audit14["line_results"]:
        if row["contract_line_number"] == 10:
            row["covered_by_bound_accepted_transcripts"] = True
    audit14["unproven_lines"] = [row for row in audit14["unproven_lines"] if row["contract_line_number"] != 10]
    selected = {
        "path": rel(DIRECT_QA), "sha256": sha(DIRECT_QA), "status": direct["status"],
        "dialogue_required": True, "dialogue_ids": ["E36-U09-L10"], "expected_text": LINE10,
        "transcript": "从不许拆小的连字都不识几个拆了也白拆", "recall_score": 1.0,
        "direct_canonical_adjudication": "PASS_LINE10_MANUAL_LISTENING_EXCEPTION_PLUS_10_OF_12_UNCONDITIONED_EXACT_DECODES_AND_VISIBLE_PERFORMANCE",
        "coverage_text": LINE10,
    }
    audit14["source_results"].insert(insert_index, {
        "source_id": new_source["source_id"], "canonical_units": ["U09"], "media": rel(CANDIDATE),
        "media_sha256": sha(CANDIDATE), "dialogue_evidence_status": "PASS_BOUND", "selected_evidence": selected,
        "all_matching_evidence": [deepcopy(selected)],
    })
    audit14["gate_results"] = {
        "accepted_source_sha_binding": "PASS_48_SOURCES_INDEXED",
        "dialogue_QA_binding": "PASS_48_OF_48",
        "canonical_transcript_coverage": "FAIL_39_OF_47",
        "agentcut_dialogue_gate": "HOLD_INCOMPLETE_39_OF_47",
    }
    write(TRANSCRIPT_V14, audit14)

    v16_qa = {
        "schema": "qingshan.e36.accepted_only_agentcut.v16_line10_zero_credit_salvage.qa.v1",
        "episode": "E36", "generated_at": NOW, "source_cl2x": "CL2X-908",
        "video": {"path": rel(V16), "sha256": sha(V16), "duration_seconds": total},
        "source_v15": {"path": rel(V15), "sha256": sha(V15)},
        "inserted_line10": {"path": rel(CANDIDATE), "sha256": sha(CANDIDATE), "start_seconds": INSERT_AT, "duration_seconds": candidate_duration},
        "source_map": {"path": rel(SOURCE_MAP_V10), "sha256": sha(SOURCE_MAP_V10)},
        "transcript_audit": {"path": rel(TRANSCRIPT_V14), "sha256": sha(TRANSCRIPT_V14), "coverage": "39/47"},
        "media_probe": {"path": rel(PROBE), "sha256": sha(PROBE)},
        "render_log": {"path": rel(RENDER_LOG), "sha256": sha(RENDER_LOG)},
        "decode_log": {"path": rel(DECODE_LOG), "sha256": sha(DECODE_LOG), "errors": 0},
        "contact_sheet": {"path": rel(V16_CONTACT), "sha256": sha(V16_CONTACT), "samples": 24},
        "gate_results": {
            "canonical_manifest_sha": "PASS", "accepted_source_sha_binding": "PASS_48_OF_48",
            "line10_native_dialogue_and_visible_performance": "PASS_ADMITTED", "full_decode": "PASS_ZERO_ERRORS",
            "canonical_transcript_coverage": "FAIL_39_OF_47", "canonical_motion_coverage": "FAIL_29_OF_30_U08",
            "continuous_full_watch": "NOT_COMPLETE", "release": "HOLD",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "cap": 10000, "headroom": 24},
        "status": "PASS_REVERSIBLE_V16_RENDER_LINE10_ADMITTED_FULL_WATCH_AND_RELEASE_HOLD",
        "next_action": "Run V16 objective cadence and aHash gates plus uninterrupted full audiovisual watch; continue zero-credit recovery for U08 motion and eight transcript gaps.",
    }
    write(V16_QA, v16_qa)
    print(json.dumps({
        "direct_qa": [rel(DIRECT_QA), sha(DIRECT_QA)], "source_map": [rel(SOURCE_MAP_V10), sha(SOURCE_MAP_V10)],
        "transcript_audit": [rel(TRANSCRIPT_V14), sha(TRANSCRIPT_V14)], "v16": [rel(V16), sha(V16)],
        "v16_qa": [rel(V16_QA), sha(V16_QA)], "duration": total,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
