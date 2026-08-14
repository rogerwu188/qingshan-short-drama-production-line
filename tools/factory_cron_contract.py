#!/usr/bin/env python3
"""Validate factory cron specs before StoryClaw schedules them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


FACTORY_AGENTS = {
    "qingshan-producer-supervisor",
    "qingshan-claude-writer",
    "qingshan-ai-drama-pipeline",
    "qingshan-agent-cut-cloud",
    "qingshan-ai-aduit",
}
ABSOLUTE_PROJECT_FIELDS = (
    "project_root",
    "project_facts_abs",
    "project_checkpoint_abs",
)


def validate_cron_spec(spec: dict) -> list[str]:
    failures: list[str] = []
    owner = str(spec.get("owner_agent_id", ""))
    if owner not in FACTORY_AGENTS:
        failures.append("owner_not_factory_agent")
    if spec.get("session_discovery_required") is not False:
        failures.append("session_discovery_must_be_false")
    route_mode = str(spec.get("route_mode", ""))
    if route_mode not in {"owner_current", "direct_agent_id"}:
        failures.append("invalid_route_mode")
    target = str(spec.get("target_agent_id", ""))
    if route_mode == "direct_agent_id" and target not in FACTORY_AGENTS:
        failures.append("direct_target_not_factory_agent")
    if route_mode == "owner_current" and target != owner:
        failures.append("owner_current_target_mismatch")
    for field in ABSOLUTE_PROJECT_FIELDS:
        value = str(spec.get(field, "")).strip()
        if not value:
            failures.append(f"missing:{field}")
        elif not Path(value).is_absolute():
            failures.append(f"not_absolute:{field}")
    payload = str(spec.get("payload", ""))
    for field in ABSOLUTE_PROJECT_FIELDS:
        value = str(spec.get(field, "")).strip()
        if value and value not in payload:
            failures.append(f"payload_missing_bound_path:{field}")
    forbidden = ("sessions.list", "sessions_list", "session search", "名称搜索")
    if any(token in payload for token in forbidden):
        failures.append("payload_uses_session_discovery")
    if not str(spec.get("idempotency_key", "")).strip():
        failures.append("missing:idempotency_key")
    if spec.get("job_kind") == "writer_staged_facts":
        if owner != "qingshan-producer-supervisor":
            failures.append("writer_staged_dispatch_owner_must_be_producer")
        if target != "qingshan-claude-writer" or route_mode != "direct_agent_id":
            failures.append("writer_staged_dispatch_must_direct_route_writer")
        dispatch_mode = spec.get("dispatch_mode")
        if dispatch_mode not in {"completion_chained_one_shot", "watchdog"}:
            failures.append("writer_staged_dispatch_mode_invalid")
        if spec.get("non_overlap_required") is not True:
            failures.append("writer_staged_non_overlap_required")
        if spec.get("max_phases_per_tick") != 1:
            failures.append("writer_staged_one_phase_per_tick_required")
        if spec.get("heartbeat_noop_seconds") != 180:
            failures.append("writer_staged_heartbeat_noop_must_be_180")
        if spec.get("retry_backoff_seconds") != [60, 120, 240, 480, 900]:
            failures.append("writer_staged_retry_backoff_invalid")
        if dispatch_mode == "completion_chained_one_shot":
            delay = spec.get("one_shot_delay_seconds")
            if not isinstance(delay, int) or not 5 <= delay <= 60:
                failures.append("writer_staged_one_shot_delay_invalid")
            if spec.get("auto_advance_on_pass") is not True:
                failures.append("writer_staged_auto_advance_required")
        if dispatch_mode == "watchdog":
            interval = spec.get("interval_seconds")
            if not isinstance(interval, int) or not 300 <= interval <= 600:
                failures.append("writer_staged_watchdog_interval_invalid")
            if spec.get("stale_after_seconds") != 420:
                failures.append("writer_staged_watchdog_stale_after_invalid")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    failures = validate_cron_spec(spec)
    result = {
        "schema": "qingshan.factory.cron_contract.v1",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
