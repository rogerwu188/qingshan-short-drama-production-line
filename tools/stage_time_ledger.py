#!/usr/bin/env python3
"""stage_time_ledger.py — per-stage time/credit ledger (Roger 2026-09-25,
codex_docs/ROGER-20260925-NALU-LINE-OPTIMIZATION.md §六, effective E09).

Append-only: one JSON line per stage-END event to workflow/<line>/<EP>/TIME_LEDGER.jsonl. Hooked
from nalu_pipeline.py's run_episode() stage loop, right after a stage's terminal status is known
(started_at/finished_at already exist there — this module adds no new timer or poller).

``breakdown`` (compute/remote_wait/human_wait/idle) is a documented approximation: the
orchestrator does not measure per-stage compute time or distinguish provider-wait from idle time
today, so this module infers only what it can from data that already exists on a stage's recorded
steps:
  * remote_wait  — the stage ran at least one paid/provider step (Ctx.run(..., paid=True))
  * human_wait   — the stage's terminal status is REVIEW_REQUIRED, or its status details mention
                   a human-review sub-stage (Q1/Q2/post_gen_plot/action_role/identity review)
  * idle         — neither of the above
  * compute      — always 0 in this version; no per-stage compute-only signal exists to measure it
A stage is credited to exactly one of these four buckets for its whole wall_seconds — this is a
coarse, honest classification, not a real breakdown of time spent within the stage.

SKIPPED_ALREADY_PASS transitions must never call append_event — no work happened, no event.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "nalu.stage_time_ledger.v1"
_HUMAN_REVIEW_MARKERS = ("q1", "q2", "post_gen_plot", "action_role", "identity_review",
                         "review_required", "final_audience_review")


def _iso_to_epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def wall_seconds(started_at: str | None, finished_at: str | None) -> float:
    start, end = _iso_to_epoch(started_at), _iso_to_epoch(finished_at)
    if start is None or end is None or end < start:
        return 0.0
    return round(end - start, 3)


def classify_breakdown(status: str, steps: list[dict[str, Any]] | None, seconds: float) -> dict[str, float]:
    """Assigns the whole stage's wall_seconds to exactly one bucket — see module docstring."""
    steps = steps or []
    is_human_wait = status == "REVIEW_REQUIRED" or any(
        marker in str(step.get("name") or "").lower() for step in steps for marker in _HUMAN_REVIEW_MARKERS
    )
    is_remote_wait = any(bool(step.get("paid")) for step in steps)
    if is_human_wait:
        return {"compute": 0.0, "remote_wait": 0.0, "human_wait": seconds, "idle": 0.0}
    if is_remote_wait:
        return {"compute": 0.0, "remote_wait": seconds, "human_wait": 0.0, "idle": 0.0}
    return {"compute": 0.0, "remote_wait": 0.0, "human_wait": 0.0, "idle": seconds}


def ledger_path(episode: str, *, work_root: Path) -> Path:
    return work_root / episode / "TIME_LEDGER.jsonl"


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def append_event(*, episode: str, stage: str, status: str, started_at: str | None,
                 finished_at: str | None, credits: int, attempt: int,
                 steps: list[dict[str, Any]] | None = None, work_root: Path,
                 note: str = "") -> dict[str, Any]:
    """Writes one stage-END event and returns it (including the running episode cumulative
    totals). Caller (nalu_pipeline.py) must not call this for a SKIPPED_ALREADY_PASS transition."""
    path = ledger_path(episode, work_root=work_root)
    seconds = wall_seconds(started_at, finished_at)
    prior = _read_events(path)
    cumulative_seconds = round(sum(float(e.get("wall_seconds") or 0) for e in prior) + seconds, 3)
    cumulative_credits = sum(int(e.get("credits") or 0) for e in prior) + int(credits or 0)
    event = {
        "schema": SCHEMA, "episode": episode, "stage": stage, "event": "END",
        "started_at": started_at, "ended_at": finished_at, "wall_seconds": seconds,
        "breakdown": classify_breakdown(status, steps, seconds),
        "credits": int(credits or 0),
        "episode_cumulative_seconds": cumulative_seconds,
        "episode_cumulative_credits": cumulative_credits,
        "attempt": int(attempt), "status": status, "note": note,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def episode_summary(episode: str, *, work_root: Path) -> dict[str, Any]:
    """Read-only per-episode rollup for print_status()/reports: latest event per stage, plus
    episode totals. Reroll/rework attempts all stay in the file (append-only); the summary uses
    each stage's LAST recorded attempt."""
    events = _read_events(ledger_path(episode, work_root=work_root))
    by_stage: dict[str, dict[str, Any]] = {}
    for event in events:
        by_stage[event.get("stage")] = event  # last write per stage wins
    total_seconds = round(sum(float(e.get("wall_seconds") or 0) for e in by_stage.values()), 3)
    total_credits = sum(int(e.get("credits") or 0) for e in by_stage.values())
    breakdown_totals = {"compute": 0.0, "remote_wait": 0.0, "human_wait": 0.0, "idle": 0.0}
    for event in by_stage.values():
        for key, value in (event.get("breakdown") or {}).items():
            breakdown_totals[key] = breakdown_totals.get(key, 0.0) + float(value or 0)
    return {
        "episode": episode, "stages": by_stage, "total_wall_seconds": total_seconds,
        "total_credits": total_credits, "breakdown_totals": {k: round(v, 3) for k, v in breakdown_totals.items()},
        "event_count": len(events),
    }
