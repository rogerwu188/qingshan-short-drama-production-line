#!/usr/bin/env python3
"""Record V8 harvest/QA, line 22 salvage, V8 AgentCut, and V9 dispatch."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
MAILBOX = ROOT / "workflow/CODEX_TO_CLAUDE.md"
QA = ROOT / "qa/e37_video_20260803/v8_dialogue_identity_repairs_v1"
SUMMARY = QA / "E37_V8_HARVEST_DIRECT_QA_LINE22_ZERO_CREDIT_ADMISSION_V1.json"
V8_FINAL = ROOT / "exports/e37/agentcut_v8_line22_textfree_native_20260803/E37_AGENTCUT_V8_LINE22_TEXTFREE_NATIVE_NOT_FINAL.mp4"
V9 = ROOT / "workflow/tasks/E37_V9_FAILED_ONLY_PROMPT_REPAIR_SUBMIT_V1_20260803.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
v9 = read(V9)
active_ids = [row["task_id"] for row in v9["tasks"]]
crop = ROOT / "working_assets/e37_video_20260803/v8_dialogue_identity_repairs_v1/zero_credit_salvage/E37-L022-V8-CROP-A-360x640-TOP.mp4"
summary = {
    "schema": "qingshan.e37.v8_harvest_direct_qa_line22_admission.v1",
    "episode": "E37", "recorded_at_utc": now, "status": "PASS_LINE22_ADMITTED_LINES6_19_FAIL_PRESERVED",
    "source_cl2x": "CL2X-936",
    "canonical": {
        "script_sha256": "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
        "manifest_sha256": "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
    },
    "v8_results": {
        "line6": {"status": "FAIL_PRESERVED", "failures": ["NATIVE_DIALOGUE_REPLACED_BY_YOYO_PLATFORM_INTRO", "SHORT_FREEZE", "CHENJI_AGE_IDENTITY_DRIFT"]},
        "line19": {"status": "FAIL_PRESERVED", "failures": ["NATIVE_DIALOGUE_RECALL_0_GIBBERISH", "BURNED_IN_SUBTITLES"]},
        "line22": {"status": "PASS_ACCEPTED_ZERO_CREDIT_TEXTFREE_CROP", "raw_failure": "BURNED_IN_SUBTITLES", "repair": "FIXED_CENTER_TOP_CROP_360x640_SCALE_720x1280_NO_CAMERA_MOTION", "accepted_source": rel(crop), "accepted_source_sha256": sha(crop)},
    },
    "line22_gates": {
        "native_dialogue": "PASS_RECALL1_0_EXACT", "visible_mouth_breath_expression": "PASS_DIRECT_2FPS_FULL_DURATION",
        "canonical_yunyang_identity": "PASS_DIRECT_17YO_MALE_PRESENTING_BLACK_PERIOD_ROBES", "cadence": "PASS",
        "ocr": "PASS_12_SAMPLES_ZERO_RECOGNITIONS", "camera_sway": "PASS_NONE_FIXED_CROP", "new_credits": 0,
    },
    "agentcut_v8": {
        "candidate": rel(V8_FINAL), "candidate_sha256": sha(V8_FINAL), "duration_seconds": 179.085,
        "strict_validate": "PASS_VALID_ONE_AUDIO_PEAK_WARNING_ONLY", "compile": "PASS", "render": "PASS",
        "full_decode": "PASS_ZERO_ERRORS", "full_cut_fps1_adjacent_ahash": "PASS_13_483_PERCENT",
        "frame_cadence": "PASS_ZERO_FAILURES", "subtitles": "PASS_31_OF31", "nalu_outro": "PASS_PRESENT",
        "release_status": "NOT_FINAL_LINES6_19_AND_FULL_NATIVE_SPEED_WATCH_REMAIN",
    },
    "credits": {"v8_pay": 340, "v8_refund": 0, "v8_net": 340, "cumulative_pay": 9193, "cumulative_refund": 1433, "cumulative_net": 7760, "episode_cap": 10000, "headroom_before_v9": 2240},
    "v9_failed_only_workaround": {"submit_receipt": rel(V9), "submit_receipt_sha256": sha(V9), "active_task_ids": active_ids, "maximum_projected_new_net": 220, "maximum_projected_episode_net": 7980, "minimum_projected_headroom": 2020},
}
write(SUMMARY, summary)

queue = read(QUEUE)
queue["updated_at"] = now
queue["status"] = "E37_V8_LINE22_ADMITTED_AGENTCUT_RENDERED_V9_LINES6_19_RUNNING"
queue["real_active_handle_count"] = 2
queue["blocked_by"] = "V9_LINES6_19_FAILED_ONLY_REMOTE_GENERATION_RUNNING_AND_V8_FULL_NATIVE_SPEED_WATCH_PENDING"
queue["next_action"] = "Poll and harvest V9 lines6/19, reconcile exact charges, run failed-only hard QA, then rebuild from V8 only on a genuine pass and complete full native-speed watch before public replacement."
queue["updated_note_latest"] = "V8 all3 harvested. Lines6/19 fail preserved; line22 exact native dialogue and canonical Yunyang visual were salvaged with a zero-credit fixed top crop that removed provider-burned subtitles without camera motion. V8 AgentCut rendered179.085s and passed strict validation, compile/render, full decode, full-cut aHash13.483% and cadence; subtitles31/31 and NALU outro remain. Materially changed failure-conditioned V9 lines6/19 submitted concurrently; active2."
line = queue["lines"]["E37"]
line["status"] = "E37_V8_LINE22_ACCEPTED_V9_LINES6_19_RUNNING"
line["current_phase"] = queue["updated_note_latest"]
line["blocked_by"] = queue["blocked_by"]
line["running_or_pending_task_ids"] = active_ids
line["next_action"] = queue["next_action"]
line["latest_v8_harvest_direct_qa_line22_admission"] = rel(SUMMARY)
line["latest_v8_harvest_direct_qa_line22_admission_sha256"] = sha(SUMMARY)
line["latest_replacement_v8_candidate"] = rel(V8_FINAL)
line["latest_replacement_v8_candidate_sha256"] = sha(V8_FINAL)
line["latest_v8_dialogue_identity_repair_harvest"] = "qa/e37_video_20260803/v8_dialogue_identity_repairs_v1/E37_V8_DIALOGUE_IDENTITY_REPAIR_HARVEST_V1.json"
line["latest_v8_credit_reconciliation"] = "workflow/credit_reports/E37_V8_DIALOGUE_IDENTITY_REPAIR_EXACT_CREDITS_20260803.json"
line["latest_v9_failed_only_prompt_repair_submit"] = rel(V9)
line["e37_source_attributable_credits"] = "settled Pay9193/Refund1433/Net7760 of10000; V9 maximum projected new220, projected Net7980, minimum headroom2020; active2"
write(QUEUE, queue)

dispatch = read(DISPATCH)
dispatch["updated_at"] = now
dispatch["recorded_at"] = now
dispatch["status"] = queue["status"]
dispatch["active_task_ids"] = active_ids
dispatch["real_active_handle_count"] = 2
dispatch["blocked_by"] = queue["blocked_by"]
dispatch["next_action"] = queue["next_action"]
dispatch["credits"] = {"pay": 9193, "refund": 1433, "net": 7760, "episode_cap": 10000, "headroom": 2240, "v9_projected_max_net": 7980, "v9_projected_min_headroom": 2020}
dispatch["latest_v8_harvest_direct_qa_line22_admission"] = rel(SUMMARY)
dispatch["latest_replacement_v8_candidate"] = rel(V8_FINAL)
dispatch["latest_replacement_v8_candidate_sha256"] = sha(V8_FINAL)
dispatch["latest_v9_failed_only_prompt_repair_submit"] = rel(V9)
dispatch["workaround_executed"] = "Harvested/QAed all V8 outputs; admitted only line22 after a fixed no-sway text-removal crop; rendered and objectively QAed V8; submitted two failure-conditioned materially changed V9 tasks for remaining lines6/19."
write(DISPATCH, dispatch)

artifacts = [
    SUMMARY,
    QA / "E37_V8_DIALOGUE_IDENTITY_REPAIR_HARVEST_V1.json",
    ROOT / "workflow/credit_reports/E37_V8_DIALOGUE_IDENTITY_REPAIR_EXACT_CREDITS_20260803.json",
    crop,
    QA / "zero_credit_salvage/E37-L022-V8-CROP-A-360x640-NATIVE-DIALOGUE.json",
    QA / "zero_credit_salvage/E37-L022-V8-CROP-A-360x640-OCR.json",
    QA / "zero_credit_salvage/E37-L022-V8-CROP-A-360x640-CADENCE.json",
    V8_FINAL,
    ROOT / "qa/e37_agentcut_20260803/v8_line22_textfree_native/E37_V8_FULL_CUT_FPS1_ADJACENT_AHASH.json",
    ROOT / "qa/e37_agentcut_20260803/v8_line22_textfree_native/E37_V8_FULL_CUT_FRAME_CADENCE.json",
    V9,
]
artifact_text = "; ".join(f"`{rel(path)}` sha256=`{sha(path)}`" for path in artifacts)
entry = f"""

