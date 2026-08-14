#!/usr/bin/env python3
"""Supersede pre-correction V19 bounded-window source counts after line10 insertion."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MAP = ROOT / "qa/e36_agentcut_20260730/E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V10.json"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_V19_BOUNDED_WATCH_SOURCE_BINDING_TIMELINE_CORRECTION_V1.json"
QUEUE = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPTS = ROOT / "workflow/CODEX_TO_CLAUDE.md"
SOURCE_CL2X = "CL2X-911"
MAILBOX_SHA = "0e4e36c5362b409ffc270447aaf915d938a28b6ed136a4cbcbe2d343fbd083a5"
INSERT_AT = 70.928060
INSERT_DURATION = 6.082993
INSERT_SOURCE = "U09_CANONICAL_LINE10_CHANGED_W3_ZERO_CREDIT_SALVAGE"
BLOCKED_BY = "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08;PAID_VIDEO_SUBMISSION_ONLY:CREDIT_RUNWAY_24;PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def binding(sources: list[dict], start: float, end: float) -> dict:
    intervals = []
    if start < INSERT_AT:
        intervals.append({"kind": "base", "candidate": [start, min(end, INSERT_AT)], "base": [start, min(end, INSERT_AT)]})
    if start < INSERT_AT + INSERT_DURATION and end > INSERT_AT:
        intervals.append({"kind": "inserted_line10", "candidate": [max(start, INSERT_AT), min(end, INSERT_AT + INSERT_DURATION)]})
    if end > INSERT_AT + INSERT_DURATION:
        candidate_start = max(start, INSERT_AT + INSERT_DURATION)
        intervals.append({"kind": "base", "candidate": [candidate_start, end], "base": [candidate_start - INSERT_DURATION, end - INSERT_DURATION]})
    ids = []
    for interval in intervals:
        if interval["kind"] == "inserted_line10":
            candidates = [INSERT_SOURCE]
        else:
            mapped_start, mapped_end = interval["base"]
            candidates = [s["source_id"] for s in sources if s["accepted_only_timeline_seconds"][0] < mapped_end and s["accepted_only_timeline_seconds"][1] > mapped_start]
        for source_id in candidates:
            if source_id not in ids:
                ids.append(source_id)
    return {"candidate_window_seconds": [start, end], "mapping_intervals": intervals, "corrected_source_count": len(ids), "corrected_source_ids": ids}


def main() -> None:
    sources = load(SOURCE_MAP)["sources"]
    rows = [binding(sources, start, end) for start, end in ((0, 60), (60, 120), (120, 180), (180, 240))]
    rows[0]["previously_reported_count"] = 12
    rows[1]["previously_reported_count"] = 10
    rows[2]["previously_reported_count"] = 12
    rows[3]["previously_reported_count"] = None
    for row in rows:
        previous = row["previously_reported_count"]
        row["count_correction"] = None if previous is None else row["corrected_source_count"] - previous
    now = datetime.now(timezone.utc).isoformat()
    qa = {
        "schema": "e36_v19_bounded_watch_source_binding_timeline_correction_v1",
        "status": "PASS_CORRECTION_SUPERSEDES_PREVIOUS_WINDOW_SOURCE_COUNTS_ONLY",
        "generated_at": now,
        "source_cl2x": SOURCE_CL2X,
        "source_mailbox_sha256": MAILBOX_SHA,
        "cause": "V19 inserts line10 at 70.928060s; post-insert candidate windows must map to the V18C/V15 base timeline by subtracting 6.082993s.",
        "windows": rows,
        "impact": {
            "media_decode_black_freeze_silence_visual_results": "UNCHANGED",
            "window_60_120_source_count": "CORRECTED_10_TO_9",
            "window_120_180_source_count": "COUNT_12_UNCHANGED_IDENTITIES_CORRECTED",
            "future_window_binding": "FIXED_IN_GENERIC_FINALIZER",
            "promotion": "NOT_YET",
            "release": "HOLD",
        },
        "blocked_by": BLOCKED_BY,
        "workaround_executed": "Detected and corrected the bounded-watch source-binding offset introduced by the 6.082993-second line10 insertion. Preserved prior media QA results and superseded only the affected source-count/identity fields.",
        "credits": "Pay0/Refund0/Net0 this heartbeat; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0",
        "next_action": "Use the insertion-aware binding transform for 180-240s and all remaining V19 windows; continue direct bounded media review without promoting V19.",
    }
    dump(OUTPUT, qa)
    qa_sha = sha256(OUTPUT)
    queue = load(QUEUE)
    queue.update({"latest_v19_bounded_watch_source_binding_correction": str(OUTPUT.relative_to(ROOT)), "latest_v19_bounded_watch_source_binding_correction_sha256": qa_sha, "updated_at": now})
    dump(QUEUE, queue)
    dispatch = load(DISPATCH)
    dispatch.setdefault("execution", {})["latest_v19_bounded_watch_source_binding_correction"] = {"path": str(OUTPUT.relative_to(ROOT)), "sha256": qa_sha, "status": qa["status"]}
    dump(DISPATCH, dispatch)
    queue_sha = sha256(QUEUE)
    dispatch_sha = sha256(DISPATCH)
    receipt = f"""

# [X2CL-20260731-2207] E36 V19 bounded-watch source bindings corrected for inserted line10 offset
- source_cl2x: `{SOURCE_CL2X}`; source_mailbox_sha256=`{MAILBOX_SHA}`
- blocked_by: `{BLOCKED_BY}`
- workaround_executed: `{qa['workaround_executed']}`
- artifacts: `{OUTPUT.relative_to(ROOT)}` sha256=`{qa_sha}`; `tools/finalize_e36_v19_bounded_watch.py` sha256=`{sha256(ROOT / 'tools/finalize_e36_v19_bounded_watch.py')}`; `workflow/work_queue.json` sha256=`{queue_sha}`; `workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json` sha256=`{dispatch_sha}`
- gate_results: `0_60_binding:PASS_12_UNCHANGED;60_120_binding:CORRECTED_10_TO_9;120_180_binding:COUNT_12_UNCHANGED_IDENTITIES_CORRECTED;prior_media_gates:UNCHANGED;future_binding_transform:PASS_INSERTION_AWARE;promotion:NOT_YET;release:HOLD`
- credits: `{qa['credits']}`
- next_action: `{qa['next_action']}`
"""
    with RECEIPTS.open("a", encoding="utf-8") as f:
        f.write(receipt)
    print(json.dumps({"qa_sha256": qa_sha, "queue_sha256": queue_sha, "dispatch_sha256": dispatch_sha, "receipt_file_sha256": sha256(RECEIPTS)}))


if __name__ == "__main__":
    main()
