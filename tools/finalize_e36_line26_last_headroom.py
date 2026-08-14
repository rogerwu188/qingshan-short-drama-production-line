#!/usr/bin/env python3
import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CL2X = "CL2X-880"
MAILBOX_SHA = "479543efc236ef7a42651b4533b70ed730972d3c58fd7b2186416c6866583fd8"
NOW = datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(rel):
    return json.loads((ROOT / rel).read_text())


def write_json(rel, value):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return path


def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


video = "working_assets/e36_autonomous_recovery_20260731/last_headroom_line26/E36_E36-U14-CANONICAL-L26-LAST-HEADROOM_60f9250b-7d6d-4669-a2b7-8ccb2d5e1337.mp4"
receipt = "qa/e36_agentcut_20260730/last_headroom_line26_runtime/RECEIPT.json"
native = "qa/e36_agentcut_20260730/last_headroom_line26_runtime/E36-U14-CANONICAL-L26-LAST-HEADROOM_native_dialogue.json"
cadence = "qa/e36_agentcut_20260730/last_headroom_line26_runtime/E36-U14-CANONICAL-L26-LAST-HEADROOM_frame_cadence.json"
ocr = "qa/e36_agentcut_20260730/last_headroom_line26_runtime/E36-U14-CANONICAL-L26-LAST-HEADROOM_ocr.json"
contact = "qa/e36_agentcut_20260730/last_headroom_line26_direct_review/E36_U14_L26_12FRAME_CONTACT.jpg"
last_frame = "qa/e36_agentcut_20260730/last_headroom_line26_direct_review/E36_U14_L26_LAST_FRAME_5_95.jpg"
direct_rel = "qa/e36_agentcut_20260730/E36_LAST_HEADROOM_LINE26_DIRECT_TEMPORAL_VISUAL_QA_V1.json"

direct = {
    "schema": "qingshan.e36.last_headroom_line26_direct_temporal_visual_qa.v1",
    "episode": "E36",
    "source_cl2x": SOURCE_CL2X,
    "source_mailbox_sha256": MAILBOX_SHA,
    "recorded_at": NOW,
    "task_id": "60f9250b-7d6d-4669-a2b7-8ccb2d5e1337",
    "video": video,
    "video_sha256": sha(video),
    "duration_seconds": 6.082993,
    "canonical_line_number": 26,
    "canonical_text": "他不是废子，是景朝拿来试各方反应的活棋子。",
    "normalized_transcript": "他不是废子是景朝拿来试各方反应的活棋子",
    "native_dialogue_evidence": {"path": native, "sha256": sha(native), "recall": 1.0},
    "cadence_evidence": {"path": cadence, "sha256": sha(cadence), "status": "PASS"},
    "ocr_evidence": {"path": ocr, "sha256": sha(ocr), "status": "PASS_ZERO_CRITICAL_TEXT"},
    "contact_sheet": {"path": contact, "sha256": sha(contact), "samples": 12},
    "terminal_frame": {"path": last_frame, "sha256": sha(last_frame), "timestamp_seconds": 5.95},
    "direct_observations": {
        "first_frame_in_motion": "PASS_RIGHT_INDEX_ALREADY_WITHDRAWING_ABOVE_INTACT_ENVELOPE",
        "visible_speaker_and_lipsync": "PASS_AGE17_CHENJI_VISIBLE_WITH_MOUTH_ARTICULATION_DURING_LINE",
        "breath_expression_timing": "PASS_SINGLE_CONTINUOUS_NATURAL_MANDARIN_PERFORMANCE_WITH_CLOSED_MOUTH_TERMINAL",
        "canonical_text": "PASS_NORMALIZED_EXACT_ASR_RECALL_1P0_UNDER_LINE26_LISTENING_EXCEPTION",
        "action_contact_direction_terminal": "PASS_LEFT_PALM_REMAINS_ON_TABLE_RIGHT_HAND_WITHDRAWS_AND_HOVERS_ENVELOPE_STAYS_INTACT_AND_STILL",
        "identity_age_period_weather": "PASS_AGE17_CHENJI_PERIOD_CLINIC_NIGHT_CONTINUITY",
        "environment_life": "PASS_VISIBLE_CANDLE_FLAME_AND_NATURAL_PERFORMANCE_MICROMOTION",
        "terminal_state": "PASS_CLOSED_MOUTH_RIGHT_HAND_HOVER_LEFT_HAND_TABLE_ENVELOPE_INTACT"
    },
    "machine_pass_does_not_override_direct_fail": True,
    "status": "PASS_ADMIT_CANONICAL_LINE26_ONLY",
    "admitted_lines": [26],
    "blocked_by": None
}
write_json(direct_rel, direct)
direct_sha = sha(direct_rel)

