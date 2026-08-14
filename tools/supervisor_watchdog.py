#!/usr/bin/env python3
"""Keep the independently running episode supervisors self-healing."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/ACTIVE_EPISODE_LINES_LATEST.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def live(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def recent_heartbeat(receipt: dict, seconds: int = 60) -> bool:
    value = receipt.get("last_heartbeat_at")
    if not value:
        return False
    try:
        observed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except ValueError:
        return False
    return (time.time() - observed) < seconds


def supervisor_args(receipt_path: Path, receipt: dict) -> list[str]:
    if receipt.get("supervisor_type") == "episode_parallel_batch":
        return [
            "python3", "-u", str(ROOT / "tools/episode_parallel_batch_supervisor.py"),
            "--config", str(ROOT / receipt["config"]),
            "--receipt", str(receipt_path),
        ]
    episode = receipt["episode"]
    previous_output = receipt.get("previous_output_path")
    previous_qa = receipt.get("previous_qa")
    if not previous_output or not previous_qa:
        raise RuntimeError(f"{episode}: receipt lacks output/QA evidence for restart")
    return [
        "python3", "-u", str(ROOT / "tools/episode_candidate_supervisor.py"),
        "--episode", episode,
        "--receipt", str(receipt_path),
        "--prompt-file", str(ROOT / receipt["prompt"]),
        "--qa-dir", str(ROOT / Path(previous_qa).parent),
        "--output-dir", str(ROOT / Path(previous_output).parent),
    ]


def restart(receipt_path: Path, receipt: dict) -> None:
    args = supervisor_args(receipt_path, receipt)
    log_path = ROOT / "workflow/production_line" / f"{receipt['episode']}_supervisor.log"
    log = log_path.open("ab", buffering=0)
    env = os.environ.copy()
    child = subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
        close_fds=True,
    )
    receipt["local_pid"] = child.pid
    receipt["status"] = "SUPERVISOR_RUNNING"
    receipt["last_action"] = "watchdog_restarted_supervisor"
    receipt["last_action_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    receipt["last_action_evidence"] = str(log_path)
    receipt["restart_count"] = int(receipt.get("restart_count") or 0) + 1
    receipt["activity_note"] = (
        f"Watchdog PID {os.getpid()} restarted supervisor PID {child.pid}; "
        "the episode line remains independently recoverable."
    )
    write_json(receipt_path, receipt)


def check_once() -> int:
    state = read_json(STATE)
    restarted = 0
    for line in state.get("parallel_lines", []):
        evidence = line.get("evidence") or (
            f"workflow/tasks/{line['episode']}_parallel_candidate_submit_20260718.json"
        )
        receipt_path = ROOT / evidence
        receipt = read_json(receipt_path)
        if not live(receipt.get("local_pid")) and not recent_heartbeat(receipt):
            restart(receipt_path, receipt)
            restarted += 1
    return restarted


def main() -> int:
    interval = float(os.environ.get("QINGSHAN_WATCHDOG_INTERVAL", "10"))
    while True:
        check_once()
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
