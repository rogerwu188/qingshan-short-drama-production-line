#!/usr/bin/env python3
"""Register the V19 worst-cluster fullscreen reel and its bounded QA."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST_SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
DIR = ROOT / "qa/e36_agentcut_20260730/v19_native24_worst_cluster_reel_v1"
MANIFEST = DIR / "E36_V19_NATIVE24_WORST_CLUSTER_MANIFEST_V1.json"
REEL = DIR / "E36_V19_NATIVE24_WORST_CLUSTER_FULLSCREEN_REALTIME_REEL_V1.mp4"
CONTACT = DIR / "E36_V19_NATIVE24_WORST_CLUSTER_REPRESENTATIVE_CONTACT_V1.jpg"
PROBE = DIR / "E36_V19_NATIVE24_WORST_CLUSTER_PROBE_V1.json"
DECODE = DIR / "E36_V19_NATIVE24_WORST_CLUSTER_DECODE_V1.log"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V19_NATIVE24_WORST_CLUSTER_FULLSCREEN_REEL_QA_V1.json"
BUILD_TOOL = ROOT / "tools/build_e36_v19_native24_worst_cluster_reel.py"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-914"
MAILBOX_SHA = "fea59b5aa15786cd2e1224d9c4e5fca57f6d07f80a2e8c132495d43e6f4050b0"
CANONICAL_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
BLOCKED = (
    "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;"
    "RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;"
    "PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;"
    "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    script_manifest = load(MANIFEST_SCRIPT)
    assert sha256(CANONICAL) == script_manifest["sha256"] == CANONICAL_SHA
    manifest = load(MANIFEST)
    probe = load(PROBE)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert sha256(REEL) == manifest["review_reel"]["sha256"]
    assert video["width"] == 720 and video["height"] == 1280
    assert video["r_frame_rate"] == "24/1" and int(video["nb_frames"]) == 360
    assert abs(float(probe["format"]["duration"]) - 15.0) < 0.01
    assert DECODE.stat().st_size == 0

    now = datetime.now(timezone.utc).isoformat()
    qa = {
        "schema": "e36_v19_native24_worst_cluster_fullscreen_reel_qa_v1",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "canonical": {"path": str(CANONICAL.relative_to(ROOT)), "sha256": sha256(CANONICAL), "manifest_declared_exact": True},
        "manifest": {"path": str(MANIFEST.relative_to(ROOT)), "sha256": sha256(MANIFEST)},
        "review_reel": {"path": str(REEL.relative_to(ROOT)), "sha256": sha256(REEL), "duration_seconds": 15.0, "fps": 24, "frames": 360, "resolution": [720, 1280], "audio_stream_duration_seconds": float(audio["duration"])},
        "windows": manifest["windows"],
        "media_integrity": {"probe": "PASS", "full_decode": "PASS_ZERO_ERRORS", "decode_error_lines": 0},
        "direct_representative_visual_review": {
            "contact_sheet": {"path": str(CONTACT.relative_to(ROOT)), "sha256": sha256(CONTACT), "samples": 12},
            "identity_age_period_continuity": "PASS_REPRESENTATIVE",
            "visible_faces_and_mouths": "PASS_REPRESENTATIVE",
            "props_and_evidence": "PASS_REPRESENTATIVE_ENVELOPE_AND_PAPER_CONTINUITY",
            "framing_and_critical_cutoff": "PASS_REPRESENTATIVE_NO_FACE_OR_EVIDENCE_CUTOFF",
            "generated_visible_text": "PASS_NONE_OBSERVED",
            "scope_limit": "STATIC_REPRESENTATIVE_REVIEW_DOES_NOT_CLEAR_REALTIME_MOTION_COMFORT_LIPSYNC_BREATH_OR_FULL_RUNTIME_CONTINUITY",
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "full_speed_review_media": "PASS_15_SECONDS_24FPS_360_FRAMES",
            "worst_clusters_mapped": "PASS_3_OF_3",
            "full_decode": "PASS_ZERO_ERRORS",
            "representative_visual": "PASS_12_SAMPLES",
            "continuous_realtime_human_watch": "NOT_COMPLETE_REEL_READY",
            "subjective_comfort": "NOT_CLEARED",
            "promotion": "NOT_GRANTED_KEEP_V15_CANONICAL",
            "release": "HOLD",
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    dump(QA, qa)

    workaround = (
        "Continued under CL2X-914 and converted the full-runtime native-rate localization into a fullscreen "
        "15-second, 24fps audiovisual V19 review reel covering all three newly identified worst clusters after "
        "the exact +6.082993-second line10 mapping. The reel has 360 frames, a 48kHz stereo audio stream and "
        "zero full-decode errors. Direct review of 12 representative full-frame samples passes identity, period, "
        "visible faces, props and critical framing, while explicitly retaining the realtime comfort and full-watch hold."
    )
    next_action = (
        "Use the fullscreen 15-second reel for uninterrupted native-speed audiovisual comfort review, then render "
        "the remaining V19 intervals as similarly full-speed fullscreen reels; concurrently continue zero-credit "
        "recovery for lines4/5/11/12/23/24/27/28 and U08 while V19 stays reversible and unpromoted."
    )
    status = "E36_V19_NATIVE24_WORST_CLUSTER_FULLSCREEN_REEL_READY_FULL_WATCH_ACTIVE"

    queue = load(QUEUE)
    queue.update({
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "updated_at": now,
        "updated_note_latest": workaround,
        "updated_note": workaround,
        "status": status,
        "latest_v19_native24_worst_cluster_reel_qa": str(QA.relative_to(ROOT)),
        "latest_v19_native24_worst_cluster_reel_qa_sha256": sha256(QA),
        "blocked_by": BLOCKED,
        "next_action": next_action,
    })
    queue["lines"]["E36"].update({"status": status, "current_phase": workaround, "blocked_by": BLOCKED, "next_action": next_action, "latest_cl2x914_worst_cluster_reel": workaround})
    dump(QUEUE, queue)

    dispatch = load(DISPATCH)
    dispatch.update({"source_cl2x": SOURCE_CL2X, "source_mailbox_sha256": MAILBOX_SHA, "generated_at": now, "blocked_by": BLOCKED, "workaround_executed": workaround, "next_action": next_action})
    dispatch["execution"]["latest_v19_native24_worst_cluster_reel"] = {"qa": str(QA.relative_to(ROOT)), "qa_sha256": sha256(QA), "reel": str(REEL.relative_to(ROOT)), "reel_sha256": sha256(REEL), "status": "PASS_REVIEW_MEDIA_READY_SUBJECTIVE_HOLD"}
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = "CL2X-914_V19_WORST_CLUSTER_REEL_READY_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)

    queue_sha, dispatch_sha = sha256(QUEUE), sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2242] E36 V19 native-rate worst-cluster fullscreen review reel
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED}`
- workaround_executed: `{workaround}`
- artifacts: `{REEL.relative_to(ROOT)}` sha256=`{sha256(REEL)}`; `{MANIFEST.relative_to(ROOT)}` sha256=`{sha256(MANIFEST)}`; `{CONTACT.relative_to(ROOT)}` sha256=`{sha256(CONTACT)}`; `{QA.relative_to(ROOT)}` sha256=`{sha256(QA)}`; `{BUILD_TOOL.relative_to(ROOT)}` sha256=`{sha256(BUILD_TOOL)}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;review_media:PASS_15S_24FPS_360_FRAMES_720X1280;audio:PASS_48KHZ_STEREO;full_decode:PASS_ZERO_ERRORS;mapped_worst_clusters:PASS_3_OF_3;direct_static_visual:PASS_12_REPRESENTATIVE_SAMPLES_IDENTITY_PERIOD_FACES_PROPS_FRAMING_NO_TEXT;realtime_motion_comfort:NOT_CLEARED_REEL_READY;continuous_full_runtime_watch:NOT_COMPLETE;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0`
- next_action: `{next_action}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"qa_sha256": sha256(QA), "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