map6 = read_json("qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V6.json")
map7 = deepcopy(map6)
map7["schema"] = "qingshan.e36.agentcut_accepted_only_source_map.v7"
map7["generated_at"] = NOW
map7["source_cl2x"] = SOURCE_CL2X
map7["source_mailbox_sha256"] = MAILBOX_SHA
map7["accepted_source_count"] = 44
map7["accepted_only_runtime_seconds"] = round(map6["accepted_only_runtime_seconds"] + 6.082993, 6)
map7["credits"] = {
    "new_generation_credits": map6["credits"]["new_generation_credits"] + 96,
    "episode_total": 9976,
    "cap": 10000,
    "headroom": 24
}
map7["status"] = "FINALIZED_AT_ACHIEVABLE_COVERAGE_AGENTCUT_BLOCKED"
map7["blocked_by"] = "MISSING_ACCEPTED_CANONICAL_MOTION_SOURCES:U08;ACCEPTED_TRANSCRIPT_INCOMPLETE:35/47;CREDIT_RUNWAY_24_INSUFFICIENT_FOR_ANY_ADDITIONAL_COMPLIANT_VIDEO_ATTEMPT"
map7["next_action"] = "Preserve all 44 admitted sources and every FAIL. AgentCut and release remain closed; no further compliant paid video fits the 24-credit runway."
map7["sources"].append({
    "source_id": "U14_L26_LAST_HEADROOM",
    "canonical_units": ["U14"],
    "admission": "PASS_ACCEPTED_ONLY_CANONICAL_LINE26_SUPPLEMENT",
    "media": video,
    "media_sha256": sha(video),
    "qa_authority": direct_rel,
    "qa_sha256": direct_sha,
    "duration_seconds": 6.082993,
    "accepted_only_timeline_seconds": [259.118604, 265.201597],
    "probe": {
        "streams": [
            {"codec_name": "h264", "codec_type": "video", "width": 720, "height": 1280, "r_frame_rate": "24/1"},
            {"codec_name": "aac", "codec_type": "audio", "sample_rate": "44100", "channels": 2, "r_frame_rate": "0/0"}
        ],
        "format": {"duration": "6.082993"}
    }
})
map7_rel = "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V7.json"
write_json(map7_rel, map7)

audit10 = read_json("qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V10.json")
audit11 = deepcopy(audit10)
audit11["schema"] = "qingshan.e36_accepted_source_transcript_binding_audit.v11"
audit11["generated_at"] = NOW
audit11["source_cl2x"] = SOURCE_CL2X
audit11["source_mailbox_sha256"] = MAILBOX_SHA
audit11["binding_summary"].update({
    "accepted_sources": 44,
    "sources_with_passing_dialogue_qa_bound_to_exact_accepted_sha": 44,
    "canonical_lines_covered_by_bound_transcript_stream": 35,
    "canonical_lines_unproven": 12,
    "status": "FAIL_ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_INCOMPLETE"
})
audit11["unproven_lines"] = [x for x in audit11["unproven_lines"] if x["contract_line_number"] != 26]
for row in audit11["line_results"]:
    if row["contract_line_number"] == 26:
        row["covered_by_bound_accepted_transcripts"] = True
audit11["source_results"].append({
    "source_id": "U14_L26_LAST_HEADROOM",
    "canonical_units": ["U14"],
    "media": video,
    "media_sha256": sha(video),
    "dialogue_evidence_status": "PASS_BOUND",
    "selected_evidence": {
        "path": direct_rel,
        "sha256": direct_sha,
        "status": "PASS_ADMIT_CANONICAL_LINE26_ONLY",
        "dialogue_required": True,
        "dialogue_ids": ["E36-U14-CANONICAL-L26-LAST-HEADROOM"],
        "expected_text": "他不是废子，是景朝拿来试各方反应的活棋子。",
        "transcript": "他不是废子 是景朝拿来试各方反应的活棋子",
        "recall_score": 1.0,
        "direct_canonical_adjudication": "PASS_DIRECT_ASR_RECALL_1P0_AND_VISIBLE_PERFORMANCE_REVIEW",
        "coverage_text": "他不是废子，是景朝拿来试各方反应的活棋子。"
    },
    "all_matching_evidence": []
})
audit11["source_results"][-1]["all_matching_evidence"] = [deepcopy(audit11["source_results"][-1]["selected_evidence"])]
audit11["blocked_by"] = "ACCEPTED_SOURCE_TRANSCRIPT_COVERAGE_INCOMPLETE;CREDIT_RUNWAY_24_INSUFFICIENT_FOR_ANY_ADDITIONAL_COMPLIANT_VIDEO_ATTEMPT"
audit11["next_action"] = "Accepted-only coverage is finalized at35/47 with12 unproven lines; preserve all evidence and keep AgentCut/release closed."
audit11["gate_results"] = {
    "accepted_source_sha_binding": "PASS_44_SOURCES_INDEXED",
    "dialogue_QA_binding": "PASS_44_OF_44",
    "canonical_transcript_coverage": "FAIL_35_OF_47",
    "canonical_motion_coverage": "FAIL_29_OF_30_U08_MISSING",
    "agentcut_dialogue_gate": "BLOCKED",
    "release_gate": "BLOCKED"
}
audit11_rel = "qa/e36_agentcut_20260730/E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V11.json"
write_json(audit11_rel, audit11)

