#!/usr/bin/env python3
"""Validate the script-layer action and xuanhuan contract before production lock."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


FIELDS = ("payload_delivery", "action_spine", "xuanhuan_element", "power_visualization")
FIGHT_MARKERS = ("打斗", "搏斗", "擒拿", "格挡", "短打", "交锋", "fight", "combat")


def validate(payload: dict) -> dict:
    beats = payload.get("structure") or []
    failures: list[dict] = []
    for beat in beats:
        beat_id = beat.get("beat_id") or "UNKNOWN"
        for field in FIELDS:
            if not str(beat.get(field) or "").strip():
                failures.append({"beat_id": beat_id, "check": f"missing_{field}"})
        if str(beat.get("payload_delivery") or "").upper() not in {"ACTION", "ACTION_XUANHUAN"}:
            failures.append({"beat_id": beat_id, "check": "payload_not_action"})

    combined_actions = " ".join(str(beat.get("action_spine") or "") for beat in beats).lower()
    if not any(marker in combined_actions for marker in FIGHT_MARKERS):
        failures.append({"beat_id": "EPISODE", "check": "missing_complete_fight_sequence"})

    xuanhuan_beats = [beat.get("beat_id") for beat in beats if str(beat.get("xuanhuan_element") or "").strip()]
    if not xuanhuan_beats:
        failures.append({"beat_id": "EPISODE", "check": "missing_xuanhuan_reveal"})

    return {
        "schema": "qingshan.action_xuanhuan_script_gate.v1",
        "episode": payload.get("episode"),
        "status": "PASS" if beats and not failures else "FAIL",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "beat_count": len(beats),
        "required_fields": list(FIELDS),
        "fight_sequence_present": any(marker in combined_actions for marker in FIGHT_MARKERS),
        "xuanhuan_beats": xuanhuan_beats,
        "failures": failures,
        "final_lock_allowed": bool(beats and not failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    script = Path(args.script)
    out = Path(args.out)
    report = validate(json.loads(script.read_text(encoding="utf-8")))
    report["script"] = str(script)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
