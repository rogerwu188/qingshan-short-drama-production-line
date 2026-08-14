#!/usr/bin/env python3
"""Build an evidence-bound, accepted-only E36 AgentCut source map."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V5.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
PLAN = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V2.json"
EXPECTED_SCRIPT_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"

P = "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs"

SOURCES = [
    ("U01", "U01", "working_assets/e36_v2_videos_20260728/E36-CW-U01-VIDEO-V1_277b8d83.mp4", "qa/e36_v2_video_20260728/E36_U01_VIDEO_QA_V1.json"),
    ("U02", "U02", f"{P}/E36_E36-CW-U02-VIDEO-V1-IDENTITY-REPAIR_66b975d4-9b03-44eb-bc84-93b48f3f916d.mp4", "qa/e36_v2_stills_repair_20260729/u02_video_runtime/E36_U02_TEMPORAL_VISUAL_QA_V1.json"),
    ("U02_R1A1", "U02", "working_assets/e36_recovery_10000_20260730/u02_r1a1_video/E36_E36-CW-U02-R1A1-CHANGED-INPUT-10000_cc12447b-dd3e-4eae-a077-c7ea3cb99f9a_LOCAL_TRIM_LATE_LEADIN_V1.mp4", "qa/e36_agentcut_20260730/u02_r1a1_video_runtime/E36_U02_R1A1_DIRECT_TEMPORAL_AND_VISUAL_QA_V1.json"),
    ("U02_R1A2", "U02", "working_assets/e36_recovery_10000_20260730/u02_r1a_video/E36_E36-CW-U02-R1A-RECOVERY-10000_c5a06506-9cd6-45df-9459-4c269186a007_SELECTED_R1A2_NATURAL_PAUSE_V2.mp4", "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36_U02_R1A2_DIRECT_SOURCE_NATIVE_ACCEPTANCE_V2.json"),
    ("U03", "U03", "working_assets/e36_v2_videos_20260728/E36-CW-U03-VIDEO-V1_43fe47b4.mp4", "qa/e36_v2_video_20260728/E36_U03_VIDEO_QA_V1.json"),
    ("U04_R2", "U04", "working_assets/e36_recovery_10000_20260730/u04_video_repair/E36_E36-CW-U04-VIDEO-R2-CHANGED-INPUT-REPAIR_1b104216-0f34-4b6b-88b8-bb5ca6364d22.mp4", "qa/e36_agentcut_20260730/u04_video_repair_runtime/E36_U04_VIDEO_CHANGED_INPUT_REPAIR_SEMANTIC_QA_V1.json"),
    ("U05", "U05", "working_assets/e36_v2_videos_20260728/E36-CW-U05-VIDEO-V1_592af09e.mp4", "qa/e36_v2_video_20260728/E36_U05_VIDEO_QA_V1.json"),
    ("U06", "U06", "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U06-LOCAL-ACTION-DETAIL-V6.mp4", "qa/e36_v2_stills_repair_20260729/local_fight_runtime/E36_U06_LOCAL_ACTION_DETAIL_MANUAL_QA_V1.json"),
    ("U07", "U07", "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U07-LOCAL-ACTION-DETAIL-V2.mp4", "qa/e36_v2_stills_repair_20260729/local_fight_runtime/E36_U07_LOCAL_ACTION_DETAIL_MANUAL_QA_V1.json"),
    ("U09_R1A", "U09", "working_assets/e36_recovery_10000_20260730/u09_r1a_video/E36_E36-CW-U09-R1A-CHANGED-INPUT-10000_a8fd831d-a5cf-4c94-8e5b-8d8787a1c23e_TRIM5P00.mp4", "qa/e36_agentcut_20260730/u09_r1a_video_runtime/E36_U09_R1A_DIRECT_TEMPORAL_ACCEPTANCE_V1.json"),
    ("U09_R1B", "U09", "working_assets/e36_recovery_10000_20260730/u09_r1b_video/E36_E36-CW-U09-R1B-CONTINUATION-10000_1500d215-250d-4ba8-aa46-56e88304d6b2_SELECTED_LATE_LEADIN_TRIM_V1.mp4", "qa/e36_agentcut_20260730/u09_r1b_video_runtime/E36_U09_R1B_DIRECT_TEMPORAL_ACCEPTANCE_V1.json"),
    ("U09_CANONICAL_LINE09_WAVE3", "U09", "working_assets/e36_autonomous_recovery_20260731/u09_split_wave3_line09/E36_E36-U09-CANONICAL-L09-WAVE3_fe943d60-0db4-4026-8fb4-62e5cc48e030.mp4", "qa/e36_agentcut_20260730/u09_split_wave3_line09_runtime/E36_U09_CANONICAL_L09_WAVE3_DIRECT_TEMPORAL_VISUAL_QA_V1.json"),
    ("U10_LINE15", "U10", "working_assets/e36_recovery_10000_20260730/u10_line15_video/E36_E36-CW-U10-L15-FAST6S-10000_33ff97c3-1b0c-4781-9a3a-17632fab43fc.mp4", "qa/e36_agentcut_20260730/u10_line15_video_runtime/E36_U10_LINE15_FAST6S_DIRECT_TEMPORAL_VISUAL_QA_V1.json"),
    ("U10_LINES13_14_AUTONOMOUS", "U10", "working_assets/e36_autonomous_recovery_20260731/u10_lines13_14/E36_E36-U10_LINES13_14-AUTONOMOUS_5a7853c6-4f8b-4d6c-b224-f6edf9b29e9c.mp4", "qa/e36_agentcut_20260730/u10_lines13_14_runtime/E36_U10_LINES13_14_DIRECT_TEMPORAL_VISUAL_QA_V1.json"),
    ("U11", "U11", f"{P}/E36_E36-CW-U11-VIDEO-V1_179acdde-6734-40f0-bf87-da2dfdd96ae2.mp4", "qa/e36_v2_stills_repair_20260729/u11_video_runtime/E36_U11_TEMPORAL_VISUAL_QA_V1.json"),
    ("U11_R1B", "U11", "working_assets/e36_recovery_10000_20260730/u11_r1b_video/E36_E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000_9afd46a1-07dd-4897-9d1d-3eb617ae21f2.mp4", "qa/e36_agentcut_20260730/u11_r1b_video_runtime/E36_U11_R1B_ROBUST_ASR_AND_DIRECT_TEMPORAL_QA_V1.json"),
    ("U12", "U12", f"{P}/E36_E36-CW-U12-VIDEO-R4-AGE17-FULL-LIPSYNC_0b54699c-26e7-4ab5-8bfc-8b5f674a8e62.mp4", "qa/e36_v2_stills_repair_20260729/u12_video_runtime/E36_U12_R4_TEMPORAL_VISUAL_QA.json"),
    ("U13", "U13", f"{P}/E36_E36-CW-U13-VIDEO-V1_beef403f-b20e-499b-95f7-64513b868e1a.mp4", "qa/e36_v2_stills_repair_20260729/u13_video_runtime/E36_U13_TEMPORAL_VISUAL_QA_V1.json"),
    ("U13_R1", "U13", "working_assets/e36_recovery_10000_20260730/u13_video/E36_E36-CW-U13-R1-RECOVERY-10000_3cc7ca4b-56c0-45ab-b18e-174cf8e9b79a.mp4", "qa/e36_agentcut_20260730/u13_video_runtime/E36_U13_R1_DIRECT_TEMPORAL_QA_V1.json"),
    ("U14_R3_D02", "U14", "working_assets/e36_recovery_10000_20260730/u14_r3_d02_video_repair/E36_E36-CW-U14-R3-D02-CHANGED-INPUT-REPAIR-10000_d2addeef-5422-4f57-afc7-d36438da5ca3_LOCAL_TRIM_CROP_NO_TEXT_V1.mp4", "qa/e36_agentcut_20260730/u14_r3_d02_video_repair_runtime/E36_U14_R3_D02_CHANGED_INPUT_REPAIR_LOCAL_SALVAGE_DIRECT_TEMPORAL_QA_V1.json"),
    ("U15A", "U15A", f"{P}/E36_E36-CW-U15A-VIDEO-V1_98aab52e-396f-4034-a5ef-a0656fc68be0.mp4", "qa/e36_v2_stills_repair_20260729/u15_video_runtime/E36-CW-U15A-VIDEO-V1_MANUAL_VISUAL_QA_V1.json"),
    ("U15B1", "U15B", f"{P}/E36_E36-CW-U15B-VIDEO-V1_5039397e-3566-401c-a9b6-fd37f895afb9.mp4", "qa/e36_v2_stills_repair_20260729/u15_video_runtime/E36_U15B1_SELECTED_TAKE_MANUAL_QA_V1.json"),
    ("U15B2", "U15B", f"{P}/E36_E36-CW-U15B2-VIDEO-V1_254765f6-3fab-4f22-8578-257f15ae2fb7_TIMING_REPAIR_V1.mp4", "qa/e36_v2_stills_repair_20260729/u15_video_runtime/E36_U15B2_TIMING_REPAIR_POSTPRODUCTION_REPORT_V1.json"),
    ("U15C", "U15C", f"{P}/E36_E36-CW-U15C-VIDEO-V1_3b867d57-6541-4933-9809-cf70184a9ca6_TIMING_REPAIR_V1.mp4", "qa/e36_v2_stills_repair_20260729/u15_video_runtime/E36_U15C_TIMING_REPAIR_MANUAL_QA_V1.json"),
    ("U16A", "U16", f"{P}/E36_E36-CW-U16A-VIDEO-V1_4d395596-896a-4ed5-9b98-16a3426e133c_ENDSTATE_REPAIR_V1.mp4", "qa/e36_v2_stills_repair_20260729/u16_video_runtime/E36_U16A_ENDSTATE_REPAIR_MANUAL_QA_V1.json"),
    ("U16B", "U16", f"{P}/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09_TICKET_TEXT_TRIM4P7_V2.mp4", "qa/e36_v2_stills_repair_20260729/u16_video_runtime/E36_U16B_TICKET_TEXT_TRIM4P7_MANUAL_QA_V1.json"),
    ("U17", "U17", "working_assets/e36_v2_stills_20260728/u17_local_fallback/E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V3.mp4", "qa/e36_v2_stills_repair_20260729/u17_video_runtime/E36_U17_LOCAL_FALLBACK_MANUAL_QA_V1.json"),
    ("U18A", "U18", f"{P}/E36_E36-CW-U18A-VIDEO-V1_8de6077c-72ac-4e29-9c20-7fe57d370287_TEXTFREE_CROP.mp4", "qa/e36_v2_stills_repair_20260729/u18_video_runtime/E36_U18A_TEXTFREE_CROP_MANUAL_QA_V1.json"),
    ("U18B", "U18", f"{P}/E36_E36-CW-U18B-VIDEO-V1-FAST_ef02d6e9-050d-4d37-a626-11d27d03f78f_TEXTFREE_CROP.mp4", "qa/e36_v2_stills_repair_20260729/u18_video_runtime/E36_U18B_TEXTFREE_CROP_MANUAL_QA_V1.json"),
    ("U18C", "U18", f"{P}/E36_E36-CW-U18C-VIDEO-V1-FAST_7e3f1dd2-fdf0-4db4-85b9-0588c7c229b7_TEXTFREE_CROP.mp4", "qa/e36_v2_stills_repair_20260729/u18_video_runtime/E36_U18C_TEXTFREE_CROP_MANUAL_QA_V1.json"),
    ("U18D", "U18", f"{P}/E36_E36-CW-U18D-VIDEO-V1-FAST_4454e3c5-9600-4339-afa0-00a4e40d8b0e_DEDUP_FRAMES_TEXTFREE_CROP.mp4", "qa/e36_v2_stills_repair_20260729/u18_video_runtime/E36_U18D_DEDUP_TEXTFREE_CROP_MANUAL_QA_V1.json"),
    ("U18_R2", "U18", "working_assets/e36_recovery_10000_20260730/u18_r2_video/E36_E36-CW-U18-R2-RECOVERY-10000_98a1afd3-2910-4ce7-82ba-3a004db44ebe.mp4", "qa/e36_agentcut_20260730/u18_r2_video_runtime/E36_U18_R2_DIRECT_TEMPORAL_QA_V1.json"),
    ("U19A", "U19A", f"{P}/E36_E36-CW-U19A-VIDEO-V2_e59e238a-daaf-44dc-8b9c-c6754809b0cc.mp4", "qa/e36_v2_stills_repair_20260729/u19_video_runtime/E36_U19A_VIDEO_MANUAL_QA_R2_V1.json"),
    ("U19B", "U19B", f"{P}/E36_E36-CW-U19B-VIDEO-V3_b792796e-d8d5-457b-afdf-f88ca21d49d9.mp4", "qa/e36_v2_stills_repair_20260729/u19_video_runtime/E36_U19B_VIDEO_MANUAL_QA_R3_V1.json"),
    ("U19C", "U19C", f"{P}/E36_E36-CW-U19C-VIDEO-V3_TRIM040_70741794-4d63-4f0b-a074-58ba09555467.mp4", "qa/e36_v2_stills_repair_20260729/u19_video_runtime/E36_U19C_VIDEO_MANUAL_QA_V3_TRIM040_V1.json"),
    ("U20A_R1", "U20A", "working_assets/e36_recovery_10000_20260730/u20a_r1_video/E36_E36-CW-U20A-R1-RECOVERY-10000_cf7a9d2d-e0bb-4d95-bfa1-a04890054dd9.mp4", "qa/e36_agentcut_20260730/u20a_r1_video_runtime/E36_U20A_R1_DIRECT_TEMPORAL_QA_V1.json"),
    ("U20A_R2A", "U20A", "working_assets/e36_recovery_10000_20260730/u20a_r2a_video/E36_E36-CW-U20A-R2A-RECOVERY-10000_d5950254-752f-4d01-a87c-338dbbd0e628_LOCAL_REMOVE_DUPLICATE_LEADIN_V1.mp4", "qa/e36_agentcut_20260730/u20a_r2_video_runtime/E36_U20A_R2A_DIRECT_TEMPORAL_AND_DIALOGUE_PRECISION_QA_V1.json"),
    ("U20A_R2B", "U20A", "working_assets/e36_recovery_10000_20260730/u20a_r2b_video/E36_E36-CW-U20A-R2B-RECOVERY-10000_0f533c17-f104-41c9-bd39-8aaed40b7e78_LOCAL_TRIM_LATE_LEADIN_V1.mp4", "qa/e36_agentcut_20260730/u20a_r2_video_runtime/E36_U20A_R2B_DIRECT_TEMPORAL_AND_AUDIO_TIMING_QA_V1.json"),
    ("U20B1", "U20B1", f"{P}/E36_E36-CW-U20B1-VIDEO-V1_b9955941-26f1-4e05-b127-c2f36a95c7e2.mp4", "qa/e36_v2_stills_repair_20260729/u20b1_video_runtime/E36_U20B1_TEMPORAL_VISUAL_QA_V1.json"),
    ("U20B2_JOIN", "U20B2A,U20B2B1A,U20B2B1B,U20B2B2", "exports/e36/agentcut_v4_d02_join_breathtrim_textclean_20260729/E36_AGENTCUT_V4_D02_JOIN_BREATHTRIM_TEXTCLEAN_NOT_FINAL.mp4", "qa/e36_postproduction_20260729/d02_join/E36_D02_JOIN_BREATHTRIM_TEXTCLEAN_FINAL_QA_V4.json"),
    ("U21", "U21", f"{P}/E36_E36-CW-U21-VIDEO-V1-CONTINUATION_8e7fa021-08a3-4506-847d-9b1db31266d9.mp4", "qa/e36_v2_stills_repair_20260729/u21_video_runtime/E36_U21_TEMPORAL_VISUAL_QA_V1.json"),
    ("U21_R1", "U21", "working_assets/e36_recovery_10000_20260730/u21_r1_video/E36_E36-CW-U21-R1-RECOVERY-10000_a715168a-332d-499f-9746-815e416ccd6f.mp4", "qa/e36_agentcut_20260730/u21_r1_video_runtime/E36_U21_R1_DIRECT_TEMPORAL_AND_AUDIO_TAIL_QA_V1.json"),
]

MISSING = {
    "U08": "No accepted motion source or authoritative video QA exists locally.",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    command = [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command, text=True))


def main() -> None:
    script_sha = sha256(SCRIPT)
    manifest_data = json.loads(MANIFEST.read_text())
    plan_data = json.loads(PLAN.read_text())
    canonical_gate = script_sha == EXPECTED_SCRIPT_SHA == manifest_data.get("sha256") == plan_data.get("source_script_sha256")
    rows = []
    all_files = canonical_gate
    covered = set()
    timeline = 0.0
    for source_id, canonical_units, media_rel, qa_rel in SOURCES:
        media = ROOT / media_rel
        qa = ROOT / qa_rel
        exists = media.is_file() and qa.is_file()
        all_files = all_files and exists
        media_probe = probe(media) if media.is_file() else {}
        duration = float(media_probe.get("format", {}).get("duration", 0.0))
        start = timeline
        timeline += duration
        covered.update(canonical_units.split(","))
        rows.append({
            "source_id": source_id,
            "canonical_units": canonical_units.split(","),
            "admission": "PASS_ACCEPTED_ONLY" if exists else "FAIL_MISSING_FILE_OR_QA",
            "media": media_rel,
            "media_sha256": sha256(media) if media.is_file() else None,
            "qa_authority": qa_rel,
            "qa_sha256": sha256(qa) if qa.is_file() else None,
            "duration_seconds": round(duration, 6),
            "accepted_only_timeline_seconds": [round(start, 6), round(timeline, 6)],
            "probe": media_probe,
        })
    canonical_units = [row["unit_id"] for row in plan_data["units"]]
    unresolved = [unit for unit in canonical_units if unit not in covered]
    report = {
        "schema": "qingshan.e36.agentcut_accepted_only_source_map.v5",
        "episode": "E36",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_cl2x": "CL2X-872",
        "source_mailbox_sha256": "2f2a1470cf865b528df1df042d9c3eb8efcfc8dd0eaf217b6377231f3e700dc5",
        "status": "BLOCKED_FULL_ASSEMBLY_MISSING_CANONICAL_MOTION_SOURCES" if unresolved else "PASS_READY_FOR_FULL_ASSEMBLY",
        "canonical_gate": {
            "status": "PASS" if canonical_gate else "FAIL",
            "script": str(SCRIPT.relative_to(ROOT)),
            "script_sha256": script_sha,
            "manifest": str(MANIFEST.relative_to(ROOT)),
            "manifest_declared_script_sha256": manifest_data.get("sha256"),
            "natural_unit_plan": str(PLAN.relative_to(ROOT)),
            "natural_unit_count": len(canonical_units),
        },
        "accepted_source_count": len(rows),
        "accepted_canonical_unit_count": len(set(canonical_units) - set(unresolved)),
        "canonical_unit_count": len(canonical_units),
        "accepted_only_runtime_seconds": round(timeline, 6),
        "all_admitted_files_and_qa_exist": all_files,
        "sources": rows,
        "unresolved_canonical_units": [{"unit_id": unit, "reason": MISSING.get(unit, "No accepted source mapped.")} for unit in unresolved],
        "assembly_gate": "FAIL_DO_NOT_RENDER_INCOMPLETE_EPISODE" if unresolved else "PASS",
        "credits": {"new_generation_credits": 916, "episode_total": 8880, "cap": 10000, "headroom": 1120},
        "blocked_by": "MISSING_ACCEPTED_CANONICAL_MOTION_SOURCES:" + ",".join(unresolved) if unresolved else None,
        "next_action": "Repair or produce accepted zero-credit motion coverage for " + ", ".join(unresolved) + "; rerun this source-map builder, then assemble the full episode and run full-cut QA." if unresolved else "Assemble full episode and run full-cut QA.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"out": str(OUT), "status": report["status"], "accepted": report["accepted_canonical_unit_count"], "total": report["canonical_unit_count"], "unresolved": unresolved}, ensure_ascii=False))


if __name__ == "__main__":
    main()
