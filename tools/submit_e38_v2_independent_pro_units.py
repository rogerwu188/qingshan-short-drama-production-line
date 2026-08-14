#!/usr/bin/env python3
"""Submit E38 independent Pro/1080p units concurrently; preserve U08 serial gate."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from giggle_api_shot_runner import submit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804/E38_PRO_V1_RUN_PLAN.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def submit_one(item: dict) -> dict:
    prompt_path = Path(item["prompt_file"])
    refs = [Path(value) for value in item.get("references", [])]
    audio_refs = item.get("audio_references", [])
    if item.get("native_dialogue_required") and not audio_refs:
        raise RuntimeError("native dialogue requires frozen audio_references")
    response = submit(
        os.environ["GIGGLE_API_KEY"],
        prompt_path.read_text(encoding="utf-8"),
        refs,
        audio_refs,
        "seedance-2.0-pro",
        int(item["duration"]),
        "9:16",
        "1080p",
    )
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"submit response missing data.task_id: {json.dumps(response, ensure_ascii=False)}")
    out_dir = Path(item["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    receipt = out_dir / "submit_response.json"
    receipt.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "shot_id": item["shot_id"],
        "task_id": task_id,
        "status": "submitted",
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "duration": item["duration"],
        "edit_duration": item.get("edit_duration", item["duration"]),
        "prompt_sha256": sha(prompt_path),
        "audio_reference_count": len(audio_refs),
        "out_dir": str(out_dir),
        "receipt": str(receipt),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shots", default="", help="Comma-separated shot ids to submit")
    args = parser.parse_args()
    if not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise SystemExit("GIGGLE_API_KEY missing")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    ready = [
        row for row in plan
        if not row.get("dependency") and row.get("status", "READY_TO_SUBMIT") == "READY_TO_SUBMIT"
    ]
    if args.shots:
        selected = {value.strip() for value in args.shots.split(",") if value.strip()}
        ready = [row for row in ready if row["shot_id"] in selected]
    if args.limit:
        ready = ready[: args.limit]
    failures = []
    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {pool.submit(submit_one, item): item for item in ready}
        for future in as_completed(futures):
            item = futures[future]
            try:
                results.append(future.result())
            except (Exception, SystemExit) as exc:
                failures.append({"shot_id": item["shot_id"], "status": "submit_failed", "error": str(exc)})
    results.sort(key=lambda row: row["shot_id"])
    failures.sort(key=lambda row: row["shot_id"])
    payload = {
        "schema": "qingshan.e38_independent_pro_submit.v1",
        "episode": "E38",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "plan": str(args.plan),
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "concurrency": args.concurrency,
        "serial_gate": {"U08": "BLOCKED_UNTIL_U07_ACCEPTED_EXACT_TAIL_FRAME"},
        "status": "PASS_SUBMITTED" if results and not failures else "PARTIAL_OR_FAILED",
        "submitted": len(results),
        "failed": len(failures),
        "credits": {"pay": "PENDING_TASK_BOUND_QUERY", "refund": "PENDING", "net": "PENDING"},
        "results": results,
        "failures": failures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "submitted": len(results), "failed": len(failures)}, ensure_ascii=False))
    return 0 if results and not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
