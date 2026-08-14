#!/usr/bin/env python3
"""Idempotently bind U12 V3 asset/QA and its exact five-credit cost into work_queue."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
TASK_ID = "562bcf99-ee03-48fa-9a57-f774f75a52d2"
IMAGE = "working_assets/e40_production_20260809/u12_v3_interior_desk_mouth_absent_plate_v1/E40-U12-V3-INTERIOR-DESK-MOUTH-ABSENT-PLATE-V1_562bcf99-ee03-48fa-9a57-f774f75a52d2.png"
IMAGE_SHA = "6f99b0d16ec7c63ffa6314d8315b2aba45ac0645dac2f3c5bbe6438b3a2cbed8"
QA = "qa/e40_production_20260809/u12_v3_interior_desk_mouth_absent_plate_v1/E40_U12_V3_INTERIOR_PLATE_FINAL_QA_V1.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    for _attempt in range(40):
        before = QUEUE.read_bytes()
        payload = json.loads(before)
        current = payload.get("latest_e40_u12_v3_interior_plate") or {}
        if current.get("task_id") == TASK_ID:
            print(json.dumps({"status": "ALREADY_APPLIED", "queue_sha256": sha(before)}))
            return 0

        credits = payload["e40_credits"]
        credits["gross_pay"] = int(credits["gross_pay"]) + 5
        credits["net"] = int(credits["net"]) + 5
        credits["remaining"] = int(credits["cap"]) - int(credits["net"])
        credits["active_remote_image_pay"] = 0
        payload["latest_e40_u12_v3_interior_plate"] = {
            "status": "PASS_ADMITTED_SOURCE_PLATE_VIDEO_NOT_AUTHORIZED",
            "task_id": TASK_ID,
            "task_fingerprint": "e91e29d0b246e82fea4079a92e42bcfe4cceb28c69ace880743c8e2fd81066ef",
            "asset": IMAGE,
            "asset_sha256": IMAGE_SHA,
            "human_score": 92,
            "visible_characters_faces_mouths": [0, 0, 0],
            "gross_pay": 5,
            "refund": 0,
            "net": 5,
            "qa": QA,
            "maximum_new_submissions": 0,
            "submitter_reentry": "FORBIDDEN"
        }
        payload["updated_at"] = stamp()
        payload["updated_note_latest"] = (
            "U12 V3 exactly-one interior desk/mouth-absent image completed and passed source-plate QA at 92. "
            "The bound provider task charged 5 credits; maximum new submissions is zero. "
            "The source plate is not a video or AgentCut authorization, while other independent E40 lanes remain active."
        )
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

        # Optimistic compare immediately before atomic replacement preserves concurrent edits.
        observed = QUEUE.read_bytes()
        if observed != before:
            time.sleep(0.05)
            continue
        descriptor, temporary = tempfile.mkstemp(prefix=QUEUE.name + ".", suffix=".part", dir=QUEUE.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if QUEUE.read_bytes() != before:
                os.unlink(temporary)
                time.sleep(0.05)
                continue
            os.replace(temporary, QUEUE)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print(json.dumps({"status": "COMMITTED_CAS", "before_sha256": sha(before), "after_sha256": sha(encoded)}))
        return 0
    raise SystemExit("work_queue CAS contention did not settle")


if __name__ == "__main__":
    raise SystemExit(main())