X2CL-20260803-1648-E37-V8-HARVEST-LINE22-SALVAGED-AGENTCUT-V8-PASS-V9-TWO-RUNNING
- source_cl2x: CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T162944Z
- blocked_by: V9_LINES6_19_FAILED_ONLY_REMOTE_GENERATION_RUNNING_AND_V8_FULL_NATIVE_SPEED_WATCH_PENDING
- workaround_executed: Harvested all three V8 tasks and ran native-dialogue, cadence, OCR and direct contact-sheet review. Preserved line6 FAIL for a provider YoYo intro replacing the canonical sentence plus a short freeze and older Chenji drift; preserved line19 FAIL for gibberish recall0 plus burned-in subtitles. Line22 passed exact native dialogue and canonical 17-year-old male-presenting Yunyang identity but raw burned-in subtitles; rendered two zero-credit fixed top crops with no camera motion, independently ran OCR/cadence on both, directly reviewed both, and admitted crop A only after OCR zero recognitions, cadence PASS and visible-mouth PASS. Built V8 AgentCut with the admitted line22 picture/audio window; strict validate, compile/render179.085s, full decode, full-cut fps1 adjacent-aHash13.483% and cadence all pass, with31/31 subtitles and NALU outro retained. Reconciled V8 exact Pay340/Refund0/Net340. Because active returned0 while production remains incomplete, precompiled failure-conditioned materially changed V9 prompts and submitted line6/19 concurrently; no unchanged replay, camera sway, platform mutation, S3 relay or cloud-agent messaging occurred.
- artifacts: {artifact_text}
- gate_results: canonical_script=PASS_EXACT_SHA_07a63a0c;canonical_manifest=PASS_EXACT_SHA_9082f9d3;V8_harvest=PASS_3_OF3;V8_line6=FAIL_YOYO_INTRO_FREEZE_IDENTITY_DRIFT;V8_line19=FAIL_DIALOGUE_RECALL0_BURNED_SUBTITLES;V8_line22_raw=FAIL_BURNED_SUBTITLES;V8_line22_cropA=PASS_DIALOGUE1_IDENTITY_VISIBLE_MOUTH_OCR0_CADENCE_NO_SWAY;V8_agentcut_strict_validate=PASS_ONE_AUDIO_WARNING;V8_compile_render=PASS_179_085S;V8_full_decode=PASS;V8_full_cut_ahash=PASS_13_483_PERCENT;V8_cadence=PASS;V8_subtitles=PASS_31_OF31;V8_nalu_outro=PASS;V8_release=HOLD_LINES6_19_AND_FULL_NATIVE_SPEED_WATCH;V9_submit=PASS_2_OF2_FRESH_IDS;platform_mutation=NONE;s3_relay=NONE;automation_e37=PASS_CONTINUES
- task_ids: V9-L006={active_ids[0]}@{v9['tasks'][0]['submitted_at_utc']};V9-L019={active_ids[1]}@{v9['tasks'][1]['submitted_at_utc']}
- credits: V8 exact Pay340/Refund0/Net340; cumulative settled E37 Pay9193/Refund1433/Net7760 of10000; V9 pending exact statements, maximum projected new Net220 and episode Net7980; minimum projected headroom2020; active2
- next_action: Poll and harvest both V9 task IDs, reconcile exact charges, run failed-only canonical dialogue/identity/mouth/cadence/OCR/direct audiovisual QA, preserve FAIL without replay, then rebuild from V8 only on genuine passes and complete full native-speed viewing before replacing public V1. Keep automation e37 active.
"""
with MAILBOX.open("a", encoding="utf-8") as handle:
    handle.write(entry)

print(json.dumps({"summary": rel(SUMMARY), "summary_sha256": sha(SUMMARY), "queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "active_task_ids": active_ids}, ensure_ascii=False))
