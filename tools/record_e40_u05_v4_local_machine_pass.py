#!/usr/bin/env python3
"""Record U05 V4 exact-audio/render progress and preserve active QA continuity."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WQ = ROOT / "workflow/work_queue.json"
SCHEDULER = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
X2CL = ROOT / "workflow/CODEX_TO_CLAUDE.md"
TASK_ID = "E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIALOGUE-PERFORMANCE-PRECOMPILE-QA"
VIDEO = ROOT / "working_assets/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIA004.mp4"
MACHINE_QA = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
CONTACT = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/contact_sheet.png"
AUDIO_QA = ROOT / "qa/e40_production_20260814/u05_v4_kokoro_exact_audio_candidates_v1/E40_U05_V4_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u05_v4_kokoro_rights_clearance_v1/E40_U05_V4_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
TTS_TX = ROOT / "workflow/tasks/giggle_audio_submit_transactions/E40/E40-U05-DIA004-EXACTLY-ONE-TTS-V1.json"
HUMAN = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1/E40_U05_V4_LOCAL_AUTHORITY_VISUAL_REVIEW_V1.json"


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    for path in (VIDEO, MACHINE_QA, CONTACT, AUDIO_QA, RIGHTS, TTS_TX):
        if not path.is_file():
            raise SystemExit(f"FAIL_MISSING:{path}")
    machine = json.loads(MACHINE_QA.read_text(encoding="utf-8"))
    audio = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    tx = json.loads(TTS_TX.read_text(encoding="utf-8"))
    if machine.get("status") != "PASS_MACHINE_HUMAN_PERFORMANCE_QA_PENDING":
        raise SystemExit("FAIL_MACHINE_QA_NOT_PASS")
    if audio.get("status") != "PASS_MACHINE_SELECTION_HUMAN_LISTEN_PENDING" or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_AUDIO_OR_RIGHTS_GATE")
    if tx.get("task_id") != "027c0fe5-d1be-4941-b074-22dd8c8e50c2" or (tx.get("credit") or {}).get("net_charged_credits") != 2:
        raise SystemExit("FAIL_TTS_TRANSACTION_CLASSIFICATION")
    moment = now()
    human = {
        "schema": "qingshan.e40.u05.v4.local_authority.visual_review.v1",
        "status": "PASS_CONTACT_SHEET_GEOMETRY_IDENTITY_PAGE_HAND_AND_MOUTH_ARTIFACT_REVIEW_DYNAMIC_LIPSYNC_LISTEN_PENDING",
        "reviewed_at": stamp(moment),
        "reviewer": "codex-root-original-resolution-contact-sheet",
        "video_path": str(VIDEO.relative_to(ROOT)),
        "video_sha256": sha(VIDEO),
        "contact_sheet_path": str(CONTACT.relative_to(ROOT)),
        "contact_sheet_sha256": sha(CONTACT),
        "checks": {
            "chenji_single_identity_stable": "PASS",
            "white_robe_hall_continuity": "PASS",
            "two_blank_pages_and_hand_contact_stable": "PASS",
            "mouth_region_no_visible_warp_or_tearing": "PASS",
            "camera_motion_bounded": "PASS",
            "frame0_authority_exact": "PASS_MACHINE_PIXEL_EXACT",
            "dynamic_lipsync_and_voice_listen": "PENDING_DEDICATED_TEMPORAL_REVIEW"
        },
        "admission": "CLOSED_UNTIL_DYNAMIC_LIPSYNC_AND_VOICE_LISTEN_PASS"
    }
    atomic_json(HUMAN, human)

    work = json.loads(WQ.read_text(encoding="utf-8"))
    credits = work["e40_credits"]
    credits.update({
        "gross_pay": 1643,
        "refund": 128,
        "net": 1515,
        "remaining": 8485,
        "audio_pay": 6,
        "status": "AUTHORITATIVE_TOTALS_1643_128_1515_U05_DIA004_TTS_PAY2_RELEASE_BLOCKED_LOCAL_KOKORO_REPLACEMENT",
        "totals_fresh_through": "U05_DIA004_TTS_TASK_ID_027c0fe5-d1be-4941-b074-22dd8c8e50c2_TERMINAL_PAY2"
    })
    work["latest_e40_u05_v4_local_authority_repair"] = {
        "status": "PASS_MACHINE_VISUAL_CONTACT_REVIEW_DYNAMIC_LIPSYNC_AND_VOICE_LISTEN_QA_ACTIVE",
        "failed_tts_transaction": str(TTS_TX.relative_to(ROOT)),
        "failed_tts_transaction_sha256": sha(TTS_TX),
        "failed_tts_task_id": tx["task_id"],
        "failed_tts_pay": 2,
        "failed_tts_refund": 0,
        "failed_tts_failure": tx["failure"],
        "local_audio_qa": str(AUDIO_QA.relative_to(ROOT)),
        "local_audio_qa_sha256": sha(AUDIO_QA),
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": sha(RIGHTS),
        "selected_audio": audio["selected"]["normalized_path"],
        "selected_audio_sha256": audio["selected"]["normalized_sha256"],
        "video": str(VIDEO.relative_to(ROOT)),
        "video_sha256": sha(VIDEO),
        "machine_qa": str(MACHINE_QA.relative_to(ROOT)),
        "machine_qa_sha256": sha(MACHINE_QA),
        "visual_review": str(HUMAN.relative_to(ROOT)),
        "visual_review_sha256": sha(HUMAN),
        "next_action": "Run dedicated temporal lip-sync and voice-listen QA; if PASS, persist U05 unit admission and dispatch U06 production successor."
    }
    atomic_json(WQ, work)

    scheduler = json.loads(SCHEDULER.read_text(encoding="utf-8"))
    matches = [row for row in scheduler["tasks"] if row.get("task_id") == TASK_ID]
    if len(matches) != 1:
        raise SystemExit("FAIL_SCHEDULER_TASK_NOT_UNIQUE")
    task = matches[0]
    task.update({
        "state": "QA",
        "wait_scope": "NONE_ACTIVE_QA",
        "zero_cost": False,
        "maximum_new_submissions": 0,
        "authorization": False,
        "provider_post_allowed": False,
        "provider_query_allowed": False,
        "download_allowed": False,
        "provider_calls": 1,
        "transactions": 1,
        "credits": 2,
        "blocked_by": "DYNAMIC_LIPSYNC_AND_VOICE_LISTEN_QA_PENDING",
        "progress": "PAID_CLONE_TTS_PAY2_RELEASE_BLOCKED_QUARANTINED_LOCAL_KOKORO_EXACT_AUDIO_SELECTED_V4_PIXEL_EXACT_FRAME0_ASR1P0_MACHINE_PASS_CONTACT_VISUAL_PASS",
        "last_progress_at": stamp(moment),
        "next_action": "Run dedicated temporal lip-sync and voice-listen QA on the local V4 candidate; if PASS, persist U05 unit admission and dispatch U06 successor without a global barrier.",
        "lease_expires_at": stamp(moment + timedelta(hours=2)),
        "next_due_at": stamp(moment + timedelta(minutes=10)),
        "executor_acknowledged_at": stamp(moment),
        "executor_next_wakeup_at": stamp(moment + timedelta(minutes=10)),
        "evidence_ref": str(MACHINE_QA.relative_to(ROOT)),
        "evidence_sha256": sha(MACHINE_QA),
        "output_ref": str(VIDEO.relative_to(ROOT)),
        "output_sha256": sha(VIDEO),
        "failed_tts_task_id": tx["task_id"],
        "failed_tts_transaction_path": str(TTS_TX.relative_to(ROOT)),
        "failed_tts_transaction_sha256": sha(TTS_TX),
        "visual_review_ref": str(HUMAN.relative_to(ROOT)),
        "visual_review_sha256": sha(HUMAN)
    })
    atomic_json(SCHEDULER, scheduler)

    entry = f"""

