#!/usr/bin/env python3
"""Run independent source-level QA checks concurrently and write one receipt."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_check(name: str, command: list[str], out: Path, video: str) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return {
        "check": name,
        "video": video,
        "command": command,
        "returncode": proc.returncode,
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
        "out": str(out),
        "started_at": started,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--video", action="append", nargs=2, metavar=("LABEL", "PATH"), required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--ocr-allow-text", action="append", default=[])
    parser.add_argument("--ocr-forbid-text", action="append", default=[])
    args = parser.parse_args()

    receipt = {
        "schema": "qingshan.parallel_source_qa.v1",
        "episode": args.episode,
        "status": "RUNNING",
        "parallel_policy": "all independent source checks run concurrently",
        "videos": [],
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    jobs: list[tuple[str, list[str], Path, str]] = []
    for label, raw_path in args.video:
        video = (ROOT / raw_path).resolve() if not Path(raw_path).is_absolute() else Path(raw_path)
        base = args.out.parent / label
        cadence = base.with_name(base.name + "_cadence.json")
        ocr = base.with_name(base.name + "_ocr.json")
        jobs.append((label, [sys.executable, "tools/frame_cadence_audit.py", "--video", str(video), "--out", str(cadence), "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC"], cadence, str(video)))
        ocr_command = [sys.executable, "tools/final_video_ocr_audit.py", "--video", str(video), "--out", str(ocr), "--source-mode"]
        for token in args.ocr_allow_text:
            ocr_command.extend(["--allow-text", token])
        for token in args.ocr_forbid_text:
            ocr_command.extend(["--forbid-text", token])
        jobs.append((label, ocr_command, ocr, str(video)))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers), thread_name_prefix="source-qa") as pool:
        futures = [pool.submit(run_check, f"{label}:{cmd[2]}", cmd, out, video) for label, cmd, out, video in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    by_video: dict[str, dict] = {}
    for result in results:
        label = result["check"].split(":", 1)[0]
        item = by_video.setdefault(label, {"label": label, "video": result["video"], "checks": []})
        item["checks"].append(result)
    receipt["videos"] = sorted(by_video.values(), key=lambda item: item["label"])
    receipt["status"] = "PASS" if all(check["returncode"] == 0 for item in receipt["videos"] for check in item["checks"]) else "FAIL"
    receipt["finished_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"episode": args.episode, "status": receipt["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
