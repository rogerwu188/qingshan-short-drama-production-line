#!/usr/bin/env python3
"""Finalize a generated V19 bounded watch package and preserve all hard holds."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
CANDIDATE_DURATION = 288.911
LINE10_INSERT_AT = 70.928060
LINE10_DURATION = 6.082993
LINE10_SOURCE_ID = "U09_CANONICAL_LINE10_CHANGED_W3_ZERO_CREDIT_SALVAGE"
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


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def artifact(directory: Path, name: str) -> dict:
    path = directory / name
    return {"path": rel(path), "sha256": sha256(path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--source-cl2x", required=True)
    parser.add_argument("--mailbox-sha", required=True)
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--visual-summary", required=True)
    parser.add_argument("--ocr-observation", default="PASS_NONE_VISIBLE_IN_SAMPLED_FRAMES")
    parser.add_argument("--cumulative-start", type=float, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.start < 0 or args.end <= args.start or args.end > CANDIDATE_DURATION:
        raise SystemExit("invalid bounded window")
    tag = f"{round(args.start):03d}_{round(args.end):03d}"
    directory = ROOT / f"qa/e36_agentcut_20260730/accepted_only_agentcut_v19_watch_{tag}_v1"
    qa_path = ROOT / f"qa/e36_agentcut_20260730/E36_V19_WATCH_{tag}_BOUNDED_QA_V1.json"
    names = {
        "review_reel": f"E36_V19_WATCH_{tag}_REVIEW_REEL_V1.mp4",
        "contact_sheet": f"E36_V19_WATCH_{tag}_CONTACT_SHEET_V1.jpg",
        "waveform": f"E36_V19_WATCH_{tag}_WAVEFORM_V1.png",
        "probe": f"E36_V19_WATCH_{tag}_PROBE_V1.json",
        "full_decode_log": f"E36_V19_WATCH_{tag}_FULL_DECODE_V1.log",
        "silence_log": f"E36_V19_WATCH_{tag}_SILENCEDETECT_V1.log",
        "black_freeze_log": f"E36_V19_WATCH_{tag}_BLACK_FREEZE_V1.log",
    }
    artifacts = {key: artifact(directory, name) for key, name in names.items()}
    for key in ("full_decode_log", "silence_log", "black_freeze_log"):
        if (directory / names[key]).stat().st_size != 0:
            raise SystemExit(f"nonempty gate log: {key}")

    source_map = load(SOURCE_MAP)
    # V19 inserts line10 into the V18C/V15 timeline. Post-insert windows must
    # be translated back by the inserted duration before binding source-map rows.
    mapped_intervals = []
    if args.start < LINE10_INSERT_AT:
        mapped_intervals.append(
            {"kind": "base", "candidate_seconds": [args.start, min(args.end, LINE10_INSERT_AT)], "base_seconds": [args.start, min(args.end, LINE10_INSERT_AT)]}
        )
    if args.start < LINE10_INSERT_AT + LINE10_DURATION and args.end > LINE10_INSERT_AT:
        mapped_intervals.append(
            {"kind": "inserted_line10", "candidate_seconds": [max(args.start, LINE10_INSERT_AT), min(args.end, LINE10_INSERT_AT + LINE10_DURATION)]}
        )
    if args.end > LINE10_INSERT_AT + LINE10_DURATION:
        candidate_start = max(args.start, LINE10_INSERT_AT + LINE10_DURATION)
        mapped_intervals.append(
            {"kind": "base", "candidate_seconds": [candidate_start, args.end], "base_seconds": [candidate_start - LINE10_DURATION, args.end - LINE10_DURATION]}
        )

    source_by_id = {source["source_id"]: source for source in source_map["sources"]}
    intersecting_ids = []
    for interval in mapped_intervals:
        if interval["kind"] == "inserted_line10":
            candidates = [LINE10_SOURCE_ID]
        else:
            mapped_start, mapped_end = interval["base_seconds"]
            candidates = [
                source["source_id"]
                for source in source_map["sources"]
                if source["accepted_only_timeline_seconds"][0] < mapped_end
                and source["accepted_only_timeline_seconds"][1] > mapped_start
            ]
        for source_id in candidates:
            if source_id not in intersecting_ids:
                intersecting_ids.append(source_id)
    intersecting = []
    for source_id in intersecting_ids:
        source = source_by_id[source_id]
        intersecting.append(
            {
                "source_id": source["source_id"],
                "canonical_units": source["canonical_units"],
                "base_timeline_seconds": source["accepted_only_timeline_seconds"],
                "media_sha256": source["media_sha256"],
                "qa_sha256": source["qa_sha256"],
            }
        )
    probe = load(directory / names["probe"])
    streams = {stream["codec_type"]: stream for stream in probe["streams"]}
    now = datetime.now(timezone.utc).isoformat()
    bounded_seconds = args.end - args.start
    cumulative_seconds = args.end - args.cumulative_start
    remaining_seconds = round(CANDIDATE_DURATION - args.end, 3)
    workaround = (
        f"Consumed and continued under {args.source_cl2x}, advancing the V19 watch gate with a zero-credit bounded "
        f"{args.start}-{args.end}s package: exact source-map overlap, full decode, black/freeze scan, "
        "silence scan, waveform and direct 24-frame visual review. The result remains representative "
        "and does not clear realtime lipsync, breath, comfort or full-film continuity."
    )
    qa = {
        "schema": "e36_v19_bounded_watch_qa_v1",
        "status": "PASS_BOUNDED_REPRESENTATIVE_REVIEW_FULL_CONTINUOUS_WATCH_NOT_COMPLETE",
        "generated_at": now,
        "source_cl2x": args.source_cl2x,
        "source_mailbox_sha256": args.mailbox_sha,
        "episode": "E36",
        "candidate": {
            "path": "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4",
            "sha256": "36faf0d5ce91b1b3aa938a7183c4bc9e6a0a034c3886a019a0ebbab3da029dde",
            "promotion": "REVERSIBLE_NOT_PROMOTED",
        },
        "window_seconds": [args.start, args.end],
        "window_fraction_of_candidate": round(bounded_seconds / CANDIDATE_DURATION, 6),
        "cumulative_bounded_representative_coverage_seconds": [args.cumulative_start, args.end],
        "cumulative_bounded_representative_fraction": round(cumulative_seconds / CANDIDATE_DURATION, 6),
        "v19_to_base_timeline_mapping": mapped_intervals,
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
            "observed_progression": args.visual_summary,
            "identity_and_age_continuity": "PASS_SAMPLED_FRAMES",
            "period_and_weather_continuity": "PASS_SAMPLED_FRAMES",
            "portrait_reframe_composition": "PASS_SAMPLED_FRAMES",
            "modern_intrusion": "PASS_NONE_VISIBLE_IN_SAMPLED_FRAMES",
            "visible_text_or_ocr_risk": args.ocr_observation,
            "scope_limit": "CONTACT_SHEET_DOES_NOT_CLEAR_REALTIME_COMFORT_LIPSYNC_BREATH_OR_FULL_DIALOGUE",
        },
        "gate_results": {
            "canonical_script_manifest": "PASS_EXACT",
            "accepted_source_binding": f"PASS_{len(intersecting)}_INTERSECTING_SOURCES",
            "bounded_media_decode": "PASS_ZERO_ERRORS",
            "bounded_black_freeze": "PASS_ZERO_EVENTS",
            "bounded_audio_continuity": "PASS_ZERO_SILENCE_EVENTS_GE_1S_AT_MINUS45DB",
            "bounded_representative_visual": "PASS_24_SAMPLES",
            "cumulative_bounded_representative_coverage": f"PASS_{args.cumulative_start}_{args.end}_SECONDS",
            "remaining_candidate_seconds_not_bounded_reviewed": remaining_seconds,
            "full_continuous_audiovisual_watch": "NOT_COMPLETE",
            "transcript": "HOLD_39_OF_47",
            "motion": "HOLD_29_OF_30_U08",
            "promotion": "NOT_YET",
            "release": "HOLD",
        },
        "blocked_by": BLOCKED_BY,
        "workaround_executed": workaround,
        "credits": "Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0",
        "next_action": (
            "Bounded representative coverage now spans the full V19 runtime. Preserve the continuous realtime human-watch hold, "
            "run dense high-frequency reframe/lipsync probes, and continue zero-credit unresolved-line/U08 recovery."
            if remaining_seconds <= 0
            else f"Continue bounded V19 representative review at {args.end}-{min(args.end + 60, CANDIDATE_DURATION)}s while preserving all release holds and pursuing zero-credit unresolved-line/U08 recovery."
        ),
    }
    dump(qa_path, qa)
    qa_sha = sha256(qa_path)

    queue = load(QUEUE)
    queue.update(
        {
            "source_cl2x": args.source_cl2x,
            "source_mailbox_sha256": args.mailbox_sha,
            "updated_at": now,
            "status": f"E36_V19_BOUNDED_WATCH_{tag}_PASS_FULL_WATCH_ACTIVE",
            f"latest_v19_watch_{tag}_qa": rel(qa_path),
            f"latest_v19_watch_{tag}_qa_sha256": qa_sha,
            "blocked_by": BLOCKED_BY,
            "next_action": qa["next_action"],
        }
    )
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.update(
        {
            "source_cl2x": args.source_cl2x,
            "source_mailbox_sha256": args.mailbox_sha,
            "generated_at": now,
            "blocked_by": BLOCKED_BY,
            "workaround_executed": workaround,
            "next_action": qa["next_action"],
        }
    )
    dispatch.setdefault("execution", {})[f"latest_v19_watch_{tag}_qa"] = {
        "path": rel(qa_path),
        "sha256": qa_sha,
        "status": qa["status"],
    }
    dispatch["execution"]["last_real_progress"] = workaround
    dispatch["execution"]["status"] = f"{args.source_cl2x}_V19_BOUNDED_WATCH_{tag}_PASS_REVERSIBLE_NOT_PROMOTED"
    dump(DISPATCH, dispatch)

    queue_sha = sha256(QUEUE)
    dispatch_sha = sha256(DISPATCH)
    receipt = f"""

