#!/usr/bin/env python3
"""Derive a deterministic native-speed action audit from an AgentCut project."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    video_path = Path(args.video).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))

    actions = []
    failures = []
    forbidden_retime_keys = {"speed", "rate", "timeScale", "timeRemap", "reverse"}
    for track in project.get("timeline", {}).get("videoTracks", []):
        if track.get("enabled", True) is False:
            continue
        for clip in track.get("clips", []):
            present_retime = sorted(key for key in forbidden_retime_keys if key in clip)
            if present_retime:
                failures.append(f"retime_field_present:{clip.get('id')}:{','.join(present_retime)}")
            metadata = clip.get("metadata") or {}
            actions.append(
                {
                    "clip_id": clip.get("id"),
                    "source": clip.get("source"),
                    "start_seconds": clip.get("start"),
                    "in_seconds": clip.get("in", 0),
                    "duration_seconds": clip.get("duration"),
                    "playback_rate": 1.0,
                    "retime_fields_present": present_retime,
                    "cut_reason": metadata.get("cut_reason"),
                    "narrative_function": metadata.get("narrative_function"),
                    "status": "PASS_NATIVE_SPEED" if not present_retime else "FAIL_RETIME_PRESENT",
                }
            )

    if not actions:
        failures.append("no_enabled_video_clips")
    payload = {
        "schema": "qingshan.action_realtime_audit.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "policy": "AgentCut materialized timeline must use native-speed source action; synthetic retime fields are forbidden.",
        "video": str(video_path),
        "media_path": str(video_path),
        "video_sha256": sha256(video_path),
        "project": str(project_path),
        "project_sha256": sha256(project_path),
        "action_count": len(actions),
        "actions": actions,
        "failures": failures,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "actions": len(actions), "failures": len(failures), "out": str(out_path)}))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
