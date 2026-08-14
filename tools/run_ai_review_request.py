#!/usr/bin/env python3
"""Run one qingshan-review request and persist a durable wrapper report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    request = resolve(args.request)
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    started_at = now()
    command = [
        str(ROOT / ".ai_review_env/bin/qingshan-review"),
        "review-many",
        str(request),
    ]
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    stdout_path = out.with_suffix(out.suffix + ".stdout.txt")
    stderr_path = out.with_suffix(out.suffix + ".stderr.txt")
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    payload = {
        "schema": "qingshan.ai_review_wrapper.v1",
        "request": str(request.relative_to(ROOT)),
        "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
        "command": command,
        "started_at": started_at,
        "finished_at": now(),
        "returncode": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "generation_credit": 0,
        "stdout_path": str(stdout_path.relative_to(ROOT)),
        "stderr_path": str(stderr_path.relative_to(ROOT)),
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "returncode": proc.returncode}, ensure_ascii=False))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