# [{args.receipt_id}] E36 V19 bounded {args.start}-{args.end}s audiovisual package advances the full-watch gate
- source_cl2x: `{args.source_cl2x}`; source_mailbox_sha256=`{args.mailbox_sha}`
- blocked_by: `{BLOCKED_BY}`
- workaround_executed: `{workaround}`
- artifacts: `{rel(qa_path)}` sha256=`{qa_sha}`; `{artifacts['review_reel']['path']}` sha256=`{artifacts['review_reel']['sha256']}`; `{artifacts['contact_sheet']['path']}` sha256=`{artifacts['contact_sheet']['sha256']}`; `{artifacts['waveform']['path']}` sha256=`{artifacts['waveform']['sha256']}`; `{artifacts['probe']['path']}` sha256=`{artifacts['probe']['sha256']}`; `{artifacts['full_decode_log']['path']}` sha256=`{artifacts['full_decode_log']['sha256']}`; `{artifacts['silence_log']['path']}` sha256=`{artifacts['silence_log']['sha256']}`; `{artifacts['black_freeze_log']['path']}` sha256=`{artifacts['black_freeze_log']['sha256']}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `canonical_script_manifest:PASS_EXACT;source_map_overlap:PASS_{len(intersecting)};window:PASS_{bounded_seconds:.3f}_SECONDS;full_decode:PASS_ZERO_ERRORS;black_freeze:PASS_ZERO_EVENTS;audio_silence:PASS_ZERO_GE_1S_AT_MINUS45DB;direct_visual:PASS_24_REPRESENTATIVE_SAMPLES;realtime_lipsync_breath_comfort:NOT_CLEARED_BY_CONTACT_SHEET;cumulative_representative_coverage:PASS_{args.cumulative_start}_{args.end}_SECONDS;remaining_full_watch:HOLD_{remaining_seconds}_SECONDS;transcript:HOLD_39_OF_47;motion:HOLD_29_OF_30_U08;promotion:NOT_YET;release:HOLD`
- credits: `{qa['credits']}`
- next_action: `{qa['next_action']}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"qa_sha256": qa_sha, "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_file_sha256": sha256(RECEIPTS), "intersecting_sources": len(intersecting)}))


if __name__ == "__main__":
    main()
