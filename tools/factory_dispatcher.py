#!/usr/bin/env python3
"""Persistent, idempotent dispatcher for the five-agent cloud factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.agent_task_journal import append_task_record
except ModuleNotFoundError:  # Direct execution from the packaged tools directory.
    from agent_task_journal import append_task_record


REQUIRED_FIELDS = {
    "event_id",
    "tenant_id",
    "project_id",
    "episode_id",
    "stage",
    "from_agent",
    "to_agent",
    "admission_sha",
    "artifact_sha",
    "idempotency_key",
    "attempt",
    "created_at",
    "not_before",
    "expires_at",
}
FACTORY_AGENTS = {
    "qingshan-producer-supervisor",
    "qingshan-claude-writer",
    "qingshan-ai-drama-pipeline",
    "qingshan-agent-cut-cloud",
    "qingshan-ai-aduit",
}
ROUTE_REGISTRY_SCHEMA = "qingshan.factory.agent_routes.v1"
WRITER_PATH_FIELDS = (
    "project_root",
    "project_facts_abs",
    "project_checkpoint_abs",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    path.with_suffix(path.suffix + ".sha256").write_text(
        sha256_bytes(data) + "\n", encoding="ascii"
    )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def default_route_registry() -> dict:
    return {
        "schema": ROUTE_REGISTRY_SCHEMA,
        "dispatch_mode": "direct_agent_id",
        "session_discovery_required": False,
        "targets": {
            agent_id: {
                "agent_id": agent_id,
                "transport": "direct_agent_id",
            }
            for agent_id in sorted(FACTORY_AGENTS)
        },
        "created_at": now(),
    }


def route_registry_path(shared_root: Path) -> Path:
    return shared_root / "factory/dispatcher/agent_routes.json"


def load_route_registry(shared_root: Path) -> dict:
    path = route_registry_path(shared_root)
    if not path.is_file():
        atomic_json(path, default_route_registry())
    registry = load_json(path)
    if registry.get("schema") != ROUTE_REGISTRY_SCHEMA:
        raise ValueError("unsupported agent route registry schema")
    if registry.get("session_discovery_required") is not False:
        raise ValueError("factory routes must not depend on session discovery")
    if not isinstance(registry.get("targets"), dict):
        raise ValueError("agent route registry targets must be an object")
    return registry


def resolve_agent_route(shared_root: Path, target: str) -> dict:
    registry = load_route_registry(shared_root)
    route = registry["targets"].get(target)
    if not isinstance(route, dict):
        raise ValueError(f"missing direct route for {target}")
    agent_id = str(route.get("agent_id", "")).strip()
    if not agent_id:
        raise ValueError(f"missing agent_id for {target}")
    transport = str(route.get("transport", "direct_agent_id"))
    if transport not in {"direct_agent_id", "fixed_session_key"}:
        raise ValueError(f"unsupported route transport for {target}: {transport}")
    session_key = str(route.get("session_key", "")).strip()
    if transport == "fixed_session_key" and not session_key:
        raise ValueError(f"missing fixed session_key for {target}")
    return {
        "target": target,
        "agent_id": agent_id,
        "session_key": session_key,
        "transport": transport,
        "session_discovery_used": False,
        "registry_path": str(route_registry_path(shared_root).resolve()),
    }


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_event(event: dict, event_path: Path, shared_root: Path) -> list[str]:
    failures = [f"missing:{field}" for field in sorted(REQUIRED_FIELDS - set(event))]
    if event.get("from_agent") != "qingshan-producer-supervisor":
        failures.append("from_agent_not_controller")
    if event.get("to_agent") not in FACTORY_AGENTS:
        failures.append("target_not_factory_agent")
    if event.get("attempt", -1) < 0:
        failures.append("invalid_attempt")
    try:
        if parse_time(str(event["expires_at"])) <= datetime.now(timezone.utc):
            failures.append("expired")
        if parse_time(str(event["not_before"])) > datetime.now(timezone.utc):
            failures.append("not_before")
    except (KeyError, TypeError, ValueError):
        failures.append("invalid_time")
    try:
        event_path.resolve().relative_to(shared_root.resolve())
    except ValueError:
        failures.append("event_path_outside_shared_root")
    if (
        event.get("to_agent") == "qingshan-claude-writer"
        and event.get("stage") in {"SOURCE", "FULL_SERIES_WRITER"}
    ):
        for field in WRITER_PATH_FIELDS:
            value = str(event.get(field, "")).strip()
            if not value:
                failures.append(f"missing:{field}")
            elif not Path(value).is_absolute():
                failures.append(f"not_absolute:{field}")
    return failures


def event_digest(event: dict) -> str:
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(canonical)


def event_key(event: dict) -> str:
    return ":".join(
        str(event.get(field, ""))
        for field in ("tenant_id", "project_id", "episode_id", "stage")
    ) + ":" + event_digest(event)


def dispatch_command(
    event_path: Path, target: str, shared_root: Path
) -> tuple[str, dict]:
    try:
        route = resolve_agent_route(shared_root, target)
    except ValueError as exc:
        return "BLOCKED_INVALID_AGENT_ROUTE", {
            "reason": str(exc),
            "adapter_required": False,
            "session_discovery_used": False,
        }
    template = os.environ.get("QINGSHAN_AGENT_WAKE_COMMAND", "").strip()
    if not template:
        return "BLOCKED_NO_WAKE_ADAPTER", {
            "reason": "QINGSHAN_AGENT_WAKE_COMMAND is not configured",
            "adapter_required": True,
            "route": route,
        }
    try:
        command = template.format(
            agent=shlex.quote(route["agent_id"]),
            agent_id=shlex.quote(route["agent_id"]),
            session_key=shlex.quote(route["session_key"]),
            event=shlex.quote(str(event_path.resolve())),
        )
    except (IndexError, KeyError, ValueError) as exc:
        return "BLOCKED_WAKE_ADAPTER_CONFIG", {
            "reason": f"wake adapter template error: {exc}",
            "adapter_required": True,
            "route": route,
        }
    completed = subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    return (
        "DISPATCHED" if completed.returncode == 0 else "DISPATCH_FAILED",
        {
            "adapter_required": False,
            "route": route,
            "exit_code": completed.returncode,
            "stdout_sha256": sha256_bytes(completed.stdout.encode("utf-8")),
            "stderr_sha256": sha256_bytes(completed.stderr.encode("utf-8")),
        },
    )


def discover_events(shared_root: Path) -> list[Path]:
    return sorted(shared_root.glob("tenants/*/control/events/*.json"))


def write_active_job_binding(
    shared_root: Path,
    event_path: Path,
    event: dict,
    route: dict,
) -> Path:
    target = str(event["to_agent"])
    binding_path = shared_root / f"factory/agents/{target}/active_job.json"
    project_paths = {
        field: event.get(field)
        for field in WRITER_PATH_FIELDS
        if event.get(field)
    }
    payload = {
        "schema": "qingshan.factory.active_job_binding.v1",
        "status": "DISPATCHED",
        "agent_id": route["agent_id"],
        "job_id": event.get("idempotency_key"),
        "event_path": str(event_path.resolve()),
        "event_sha": event_digest(event),
        "project_id": event.get("project_id"),
        "episode_id": event.get("episode_id"),
        "stage": event.get("stage"),
        "idempotency_key": event.get("idempotency_key"),
        "project_paths": project_paths,
        "route": route,
        "updated_at": now(),
    }
    atomic_json(binding_path, payload)
    return binding_path


def dispatch_once(shared_root: Path, dry_run: bool = False) -> dict:
    index_path = shared_root / "factory/dispatcher/dispatch_index.json"
    index = load_json(index_path) if index_path.is_file() else {
        "schema": "qingshan.factory.dispatch_index.v1",
        "events": {},
    }
    outcomes: list[dict] = []
    for path in discover_events(shared_root):
        event = load_json(path)
        key = event_key(event)
        prior = index["events"].get(key)
        if prior and prior.get("status") in {"DISPATCHED", "CLAIMED", "PASS"}:
            continue
        failures = validate_event(event, path, shared_root)
        if failures:
            status = "DEFERRED" if failures == ["not_before"] else "NACK"
            detail = {"failures": failures}
        elif dry_run:
            try:
                route = resolve_agent_route(shared_root, str(event["to_agent"]))
                status, detail = "DRY_RUN_READY", {
                    "adapter_required": False,
                    "route": route,
                }
            except ValueError as exc:
                status, detail = "BLOCKED_INVALID_AGENT_ROUTE", {
                    "adapter_required": False,
                    "reason": str(exc),
                    "session_discovery_used": False,
                }
        else:
            status, detail = dispatch_command(
                path, str(event["to_agent"]), shared_root
            )
            if status == "DISPATCHED":
                binding_path = write_active_job_binding(
                    shared_root,
                    path,
                    event,
                    detail["route"],
                )
                detail["active_job_binding"] = str(binding_path.resolve())
                journal = append_task_record(
                    shared_root,
                    str(event["to_agent"]),
                    job_id=str(event["idempotency_key"]),
                    status="DISPATCHED",
                    event=str(event["stage"]),
                    details={
                        "event_id": event.get("event_id"),
                        "event_sha": event_digest(event),
                        "active_job_binding": str(binding_path.resolve()),
                        "route_transport": detail["route"]["transport"],
                    },
                )
                detail["task_journal"] = journal["journal_path"]
                detail["task_journal_record_sha"] = journal["record"][
                    "record_sha"
                ]
        record = {
            "event_id": event.get("event_id"),
            "event_sha": event_digest(event),
            "idempotency_key": event.get("idempotency_key"),
            "target": event.get("to_agent"),
            "status": status,
            "recorded_at": now(),
            **detail,
        }
        index["events"][key] = record
        outcomes.append(record)
    index["updated_at"] = now()
    atomic_json(index_path, index)
    summary = {
        "schema": "qingshan.factory.dispatch_tick.v1",
        "status": "PASS" if all(
            row["status"] in {"DISPATCHED", "DRY_RUN_READY", "DEFERRED"}
            for row in outcomes
        ) else "BLOCKED",
        "shared_root": str(shared_root.resolve()),
        "processed": len(outcomes),
        "outcomes": outcomes,
        "recorded_at": now(),
    }
    receipt = (
        shared_root
        / "factory/dispatcher/receipts"
        / f"tick-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    atomic_json(receipt, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-root", type=Path)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configured_root = os.environ.get("QINGSHAN_FACTORY_SHARED_ROOT")
    shared_root = (
        args.shared_root
        or (Path(configured_root) if configured_root else None)
        or Path.home() / ".openclaw/shared/ai-drama-factory"
    ).expanduser().resolve()
    shared_root.mkdir(parents=True, exist_ok=True)
    while True:
        result = dispatch_once(shared_root, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False))
        if args.once:
            return 0 if result["status"] == "PASS" else 2
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
