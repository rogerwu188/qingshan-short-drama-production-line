#!/usr/bin/env python3
"""Compile a review-many request from a harvested dialogue submit batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fallback-manifest", type=Path)
    args = parser.parse_args()
    manifest = read(args.manifest)
    status = read(args.status_report)
    task_by_id = {row["dialogue_id"]: row for row in manifest.get("tasks", [])}
    fallback_ids = set()
    if args.fallback_manifest:
        fallback_ids = {row["dialogue_id"] for row in read(args.fallback_manifest).get("tasks", [])}
    items = []
    failures = []
    for harvested in status.get("results", []):
        dia_id = harvested.get("dialogue_id")
        task = task_by_id.get(dia_id)
        files = harvested.get("downloaded_files") or []
        if not task or len(files) != 1:
            failures.append({"dialogue_id": dia_id, "downloaded_file_count": len(files), "manifest_task": bool(task)})
            continue
        path = Path(files[0]).resolve()
        items.append(
            {
                "path": str(path),
                "scope": "shot",
                "kind": "video",
                "importance": "important" if dia_id in fallback_ids else "standard",
                "pass_score": 4.0 if dia_id in fallback_ids else 3.5,
                "clip_id": f"{manifest.get('episode', 'EP')}-{dia_id}-MULTIMODAL",
                "metadata": {
                    "episode": manifest.get("episode"),
                    "dialogue_id": dia_id,
                    "beat_id": task.get("beat_id"),
                    "speaker": task.get("speaker"),
                    "expected_text": task.get("text"),
                    "status": "CANDIDATE_NOT_ADMITTED",
                    "visual_identity_qa_required": dia_id in fallback_ids,
                },
                "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            }
        )
    payload = {"items": sorted(items, key=lambda row: row["metadata"]["dialogue_id"])}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {"status": "PASS" if len(items) == len(task_by_id) and not failures else "FAIL", "item_count": len(items), "expected": len(task_by_id), "failures": failures, "out": str(args.out)}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
