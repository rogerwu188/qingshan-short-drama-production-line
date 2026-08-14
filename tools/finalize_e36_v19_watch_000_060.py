#!/usr/bin/env python3
"""Record the bounded V19 0-60s audiovisual review without promoting V19."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA_DIR = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_watch_000_060_v1"
QA_PATH = ROOT / "qa/e36_agentcut_20260730/E36_V19_WATCH_000_060_BOUNDED_QA_V1.json"
SOURCE_MAP_PATH = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
QUEUE_PATH = ROOT / "workflow/work_queue.json"
DISPATCH_PATH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPT_PATH = ROOT / "workflow/CODEX_TO_CLAUDE.md"

SOURCE_CL2X = "CL2X-910"
MAILBOX_SHA = "662f57330226f71e023df8bfc64e94d8232e203ca77f3f9d4d9a253ad52d6cd1"
BLOCKED_BY = (
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


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact(name: str) -> dict:
    path = QA_DIR / name
    return {"path": rel(path), "sha256": sha256(path)}


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    source_map = load(SOURCE_MAP_PATH)
    intersecting = []
    for source in source_map["sources"]:
        start, end = source["accepted_only_timeline_seconds"]
        if start < 60.0 and end > 0.0:
            intersecting.append(
                {
                    "source_id": source["source_id"],
                    "canonical_units": source["canonical_units"],
                    "timeline_seconds": [start, end],
                    "media_sha256": source["media_sha256"],
                    "qa_sha256": source["qa_sha256"],
                }
            )

    artifacts = {
        "review_reel": artifact("E36_V19_WATCH_000_060_REVIEW_REEL_V1.mp4"),
        "contact_sheet": artifact("E36_V19_WATCH_000_060_CONTACT_SHEET_V1.jpg"),
        "waveform": artifact("E36_V19_WATCH_000_060_WAVEFORM_V1.png"),
        "probe": artifact("E36_V19_WATCH_000_060_PROBE_V1.json"),
        "full_decode_log": artifact("E36_V19_WATCH_000_060_FULL_DECODE_V1.log"),
        "silence_log": artifact("E36_V19_WATCH_000_060_SILENCEDETECT_V1.log"),
        "black_freeze_log": artifact("E36_V19_WATCH_000_060_BLACK_FREEZE_V1.log"),
    }
    probe = load(QA_DIR / "E36_V19_WATCH_000_060_PROBE_V1.json")
    streams = {s["codec_type"]: s for s in probe["streams"]}

    qa = {
        "schema": "e36_v19_watch_000_060_bounded_qa_v1",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "episode": "E36",
        "candidate": {
            "path": "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4",
            "sha256": "36faf0d5ce91b1b3aa938a7183c4bc9e6a0a034c3886a019a0ebbab3da029dde",
            "promotion": "REVERSIBLE_NOT_PROMOTED",
        },
        "window_seconds": [0.0, 60.0],
        "window_fraction_of_candidate": round(60.0 / 288.911, 6),
        "intersecting_accepted_sources": intersecting,
        "artifacts": artifacts,
        "media_observations": {
            "duration_seconds": float(probe["format"]["duration"]),
            "video": {
                "codec": streams["video"]["codec_name"],
                "width": streams["video"]["width"],
                "height": streams["video"]["height"],
                "frames": int(streams["video"]["nb_frames"]),
            },
            "audio": {
                "codec": streams["audio"]["codec_name"],
                "sample_rate": int(streams["audio"]["sample_rate"]),
                "channels": streams["audio"]["channels"],
                "packets": int(streams["audio"]["nb_frames"]),
            },
            "full_decode_error_lines": 0,
            "black_events_at_least_0_25s": 0,
            "freeze_events_at_least_0_5s": 0,
            "silence_events_below_minus45db_at_least_1s": 0,
        },
        "direct_representative_visual_review": {
            "sample_count": 24,
            "verdict": "PASS_REPRESENTATIVE_VISUAL_ONLY",
            "identity_and_age_continuity": "PASS_SAMPLED_FRAMES",
            "period_and_weather_continuity": "PASS_SAMPLED_FRAMES",
            "action_causality": "PASS_SAMPLED_PROGRESSION_PUBLIC_EXECUTION_TO_OBSERVERS_TO_AFTERMATH",
            "portrait_reframe_composition": "PASS_SAMPLED_FRAMES",
            "modern_intrusion": "PASS_NONE_VISIBLE_IN_SAMPLED_FRAMES",
            "visible_text_or_ocr_risk": "PASS_NONE_VISIBLE_IN_SAMPLED_FRAMES",
            "scope_limit": "CONTACT_SHEET_DOES_NOT_CLEAR_REALTIME_COMFORT_LIPSYNC_BREATH_OR_FULL_DIALOGUE",
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "accepted_source_binding": f"PASS_{len(intersecting)}_INTERSECTING_SOURCES",
            "bounded_media_decode": "PASS_ZERO_ERRORS",
            "bounded_black_freeze": "PASS_ZERO_EVENTS",
            "bounded_audio_continuity": "PASS_ZERO_SILENCE_EVENTS_GE_1S_AT_MINUS45DB",
            "bounded_representative_visual": "PASS_24_SAMPLES",
            "bounded_realtime_human_audiovisual_watch": "NOT_COMPLETE",
            "remaining_candidate_seconds_not_bounded_reviewed": round(288.911 - 60.0, 3),
            "full_continuous_audiovisual_watch": "NOT_COMPLETE",
            "transcript": "HOLD_39_OF_47",
            "motion": "HOLD_29_OF_30_U08",
            "promotion": "NOT_YET",
            "release": "HOLD",
        },
        "blocked_by": BLOCKED_BY,
        "workaround_executed": (
            "Advanced the V19 watch gate with a zero-credit bounded 0-60s package: exact source-map overlap, "
            "full decode, black/freeze scan, silence scan, waveform and direct 24-frame visual review. "
            "The result is explicitly representative rather than a continuous realtime clearance."
        ),
        "credits": "Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0",
        "next_action": "Continue bounded V19 review at 60-120s with dialogue/lipsync and reframe-comfort checks, while preserving all release holds and pursuing zero-credit unresolved-line/U08 recovery.",
    }
    dump(QA_PATH, qa)
    qa_sha = sha256(QA_PATH)

    queue = load(QUEUE_PATH)
    queue.update(
        {
            "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA,
            "updated_at": now,
            "status": "E36_V19_BOUNDED_WATCH_000_060_PASS_FULL_WATCH_ACTIVE",
            "latest_v19_watch_000_060_qa": rel(QA_PATH),
            "latest_v19_watch_000_060_qa_sha256": qa_sha,
            "blocked_by": BLOCKED_BY,
            "next_action": qa["next_action"],
        }
    )
    dump(QUEUE_PATH, queue)

    dispatch = load(DISPATCH_PATH)
    dispatch.update(
        {
            "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA,
            "generated_at": now,
            "blocked_by": BLOCKED_BY,
            "workaround_executed": qa["workaround_executed"],
            "next_action": qa["next_action"],
        }
    )
    dispatch.setdefault("execution", {})["latest_v19_watch_000_060_qa"] = {
        "path": rel(QA_PATH),
        "sha256": qa_sha,
        "status": "PASS_BOUNDED_REPRESENTATIVE_REVIEW_FULL_CONTINUOUS_WATCH_NOT_COMPLETE",
    }
    dump(DISPATCH_PATH, dispatch)

    queue_sha = sha256(QUEUE_PATH)
    dispatch_sha = sha256(DISPATCH_PATH)
    receipt = f"""

