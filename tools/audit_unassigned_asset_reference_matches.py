#!/usr/bin/env python3
"""Find episode-bearing local references to assets from unassigned remote tasks."""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
EPISODE_RE = re.compile(r"(?i)(?:^|[/_.-])(E(?:1[7-9]R?|2[0-8]))(?:[/_.-]|$)")
EPISODE_FIELD_RE = re.compile(r'(?i)["\']episode["\']\s*:\s*["\'](E(?:1[7-9]R?|2[0-8]))["\']')
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".txt", ".log", ".yaml", ".yml", ".csv", ".tsv"}


def resolve(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote-metadata-audit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    source = resolve(args.remote_metadata_audit)
    out = resolve(args.out)
    document = json.loads(source.read_text(encoding="utf-8"))
    token_to_tasks: dict[str, set[str]] = defaultdict(set)
    task_credits: dict[str, int] = {}
    for task in document.get("tasks") or []:
        task_id = str(task["task_id"])
        task_credits[task_id] = int(task.get("statement_credits") or 0)
        for asset in task.get("assets") or []:
            tokens = {str(asset.get("asset_id") or "")}
            for key in ("signed_url", "thumbnail_url"):
                url = str(asset.get(key) or "")
                if url:
                    tokens.add(Path(urlparse(url).path).name)
            for token in tokens - {""}:
                token_to_tasks[token].add(task_id)

    matches: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    token_pattern = re.compile("|".join(re.escape(token) for token in sorted(token_to_tasks, key=len, reverse=True))) if token_to_tasks else None
    excluded = {source.resolve(), out.resolve()}
    for root in (ROOT / "workflow", ROOT / "working_assets", ROOT / "qa"):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or path.resolve() in excluded:
                continue
            if "bridge_outgoing" in path.parts or "bridge_incoming" in path.parts:
                continue
            if "ACCOUNT_WINDOW" in path.name and "AUDIT" in path.name:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found_tokens = set(token_pattern.findall(content)) if token_pattern else set()
            if not found_tokens:
                continue
            relative = str(path.relative_to(ROOT))
            episodes = {match.group(1).upper() for match in EPISODE_RE.finditer(relative)}
            episodes.update(match.group(1).upper() for match in EPISODE_FIELD_RE.finditer(content))
            if not episodes:
                continue
            for token in found_tokens:
                for task_id in token_to_tasks[token]:
                    for episode in episodes:
                        matches[task_id][episode].add(relative)

    matched_tasks = [
        {
            "task_id": task_id,
            "statement_credits": task_credits[task_id],
            "episode_evidence": {
                episode: sorted(paths) for episode, paths in sorted(episode_paths.items())
            },
        }
        for task_id, episode_paths in sorted(matches.items())
    ]
    report = {
        "schema": "qingshan.unassigned_asset_reference_match_audit.v1",
        "status": "MATCHES_REQUIRE_REVIEW" if matched_tasks else "PASS_NO_EPISODE_BEARING_ASSET_REFERENCE_MATCHES",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_remote_metadata_audit": str(source.relative_to(ROOT)),
        "method": "EXACT_REMOTE_ASSET_ID_OR_URL_BASENAME_MATCH_IN_EPISODE_BEARING_LOCAL_TEXT",
        "tokens_scanned": len(token_to_tasks),
        "matched_task_count": len(matched_tasks),
        "matched_credits": sum(row["statement_credits"] for row in matched_tasks),
        "matches": matched_tasks,
        "remote_call_count": 0,
        "generation_call_count": 0,
        "new_credits": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "tokens": report["tokens_scanned"],
        "matched_tasks": report["matched_task_count"],
        "matched_credits": report["matched_credits"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