queue_rel = "workflow/work_queue.json"
queue = read_json(queue_rel)
queue["updated_at"] = NOW
queue["generation_credits"] = 9976
queue["generation_calls"] = 135
queue["real_active_handle_count"] = 0
queue["status"] = "E36_FINALIZED_AT_ACHIEVABLE_COVERAGE_AGENTCUT_RELEASE_BLOCKED"
line = queue["lines"]["E36"]
line["status"] = "FINALIZED_AT_ACHIEVABLE_COVERAGE_AGENTCUT_RELEASE_BLOCKED"
line["blocked_by"] = "CREDIT_RUNWAY_24_INSUFFICIENT_FOR_ANY_ADDITIONAL_COMPLIANT_VIDEO_ATTEMPT;ACCEPTED_TRANSCRIPT_35_OF_47;MOTION_29_OF_30_U08"
line["e36_paid_credits"] = "9976/10000 exact source-attributable episode net charged total; images704, videos9172, audio100; refunds3084 recorded separately; active tasks0; generation calls135; attributable headroom24"
line["running_or_pending_task_ids"] = []
line["local_pid"] = None
line["next_action"] = "Preserve accepted-only source map V7 and transcript audit V11. No additional compliant video attempt fits24 credits; AgentCut and release stay fail-closed."
line["latest_cl2x880_last_headroom_line26"] = "U14 line26 Fast6 task60f9250b Pay96/Refund0/Net96 produced MP4 shac3df2d71. Exact native Mandarin recall1.0, cadence/OCR, direct12-frame visible age17 Chenji performance, action/contact/direction/terminal, period and environment gates PASS; line26 admitted. Final accepted transcript35/47, motion29/30, source count44, episode9976/10000, headroom24, active0."
queue["updated_note_latest"] = line["latest_cl2x880_last_headroom_line26"]
write_json(queue_rel, queue)

dispatch_rel = "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
dispatch = read_json(dispatch_rel)
dispatch["generated_at"] = NOW
dispatch["source_cl2x"] = SOURCE_CL2X
dispatch["source_mailbox_sha256"] = MAILBOX_SHA
dispatch["blocked_by"] = "CREDIT_RUNWAY_24_INSUFFICIENT_FOR_ANY_ADDITIONAL_COMPLIANT_VIDEO_ATTEMPT;ACCEPTED_TRANSCRIPT_35_OF_47;MOTION_29_OF_30_U08"
dispatch["next_action"] = "Finalize at achievable accepted-only coverage35/47 and motion29/30. Preserve all PASS and FAIL evidence; AgentCut/release remain closed."
dispatch["accounting"].update({
    "current_source_attributable_credits": 9976,
    "headroom_before_dispatch": 120,
    "focused_video_projection_remaining": 96,
    "projected_total_after_success": 9976,
    "projected_headroom_after_success": 24
})
dispatch["execution"].update({
    "status": "FINALIZED_AT_ACHIEVABLE_COVERAGE_LINE26_ADMITTED_AGENTCUT_RELEASE_BLOCKED",
    "active_task_count": 0,
    "accepted_transcript_coverage": "35/47",
    "accepted_motion_coverage": "29/30"
})
dispatch.setdefault("subsequent_attempts", {})["last_headroom_line26"] = {
    "source_cl2x": SOURCE_CL2X,
    "task_key": "E36-U14-CANONICAL-L26-LAST-HEADROOM",
    "task_id": "60f9250b-7d6d-4669-a2b7-8ccb2d5e1337",
    "status": "PASS_ADMITTED_CANONICAL_LINE26",
    "receipt": receipt,
    "receipt_sha256": sha(receipt),
    "media": video,
    "media_sha256": sha(video),
    "direct_qa": direct_rel,
    "direct_qa_sha256": direct_sha,
    "credits": {"pay": 96, "refund": 0, "net": 96}
}
dispatch["subsequent_attempts"]["accepted_only_integrity"] = {
    "source_map": map7_rel,
    "source_map_sha256": sha(map7_rel),
    "transcript_audit": audit11_rel,
    "transcript_audit_sha256": sha(audit11_rel),
    "transcript_coverage": "35/47",
    "motion_coverage": "29/30"
}
write_json(dispatch_rel, dispatch)

print(json.dumps({
    "direct_qa": [direct_rel, direct_sha],
    "source_map_v7": [map7_rel, sha(map7_rel)],
    "transcript_v11": [audit11_rel, sha(audit11_rel)],
    "work_queue": [queue_rel, sha(queue_rel)],
    "dispatch": [dispatch_rel, sha(dispatch_rel)]
}, ensure_ascii=False))
