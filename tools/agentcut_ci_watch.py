#!/usr/bin/env python3
"""Continuously re-check an AgentCut candidate until its CI gates converge."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    out = ROOT / args.out
    ci_out = out.with_name(out.stem + ".regression.json")
    while True:
        validate = subprocess.run(
            ["./tools/run_agentcut.sh", "validate", "--strict-media", args.project],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        ci = subprocess.run(
            ["python3", "tools/run_regression_ci.py", "--video", args.video, "--episode-id", args.episode, "--out", str(ci_out)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        payload = {
            "schema": "qingshan.agentcut_ci_watch.v1",
            "episode": args.episode,
            "project": args.project,
            "video": args.video,
            "watch_pid": os.getpid(),
            "checked_at": now(),
            "validate_returncode": validate.returncode,
            "validate_stdout": validate.stdout[-1500:],
            "validate_stderr": validate.stderr[-1500:],
            "ci_returncode": ci.returncode,
            "ci_stdout": ci.stdout[-2500:],
            "ci_stderr": ci.stderr[-2500:],
            "state": "PASS_READY_FOR_AUDIENCE_GATE" if validate.returncode == 0 and ci.returncode == 0 else "REPAIR_REQUIRED",
            "rollback": "Replace only the candidate project/render and rerun; source assets remain untouched.",
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if payload["state"] == "PASS_READY_FOR_AUDIENCE_GATE":
            return 0
        time.sleep(max(30, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
