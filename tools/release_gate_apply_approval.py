#!/usr/bin/env python3
"""Apply an explicit approval to a release gate JSON without uploading."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply StoryClaw/Roger approval to a release gate JSON.")
    parser.add_argument("gate_json", help="Path to release gate status JSON.")
    parser.add_argument("--source", required=True, choices=["storyclaw", "roger"], help="Approval source.")
    parser.add_argument("--note", required=True, help="Approval note or SC2X/C2SC reference.")
    args = parser.parse_args()

    gate_path = Path(args.gate_json).expanduser().resolve()
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    quality = gate.setdefault("quality_gates", {})
    if args.source == "storyclaw":
        quality["storyclaw_review"] = "APPROVED"
    else:
        quality["roger_override"] = "APPROVED"

    gate["overall_status"] = "APPROVED_FOR_PLATFORM_UPLOAD"
    gate["approval"] = {
        "source": args.source,
        "approved_at": now,
        "note": args.note,
    }
    release = gate.setdefault("platform_release", {})
    release["publish_allowed"] = True
    release["youtube"] = "READY"
    release["douyin"] = "READY_AFTER_YOUTUBE_RECORD"
    release["hold_reason"] = None
    gate["updated_at"] = now

    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "gate_json": str(gate_path), "status": gate["overall_status"], "approved_at": now}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
