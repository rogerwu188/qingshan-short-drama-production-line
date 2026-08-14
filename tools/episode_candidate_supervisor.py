#!/usr/bin/env python3
"""Keep one independent candidate-generation line alive with real evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

from giggle_api_client import generate_video, query_task


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run(argv: list[str]) -> None:
    subprocess.run(argv, check=True)


def download(url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    with urlopen(Request(url, headers={"User-Agent": "qingshan-candidate-supervisor/1.0"}), timeout=120) as src:
        with partial.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    os.replace(partial, output)


def harvest(args: argparse.Namespace, receipt: dict, task_id: str, data: dict) -> tuple[Path | None, str]:
    urls = data.get("urls") or []
    out_dir = Path(args.output_dir)
    output = out_dir / f"{args.episode}_{task_id}.mp4"
    if not urls:
        return None, "completed_without_output_url"
    download(urls[0], output)
    qa_dir = Path(args.qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    report = qa_dir / f"remote_status_{task_id}.json"
    atomic_json(report, {"task_id": task_id, "remote_status": data.get("status"), "url_count": len(urls), "output_path": str(output), "bytes": output.stat().st_size})
    qa_failures = []
    cadence = subprocess.run([
        "python3", "tools/frame_cadence_audit.py", "--video", str(output),
        "--out", str(qa_dir / "frame_cadence_audit_latest.json")
    ], check=False)
    if cadence.returncode:
        qa_failures.append({"check": "frame_cadence", "returncode": cadence.returncode})
    ocr = subprocess.run([
        "python3", "tools/final_video_ocr_audit.py", "--video", str(output),
        "--out", str(qa_dir / "full_motion_ocr_audit_latest.json"), "--source-mode",
        "--allow-text", "__NO_TEXT_ALLOWED__", "--forbid-text", "__FORBIDDEN_TEXT__"
    ], check=False)
    if ocr.returncode:
        qa_failures.append({"check": "full_motion_ocr", "returncode": ocr.returncode})
    frame = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1.0",
        "-i", str(output), "-frames:v", "1", "-q:v", "2", str(qa_dir / "visual_review_latest.jpg")
    ], check=False)
    if frame.returncode:
        qa_failures.append({"check": "visual_frame_extract", "returncode": frame.returncode})
    sha = subprocess.check_output(["shasum", "-a", "256", str(output)], text=True).split()[0]
    receipt.update({
        "last_remote_status": "completed",
        "last_action": "supervisor_harvested_candidate_and_started_machine_qa" if not qa_failures else "supervisor_harvested_candidate_qa_failed_and_started_fallback",
        "last_action_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "last_action_evidence": str(qa_dir / "full_motion_ocr_audit_latest.json"),
        "previous_output_path": str(output),
        "previous_qa": str(qa_dir / "frame_cadence_audit_latest.json"),
        "previous_visual_review": str(qa_dir / "visual_identity_review_latest.json"),
        "previous_sha256": sha,
        "qa_status": "PASS" if not qa_failures else "FAIL_WITH_AUTOMATIC_FALLBACK",
        "qa_failures": qa_failures,
        "rollback": "candidate rejected; retain output and QA evidence, continue next candidate",
    })
    return output, "harvested" if not qa_failures else "harvested_with_qa_failures"


def submit_next(args: argparse.Namespace, receipt: dict, previous_task_id: str, previous_output: Path | None, reason: str) -> None:
    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    start_frame = Path(args.qa_dir) / "visual_review_latest.jpg"
    result = generate_video(SimpleNamespace(
        prompt=prompt,
        model="seedance-2.0-pro",
        duration=4,
        aspect_ratio="9:16",
        resolution="720p",
        count=1,
        start_frame=str(start_frame) if start_frame.exists() else None,
        end_frame=None,
    ))
    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"Giggle returned no task_id: {result}")
    history = list(receipt.get("previous_task_ids") or [])
    if previous_task_id and previous_task_id not in history:
        history.append(previous_task_id)
    receipt.update({
        "previous_task_ids": history,
        "previous_task_id": previous_task_id,
        "task_id": task_id,
        "status": "SUPERVISOR_RUNNING",
        "local_pid": os.getpid(),
        "next": "supervisor_poll_download_qa_and_refill",
        "last_action": "supervisor_submitted_next_candidate",
        "last_action_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "last_action_evidence": f"giggle_api_submit_response:{task_id}",
        "last_remote_status": "running",
        "activity_note": f"Persistent local supervisor PID {os.getpid()} owns this line; next candidate task is polled independently. reason={reason}",
        "output_path": None,
        "sha256": None,
        "qa": None,
        "visual_review": None,
    })
    if previous_output:
        receipt["previous_output_path"] = str(previous_output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--qa-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--interval", type=float, default=15.0)
    args = parser.parse_args()
    receipt_path = Path(args.receipt)
    while True:
        receipt = load(receipt_path)
        receipt["local_pid"] = os.getpid()
        task_id = receipt.get("task_id")
        data = query_task(SimpleNamespace(task_id=task_id)).get("data") or {}
        status = str(data.get("status") or "").lower()
        if status == "completed":
            previous_output, reason = harvest(args, receipt, task_id, data)
            submit_next(args, receipt, task_id, previous_output, reason)
        elif status in {"failed", "error", "cancelled"}:
            receipt.update({"last_remote_status": status, "failure_reason": data.get("error") or data.get("message") or status})
            submit_next(args, receipt, task_id, None, f"remote_{status}_fallback")
        else:
            receipt["status"] = "SUPERVISOR_RUNNING"
            receipt["last_remote_status"] = data.get("status") or "running"
            receipt["activity_note"] = f"Persistent local supervisor PID {os.getpid()} owns this line; remote task {task_id} is {data.get('status') or 'running'}."
            atomic_json(receipt_path, receipt)
        atomic_json(receipt_path, receipt)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
