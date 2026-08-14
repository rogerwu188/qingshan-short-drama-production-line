#!/usr/bin/env python3
"""Inventory recoverable task ids for a legacy episode without calling Giggle."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
TASK_KEYS = {"task_id", "taskid", "project_id", "projectid", "remote_task_id"}
TASK_LIST_KEYS = {"task_ids", "taskids", "remote_task_ids"}


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def collect_ids(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = str(key).lower()
            if normalized in TASK_KEYS and isinstance(value, str) and UUID_RE.fullmatch(value):
                found.add(value.lower())
            elif normalized in TASK_LIST_KEYS and isinstance(value, list):
                found.update(str(item).lower() for item in value if isinstance(item, str) and UUID_RE.fullmatch(item))
            collect_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_ids(item, found)


def ids_from_file(path: Path) -> set[str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    collect_ids(document, found)
    return found


def known_ids(paths: list[str]) -> set[str]:
    found: set[str] = set()
    for value in paths:
        collect_ids(json.loads(resolve(value).read_text(encoding="utf-8")), found)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--known", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    episode = args.episode.lower()
    candidates: dict[str, set[str]] = {}
    parse_errors = []
    scanned_files = 0
    matched_files = 0
    for root_arg in args.root:
        root = resolve(root_arg)
        for path in root.rglob("*.json"):
            if not path.is_file():
                continue
            scanned_files += 1
            relative = str(path.relative_to(ROOT))
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if episode not in relative.lower() and episode not in raw.lower():
                continue
            matched_files += 1
            try:
                recovered = ids_from_file(path)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                parse_errors.append({"path": relative, "error": str(exc)})
                continue
            for task_id in recovered:
                candidates.setdefault(task_id, set()).add(relative)

    already_known = known_ids(args.known)
    recovered_ids = sorted(candidates)
    new_ids = sorted(set(recovered_ids) - already_known)
    report = {
        "schema": "qingshan.episode_task_id_inventory.v1",
        "episode": args.episode.upper(),
        "status": "PASS" if not parse_errors else "PASS_WITH_PARSE_WARNINGS",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "method": "RECURSIVE_JSON_TASK_KEY_UUID_SCAN_NO_REMOTE_CALL",
        "roots": args.root,
        "known_sources": args.known,
        "scanned_json_file_count": scanned_files,
        "episode_matched_json_file_count": matched_files,
        "recovered_task_id_count": len(recovered_ids),
        "already_known_task_id_count": len(set(recovered_ids) & already_known),
        "new_candidate_task_id_count": len(new_ids),
        "new_candidate_task_ids": [
            {"task_id": task_id, "source_files": sorted(candidates[task_id])}
            for task_id in new_ids
        ],
        "parse_errors": parse_errors,
        "generation_call_count": 0,
        "new_credits": 0,
    }
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "scanned": scanned_files,
        "matched_files": matched_files,
        "recovered": len(recovered_ids),
        "known": report["already_known_task_id_count"],
        "new": len(new_ids),
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