## E40 heartbeat {stamp(moment)} — U05 V4 local authority exact-dialogue candidate rendered; temporal QA active

- Canonical/script SHA remains `140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b`; manifest SHA remains `773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1`.
- Persisted one U05 DIA-004 TTS intent before POST and immediately bound task_id `{tx['task_id']}`. Authoritative ledger classified Pay=`2`, Refund=`0`, Net=`2`; E40 authoritative totals are now gross=`1643`, refund=`128`, net=`1515`, remaining=`8485` under cap=`10000`. The task returned exact ASR=`1.0`, duration=`3.831313s`, LUFS=`-15.6`, peak=`-1.1 dBFS`, but provider commercial metadata was `present=false`, `releaseBlocked=true`; it is quarantined, PF memory persisted, and unchanged replay is forbidden.
- Materially changed to pinned local Apache-2.0 Kokoro revision `01e7505bd6a7a2ac4975463114c3a7650a9f7218`, built-in Chinese male voices, provider posts=`0`, credits=`0`, and no failed provider audio reuse. Six candidates were generated; four passed exact ASR/audio gates. Deterministic selection: `zm_009`, speed=`1.15`, duration=`3.5s`, exact ASR=`1.0`, LUFS=`-18.2`, peak=`-2.0 dBFS`, WAV SHA=`{audio['selected']['normalized_sha256']}`. Rights evidence `{RIGHTS.relative_to(ROOT)}` SHA=`{sha(RIGHTS)}`.
- Rendered local authority-only U05 V4 `{VIDEO.relative_to(ROOT)}` SHA=`{sha(VIDEO)}` from the admitted PNG SHA=`4f5205fa8a001b1943a322ee146ec19f4a62c530a9b1286bf921e327c2dbcc7e`. Decoded frame0 is pixel-exact (MAE=`0.0`); final mux ASR=`1.0`; 720x1280, 24fps, 4.0s, H.264 RGB lossless video + AAC audio. Machine QA `{MACHINE_QA.relative_to(ROOT)}` SHA=`{sha(MACHINE_QA)}` passed. Original-resolution contact sheet visual review `{HUMAN.relative_to(ROOT)}` SHA=`{sha(HUMAN)}` passed identity, geometry, two blank pages/hand contact, bounded camera and no mouth tearing.
- U05 V4 remains active `QA`, not terminal: unique next action is dedicated temporal lip-sync and voice-listen review. On PASS, persist U05 unit admission and dispatch U06 production successor. No E38/E39 mutation, no release, no duplicate paid submission.
"""
    with X2CL.open("a", encoding="utf-8") as stream:
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "PASS_RECORDED_ACTIVE_QA", "video_sha256": sha(VIDEO), "human_sha256": sha(HUMAN), "credits": work["e40_credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
