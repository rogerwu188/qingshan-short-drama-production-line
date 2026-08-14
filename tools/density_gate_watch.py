#!/usr/bin/env python3
"""Keep a real local process on a blocked density gate until its review arrives."""

from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--script", required=True)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--time-ledger", required=True)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    out = ROOT / args.out
    while True:
        command = [
            "python3", "tools/script_density_gate_preflight.py",
            "--episode", args.episode,
            "--script", args.script,
            "--review-dir", args.review_dir,
            "--out", args.out,
            "--time-ledger", args.time_ledger,
        ]
        proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        payload = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {"status": "FAIL", "failures": ["preflight_output_missing"]}
        payload["watch_pid"] = __import__("os").getpid()
        payload["watch_last_run_at"] = now()
        payload["watch_returncode"] = proc.returncode
        payload["watch_state"] = "PASS_AND_READY_FOR_NEXT_STAGE" if payload.get("status") == "PASS" else "WAITING_FOR_MATCHED_REVIEW"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if payload.get("status") == "PASS":
            return 0
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
