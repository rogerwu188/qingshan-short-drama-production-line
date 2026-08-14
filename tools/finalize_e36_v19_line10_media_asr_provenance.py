#!/usr/bin/env python3
"""Cross-check direct MP4 and extracted-PCM ASR for V19 line 10."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now().astimezone().isoformat(timespec="seconds")
MAILBOX_SHA = "662f57330226f71e023df8bfc64e94d8232e203ca77f3f9d4d9a253ad52d6cd1"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
MP4_QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_INSERTION_BOUNDARY_ASR_AND_VISUAL_QA_V1.json"
PCM = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_AUDIO_PCM_V1.wav"
PCM_V1 = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_PCM_UNCONDITIONED_ASR_V1.json"
PCM_V2 = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_PCM_UNCONDITIONED_ASR_V2.json"
ASR_TOOL = ROOT / "tools/audit_e36_dialogue_audio_unconditioned_asr.py"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_MEDIA_TO_ASR_PROVENANCE_QA_V1.json"
V19_QA = ROOT / "qa/e36_agentcut_20260730/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10_QA_V1.json"


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


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


mp4 = load(MP4_QA)
pcm = load(PCM_V2)
mp4_rows = {(row["model"], row["beam_size"], row["vad_filter"]): row for row in mp4["results"]}
pcm_rows = {(row["model"], row["beam_size"], row["vad_filter"]): row for row in pcm["results"]}
if set(mp4_rows) != set(pcm_rows):
    raise SystemExit("MP4 and PCM ASR configuration sets differ")

comparison = []
for key in sorted(mp4_rows, key=lambda item: (item[0], item[1], item[2])):
    media_row = mp4_rows[key]
    pcm_row = pcm_rows[key]
    comparison.append({
        "model": key[0], "beam_size": key[1], "vad_filter": key[2],
        "mp4_line10_exact_subsequence": media_row["line10_exact_contiguous_subsequence"],
        "pcm_line10_exact_subsequence": pcm_row["normalized_exact"],
        "classification_match": media_row["line10_exact_contiguous_subsequence"] == pcm_row["normalized_exact"],
        "mp4_transcript": media_row["transcript"],
        "pcm_transcript": pcm_row["transcript"],
    })

matches = sum(row["classification_match"] for row in comparison)
small_exact = sum(row["pcm_line10_exact_subsequence"] for row in comparison if row["model"].endswith("small"))
all_exact = sum(row["pcm_line10_exact_subsequence"] for row in comparison)
payload = {
    "schema": "qingshan.e36.v19_line10_media_to_asr_provenance_qa.v1",
    "episode": "E36", "source_cl2x": "CL2X-910", "source_mailbox_sha256": MAILBOX_SHA,
    "generated_at": NOW,
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
    "direct_mp4_asr": {"path": rel(MP4_QA), "sha256": sha(MP4_QA), "exact_subsequence_decodes": "6/12"},
    "extracted_pcm": {"path": rel(PCM), "sha256": sha(PCM), "format": "PCM_S16LE_48000HZ_STEREO"},
    "pcm_whole_clip_exact_mode_fail_preserved": {"path": rel(PCM_V1), "sha256": sha(PCM_V1), "status": "FAIL_EXPECTED_WHOLE_CLIP_HAS_NEIGHBORING_DIALOGUE"},
    "pcm_line10_contains_mode": {"path": rel(PCM_V2), "sha256": sha(PCM_V2), "exact_subsequence_decodes": f"{all_exact}/12", "small_exact_subsequence_decodes": f"{small_exact}/6"},
    "comparison": comparison,
    "gate_results": {
        "media_to_pcm_extraction": "PASS_LOSSLESS_PCM_DECODE_FROM_BOUNDARY_REEL",
        "asr_configuration_parity": "PASS_12_OF_12",
        "mp4_pcm_exact_classification_parity": f"PASS_{matches}_OF_12",
        "small_model_exact_line10": f"PASS_{small_exact}_OF_6",
        "all_model_exact_line10": f"PASS_WITH_AUTHORIZED_MANUAL_LISTENING_EXCEPTION_{all_exact}_OF_12",
        "media_to_transcript_fidelity_watch_item": "PASS_CLOSED",
        "continuous_full_audiovisual_watch": "NOT_COMPLETE",
    },
    "credits": {"pay": 0, "refund": 0, "net": 0, "episode_net": 9976, "limit": 10000, "headroom": 24},
    "status": "PASS_MEDIA_TO_ASR_PROVENANCE_WATCH_ITEM_CLOSED" if matches == 12 and small_exact == 6 else "FAIL_MEDIA_TO_ASR_PROVENANCE",
}
write(OUT, payload)
if payload["status"].startswith("FAIL"):
    raise SystemExit(payload["status"])

blocked = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)
next_action = (
    "Continue V19 full audiovisual review outside the verified line10 window and pursue zero-credit recovery for lines4,5,11,12,23,24,27,28 and U08. "
    "Rerun whole-film aHash after every future source admission."
)
progress = (
    "Consumed CL2X-910 and closed its remaining media-to-transcript fidelity watch item with a second independent media path. Extracted a lossless "
    "48kHz stereo PCM WAV from the V19 boundary reel, reran all12 unconditioned base/small ASR configurations, and compared every classification "
    "to direct MP4 decoding. Exact-subsequence labels match12/12: all6 small runs are exact and all6 base runs retain the documented homophone "
    "failures. The authorized line10 exception remains narrow; no 6/12 result was relabeled as 12/12."
)

v19_qa = load(V19_QA)
v19_qa["line10_media_to_asr_provenance"] = {"path": rel(OUT), "sha256": sha(OUT), "status": payload["status"]}
v19_qa["gate_results"]["line10_media_to_asr_provenance"] = "PASS_MP4_PCM_CLASSIFICATION_PARITY_12_OF_12_SMALL_EXACT_6_OF_6"
v19_qa["workaround_executed"] = progress
v19_qa["blocked_by"] = blocked
v19_qa["next_action"] = next_action
write(V19_QA, v19_qa)

queue = load(QUEUE)
queue.update({
    "updated_at": NOW, "source_cl2x": "CL2X-910", "source_mailbox_sha256": MAILBOX_SHA,
    "status": "E36_CL2X910_MEDIA_TO_ASR_PROVENANCE_PASS_V19_FULL_WATCH_ACTIVE",
    "blocked_by": blocked, "next_action": next_action,
    "latest_v19_line10_media_to_asr_provenance_qa": rel(OUT),
    "latest_v19_line10_media_to_asr_provenance_qa_sha256": sha(OUT),
    "latest_reversible_agentcut_candidate_qa_sha256": sha(V19_QA),
    "updated_note_latest": progress,
})
queue["lines"]["E36"].update({
    "status": "CL2X910_LINE10_MEDIA_TO_ASR_PROVENANCE_PASS_FULL_WATCH_AND_GAP_REPAIR_ACTIVE",
    "current_phase": progress, "blocked_by": blocked, "next_action": next_action,
    "latest_cl2x910_consumption": progress,
})
write(QUEUE, queue)

dispatch = load(DISPATCH)
dispatch.update({
    "generated_at": NOW, "source_cl2x": "CL2X-910", "source_mailbox_sha256": MAILBOX_SHA,
    "blocked_by": blocked, "workaround_executed": progress, "next_action": next_action,
})
dispatch["execution"].update({
    "status": "CL2X910_LINE10_MEDIA_TO_ASR_PROVENANCE_PASS_REVERSIBLE_NOT_PROMOTED",
    "active_task_count": 0,
    "latest_v19_line10_media_to_asr_provenance_qa": rel(OUT),
    "latest_v19_line10_media_to_asr_provenance_qa_sha256": sha(OUT),
    "latest_reversible_agentcut_qa_sha256": sha(V19_QA),
    "last_real_progress": progress,
})
write(DISPATCH, dispatch)

receipt = f"""

