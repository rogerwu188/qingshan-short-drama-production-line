#!/usr/bin/env python3
"""Line-agnostic write side of the engineering knowledge base.

`tools/knowledge_registry.py` is deliberately read-only: it validates and exports.
This module is the shared writer every production line calls when an episode
closes (via `tools/line_upgrade_gate.py close`, or a line's own thin wrapper such
as `lines/nalu/runtime/tools/knowledge_sync.py`, which keeps its original CLI).

Guarantees (moved unchanged from the nalu writer):
  1. Every row it writes passes `knowledge_registry.validate` -- the registry, the
     markdown section and `knowledge/failure_memory.jsonl` are regenerated together
     and never allowed to drift apart.
  2. It is idempotent.  A row is keyed by its `sync_slug`; re-running an episode
     appends nothing new.
  3. It refuses to write a row it cannot make honest.  A candidate with no real
     `recovery` (or a REFERENCE_IMPLEMENTATION with no `implementation`) is reported
     as a gap for a human to fill, never padded with filler text.

Input: rows an agent/human authored for the episode in
`<runtime-root>/reports/<EP>_knowledge_candidates.json` (or
`<runtime-root>/runtime/reports/...`), plus optional extra rows.  There is
deliberately NO mechanical derivation from pipeline state (see
`candidates_from_evidence`).

It never writes an absolute path, a task id or a credential into the registry.
Standard library only; no provider requests.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REGISTRY = "configs/ENGINEERING_KNOWLEDGE_V1.json"
MARKDOWN = "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md"
FAILURE_MEMORY = "knowledge/failure_memory.jsonl"
DECISION_RECORD = "docs/decisions/DECISION_RECORDS.md"
REGRESSION = "tools/tests/test_knowledge_registry.py"

# Tokens the registry is forbidden from carrying (mirrors the test that guards it).
# Split so this file does not match its own scan -- same trick as
# tools/tests/test_nalu_runtime_port.py, which a literal would otherwise flag.
_HOME_PREFIX = "/Us" + "ers/"
FORBIDDEN_TOKENS = (_HOME_PREFIX, "/var/folders/", "Bearer ", "task_id", "remote_task_id")

STATUSES = {"REFERENCE_IMPLEMENTATION", "GUIDANCE_ONLY", "INTEGRATION_PENDING"}


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _next_id(rows: list[dict[str, Any]]) -> str:
    used = {int(m.group(1)) for row in rows if (m := re.fullmatch(r"K(\d{3})", str(row.get("id") or "")))}
    return f"K{(max(used) + 1 if used else 1):03d}"


def _clean(text: Any, limit: int = 1200) -> str:
    """One line, no newlines, no path/task tokens, bounded."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    for token in FORBIDDEN_TOKENS:
        if token in value:
            raise ValueError(f"KNOWLEDGE_FORBIDDEN_TOKEN:{token}")
    return value[:limit]


def candidates_from_evidence(root: Path, runtime_root: Path, episode: str) -> list[dict[str, Any]]:
    """Candidates that a human/agent authored for this episode, if any.

    There is deliberately NO mechanical derivation from pipeline state.  Two attempts
    proved it cannot work and this note exists so nobody tries a third time:

    * `open_decisions` is cross-episode boilerplate.  E08, E09 and E10 all carry the
      same D-1…D-14 rows (the pipeline's own decisions about how to run, not anything
      that happened in one episode), so deriving from it would mint ~14 duplicate rows
      per episode.
    * A stage that blocked and later passed has its `blockers` list CLEARED on the way
      out, so "the stage that blocked" is exactly the information state does not keep.

    What is left in state is status, attempt counts and run ids — none of which name a
    CAUSE.  Turning a failure into a rule ("抽象出错误原因") is a judgement step: it
    needs the session that saw the failure.  So the pipeline's job is to WRITE what it
    is handed, to insist that what it writes is honest, and to make a silent zero
    visible.  It is not to invent rules from a status table.
    """
    # `runtime_root` is already the runtime STATE root (the pipeline passes RT = RUNTIME/"runtime"),
    # same root the tools call RUNTIME_ROOT, so do not append another "runtime" here.
    authored_path = runtime_root / "reports" / f"{episode}_knowledge_candidates.json"
    if not authored_path.is_file():
        authored_path = runtime_root / "runtime" / "reports" / f"{episode}_knowledge_candidates.json"
    authored = _read_json(authored_path, [])
    out = [row for row in (authored or []) if isinstance(row, dict)]
    for row in out:
        row.setdefault("episode", episode)
        row.setdefault("slug", f"{episode}-{row.get('key') or row.get('failure_code') or len(out)}")
    return out



