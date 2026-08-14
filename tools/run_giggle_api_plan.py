#!/usr/bin/env python3
"""
Submit, poll, and download multiple Giggle omni-video shots from a run_plan.

The API key is read only from GIGGLE_API_KEY and is never written to disk.
The run_plan is produced by build_api_shot_package.py.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from giggle_api_shot_runner import download, query, submit
from script_readiness_gate import verify_script_readiness_report


def load_plan(path: str) -> List[Dict[str, Any]]:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("run_plan must be a JSON list.")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Run selected shots from a Giggle API run_plan.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--shots", nargs="*", help="Shot ids to run, e.g. 01 02 03. Defaults to all.")
    parser.add_argument("--model", default="seedance-2.0-pro")
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--timeout-minutes", type=int, default=35)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--script-gate-report", required=True)
    args = parser.parse_args()

    script_gate = verify_script_readiness_report(
        Path(args.beat_sheet),
        Path(args.script_gate_report),
    )
    if script_gate["status"] != "PASS":
        print(json.dumps({"status": "blocked_script_gate", **script_gate}, ensure_ascii=False))
        return 3

    api_key = os.environ.get("GIGGLE_API_KEY")
    if not api_key:
        raise SystemExit("Missing API key env var: GIGGLE_API_KEY")

    requested = {shot.zfill(2) for shot in (args.shots or [])}
    plan = [
        item for item in load_plan(args.plan)
        if not requested or str(item.get("shot_id", "")).zfill(2) in requested
    ]
    if not plan:
        raise SystemExit("No matching shots in run_plan.")

    pending: Dict[str, Dict[str, Any]] = {}
    for item in plan:
        shot_id = str(item["shot_id"]).zfill(2)
        out_dir = Path(item["out_dir"]).expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.skip_existing and list(out_dir.glob("result_*.mp4")):
            print(json.dumps({"shot_id": shot_id, "status": "skipped_existing", "out_dir": str(out_dir)}, ensure_ascii=False))
            continue
        prompt = Path(item["prompt_file"]).expanduser().read_text(encoding="utf-8")
        refs = [Path(path).expanduser().resolve() for path in item.get("references", [])]
        audio_refs = []
        for ref in item.get("audio_references", []):
            if isinstance(ref, dict):
                audio_refs.append(ref)
            elif isinstance(ref, str) and ref.startswith(("http://", "https://")):
                audio_refs.append(ref)
            else:
                audio_refs.append(Path(ref).expanduser().resolve())
        response = submit(api_key, prompt, refs, audio_refs, args.model, int(item.get("duration", 4)), args.ratio, args.resolution)
        (out_dir / "submit_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        task_id = (response.get("data") or {}).get("task_id")
        if not task_id:
            print(json.dumps({"shot_id": shot_id, "status": "submit_no_task_id", "response": response}, ensure_ascii=False))
            continue
        pending[shot_id] = {"task_id": task_id, "out_dir": out_dir}
        print(json.dumps({"shot_id": shot_id, "status": "submitted", "task_id": task_id}, ensure_ascii=False))

    deadline = time.time() + args.timeout_minutes * 60
    while pending and time.time() < deadline:
        for shot_id in list(pending):
            entry = pending[shot_id]
            response = query(api_key, entry["task_id"])
            out_dir: Path = entry["out_dir"]
            (out_dir / "last_query_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            data = response.get("data") or {}
            status = data.get("status")
            if status == "completed":
                urls = data.get("urls") or []
                for idx, url in enumerate(urls, 1):
                    download(url, out_dir / f"result_{idx:02d}.mp4")
                print(json.dumps({"shot_id": shot_id, "status": "completed", "files": [str(p) for p in sorted(out_dir.glob("result_*.mp4"))]}, ensure_ascii=False))
                pending.pop(shot_id, None)
            elif status in {"failed", "error", "canceled", "cancelled"}:
                print(json.dumps({"shot_id": shot_id, "status": status, "response": response}, ensure_ascii=False))
                pending.pop(shot_id, None)
        if pending:
            time.sleep(args.poll_seconds)

    if pending:
        print(json.dumps({"status": "timeout", "pending": sorted(pending)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