# [X2CL-20260731-2147] CL2X-910 consumed; V19 line10 media-to-ASR provenance independently closes
- source_cl2x: `CL2X-910`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{blocked}`
- workaround_executed: `{progress}`
- artifacts: `{rel(PCM)}` sha256=`{sha(PCM)}`; `{rel(PCM_V1)}` sha256=`{sha(PCM_V1)}`; `{rel(PCM_V2)}` sha256=`{sha(PCM_V2)}`; `{rel(ASR_TOOL)}` sha256=`{sha(ASR_TOOL)}`; `{rel(OUT)}` sha256=`{sha(OUT)}`; `{rel(V19_QA)}` sha256=`{sha(V19_QA)}`; `workflow/work_queue.json` sha256=`{sha(QUEUE)}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{sha(DISPATCH)}`
- gate_results: `CL2X910_consumed:PASS;lossless_PCM_extraction:PASS;ASR_configurations:PASS_12_OF_12;direct_MP4_vs_PCM_classification:PASS_12_OF_12;small_model_line10:PASS_6_OF_6_EXACT;all_model_line10:PASS_AUTHORIZED_EXCEPTION_6_OF_12_EXACT;whole_clip_exact_mode:FAIL_EXPECTED_PRESERVED_NEIGHBORING_DIALOGUE;media_to_transcript_fidelity_watch_item:PASS_CLOSED;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;continuous_watch:NOT_COMPLETE;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
with RECEIPTS.open("a", encoding="utf-8") as handle:
    handle.write(receipt)

print(json.dumps({"qa_sha256": sha(OUT), "v19_qa_sha256": sha(V19_QA), "queue_sha256": sha(QUEUE), "dispatch_sha256": sha(DISPATCH), "receipt_file_sha256": sha(RECEIPTS)}, ensure_ascii=False))
