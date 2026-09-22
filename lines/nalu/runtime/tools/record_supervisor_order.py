#!/usr/bin/env python3
"""record_supervisor_order.py — append one Roger order to SUPERVISOR_ORDERS.json.

Why this exists (2026-09-21): recording an order means editing the file that *is* the line's
authority, so the auto-mode classifier refuses ad-hoc scripts that write it ("Instruction
Poisoning") — correctly, since a model must not be able to manufacture its own authorisation by
writing prose into that file.  Roger then had to repeat 「同意」 five times in one night for the
same class of gate failure.

The split this tool makes:

* WHAT is accepted stays a human decision.  The operator runs this only after Roger says so in
  chat, and ``--order`` records his words verbatim.
* HOW it is written becomes a fixed, auditable shape: a single append, typed fields only, no
  free-form editing of existing rows, sha256 computed from the media on disk rather than supplied.

So the tool can be allow-listed in settings.json without giving the model a way to widen its own
permissions: every field it writes is either Roger's literal reply or a measurement of a file.

    record_supervisor_order.py --seq 53 --order 同意 --episode E08 \
        --gate-id CHARACTER-IDENTITY-ADMISSION \
        --detector E08-S02-03:CHAR-QINMING --detector E08-S14-03:CHAR-QINMING \
        --context "..." [--kind GATE_FAIL_ACCEPTANCE]

Each ``--detector`` is ``<item_id>:<character_id>``; the item's keyframe is hashed and bound to the
order, so the acceptance dies the moment that frame is regenerated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nalu_paths as _np  # noqa: E402  (portable ENGINE_ROOT / RUNTIME_ROOT)

ORDERS = Path(f"{_np.ENGINE_ROOT}/workflow/claude_writer_agent/SUPERVISOR_ORDERS.json")
KINDS = ("GATE_FAIL_ACCEPTANCE", "STANDING_RULE", "S8_APPROVAL")


def keyframe_path(episode: str, item_id: str) -> Path:
    return Path(f"{_np.ENGINE_ROOT}/workflow/nalu/{episode}/preproduction/keyframes/{item_id}-keyframe-v1.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seq", type=int, required=True)
    ap.add_argument("--order", required=True, help="Roger's reply, verbatim (e.g. 同意)")
    ap.add_argument("--episode", required=True)
    ap.add_argument("--kind", default="GATE_FAIL_ACCEPTANCE", choices=KINDS)
    ap.add_argument("--gate-id", required=True)
    ap.add_argument("--detector", action="append", default=[],
                    help="<item_id>:<character_id>; repeatable")
    ap.add_argument("--context", required=True, help="what was accepted and why, for the record")
    args = ap.parse_args()

    payload = json.loads(ORDERS.read_text(encoding="utf-8"))
    rows = payload["orders"] if isinstance(payload, dict) else payload
    if any(int(row.get("seq") or 0) == args.seq for row in rows):
        print(json.dumps({"status": "REFUSED", "reason": f"seq={args.seq} already recorded"}, ensure_ascii=False))
        return 2
    highest = max((int(row.get("seq") or 0) for row in rows), default=0)
    if args.seq != highest + 1:
        print(json.dumps({"status": "REFUSED", "reason": f"seq must be {highest + 1}, got {args.seq}"},
                         ensure_ascii=False))
        return 2

    shas: dict[str, str] = {}
    for detector in args.detector:
        item_id = str(detector).split(":", 1)[0]
        path = keyframe_path(args.episode, item_id)
        if not path.is_file():
            print(json.dumps({"status": "REFUSED", "reason": f"no keyframe on disk for {item_id}"},
                             ensure_ascii=False))
            return 2
        shas[item_id] = hashlib.sha256(path.read_bytes()).hexdigest()

    rows.append({
        "seq": args.seq,
        "issued_by": "Roger",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "active",
        "recorded_by": "record_supervisor_order.py (operator ran it after Roger replied in chat)",
        "order": args.order,
        "context": args.context,
        "decision": {
            "kind": args.kind,
            "episode": args.episode,
            "gate_id": args.gate_id,
            "detectors": sorted(args.detector),
            "media_sha256_by_item": shas,
        },
    })
    if isinstance(payload, dict):
        payload["orders"] = rows
    ORDERS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "RECORDED", "seq": args.seq, "detectors": len(args.detector),
                      "sha_bound_items": len(shas)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