def assign_ids(rows: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each genuinely new candidate the next free id.

    Idempotence: a candidate whose `slug` is already recorded in `knowledge_sync_log`
    inside the registry is skipped, so re-running an episode appends nothing.
    """
    recorded = {row.get("sync_slug") for row in rows if row.get("sync_slug")}
    fresh = [c for c in candidates if c.get("slug") not in recorded]
    taken = [r for r in rows]
    for candidate in fresh:
        row = {k: v for k, v in candidate.items() if k != "episode"}
        row["id"] = _next_id(taken)
        row["sync_slug"] = candidate["slug"]
        taken.append(row)
    return fresh


def _row_for_registry(candidate: dict[str, Any], k_id: str) -> dict[str, Any]:
    row = {k: v for k, v in candidate.items() if k not in ("slug",)}
    row["id"] = k_id
    row["sync_slug"] = candidate["slug"]
    return row


def _markdown_section(row: dict[str, Any]) -> str:
    lines = [f"### {row['id']} — {row['stage']}", ""]
    lines.append(f"- **规则**：{row['rule']}")
    lines.append(f"- **教训**：{row['lesson']}")
    lines.append(f"- **恢复**：{row['recovery']}")
    impl = row.get("implementation") or []
    lines.append("- **实现**：" + ("、".join(f"`{p}`" for p in impl) if impl else "（未链接到代码；状态见下）"))
    lines.append(f"- **回归**：`{row['regression']}`")
    lines.append(f"- **证据**：{row['evidence']}")
    lines.append(f"- **授权**：{row['authority']}")
    lines.append(f"- **状态**：{row['status']}")
    lines.append("")
    return "\n".join(lines)


def sync(root: Path, runtime_root: Path, episode: str, extra: list[dict[str, Any]] | None = None,
         dry_run: bool = False) -> dict[str, Any]:
    """Append this episode's new knowledge rows; keep registry, markdown and jsonl in step."""
    registry_path = root / REGISTRY
    markdown_path = root / MARKDOWN
    data = _read_json(registry_path, None)
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError("KNOWLEDGE_REGISTRY_UNREADABLE")
    rows: list[dict[str, Any]] = data["rules"]

    state = _read_json(runtime_root / "pipeline_state" / f"{episode}.json", {}) or {}
    candidates = candidates_from_evidence(root, runtime_root, episode)
    for row in extra or []:
        if not isinstance(row, dict):
            continue
        row.setdefault("episode", episode)
        row.setdefault("slug", f"{episode}-manual-{row.get('key') or len(candidates)}")
        candidates.append(row)

    fresh = []
    for candidate in candidates:
        if candidate.get("slug") in {r.get("sync_slug") for r in rows}:
            continue
        if candidate.get("slug") in {c.get("slug") for c in fresh}:
            continue
        fresh.append(candidate)

    gaps = [c["slug"] for c in fresh
            if not _clean(c.get("recovery")) or (c.get("status") == "REFERENCE_IMPLEMENTATION"
                                                 and not c.get("implementation"))]
    fresh = [c for c in fresh if c["slug"] not in gaps]

    if dry_run or not fresh:
        return {"status": "DRY_RUN" if dry_run else "NO_NEW_KNOWLEDGE", "episode": episode,
                "new_ids": [], "candidates": len(candidates), "gaps": gaps,
                "rule_count": len(rows)}

    appended: list[dict[str, Any]] = []
    for candidate in fresh:
        row = {k: v for k, v in candidate.items() if k != "slug"}
        row["id"] = _next_id(rows)
        row["sync_slug"] = candidate["slug"]
        row.setdefault("regression", REGRESSION)
        row.setdefault("decision_record", DECISION_RECORD)
        row.setdefault("runtime_gate_added", False)
        row.setdefault("owner", "DEPLOYMENT_MAINTAINER")
        row.setdefault("scope", "generalizable")
        if row.get("failure_code"):
            row.setdefault("do_not_repeat", row["rule"])
        rows.append(row)
        appended.append(row)

    # Validate BEFORE touching anything on disk: a bad row must not leave the three
    # files inconsistent with each other.
    sys.path.insert(0, str(root / "tools"))  # the read-only validator lives in the engine
    import knowledge_registry as kr  # noqa: E402

    kr.validate(data, root)

    if not dry_run:
        registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with markdown_path.open("a", encoding="utf-8") as handle:
            for row in appended:
                handle.write(_markdown_section(row))
        memory = "".join(json.dumps(r, ensure_ascii=False) + "\n"
                         for r in kr.export_failure_memory(data))
        (root / FAILURE_MEMORY).write_text(memory, encoding="utf-8")

    return {"status": "SYNCED", "episode": episode, "new_ids": [r["id"] for r in appended],
            "candidates": len(candidates), "gaps": gaps, "rule_count": len(rows)}