# [X2CL-20260731-2152] E36 V19 bounded 0-60s audiovisual package advances the full-watch gate
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED_BY}`
- workaround_executed: `{qa['workaround_executed']}`
- artifacts: `{rel(QA_PATH)}` sha256=`{qa_sha}`; `{artifacts['review_reel']['path']}` sha256=`{artifacts['review_reel']['sha256']}`; `{artifacts['contact_sheet']['path']}` sha256=`{artifacts['contact_sheet']['sha256']}`; `{artifacts['waveform']['path']}` sha256=`{artifacts['waveform']['sha256']}`; `{artifacts['probe']['path']}` sha256=`{artifacts['probe']['sha256']}`; `{artifacts['full_decode_log']['path']}` sha256=`{artifacts['full_decode_log']['sha256']}`; `{artifacts['silence_log']['path']}` sha256=`{artifacts['silence_log']['sha256']}`; `{artifacts['black_freeze_log']['path']}` sha256=`{artifacts['black_freeze_log']['sha256']}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;source_map_overlap:PASS_{len(intersecting)};window:PASS_60P000_SECONDS;full_decode:PASS_ZERO_ERRORS;black_freeze:PASS_ZERO_EVENTS;audio_silence:PASS_ZERO_GE_1S_AT_MINUS45DB;direct_visual:PASS_24_REPRESENTATIVE_SAMPLES_IDENTITY_PERIOD_CAUSALITY_COMPOSITION_NO_MODERN_INTRUSION;realtime_lipsync_breath_comfort:NOT_CLEARED_BY_CONTACT_SHEET;remaining_full_watch:HOLD_228P911_SECONDS;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `{qa['credits']}`
- next_action: `{qa['next_action']}`
"""
    with RECEIPT_PATH.open("a", encoding="utf-8") as f:
        f.write(receipt)

    print(
        json.dumps(
            {
                "qa_sha256": qa_sha,
                "queue_sha256": queue_sha,
                "dispatch_sha256": dispatch_sha,
                "receipt_file_sha256": sha256(RECEIPT_PATH),
                "intersecting_sources": len(intersecting),
            }
        )
    )


if __name__ == "__main__":
    main()
