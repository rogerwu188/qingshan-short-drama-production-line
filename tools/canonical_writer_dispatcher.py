#!/usr/bin/env python3
"""Create and close an exclusive, provenance-bound canonical Writer run.

This dispatcher owns the write lease and receipt boundary.  Claude/Cowork or
StoryClaw performs the actual language-model turn, but no E41+ output can pass
the script gate unless it was bracketed by this tool and bound to its receipt.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from canonical_writer_provenance import (
        ALLOWED_AGENT_IDS,
        GENERIC_MODEL_ALIASES,
        RECEIPT_SCHEMA,
        combined_rules_sha,
        sha256_bytes,
    )
except ModuleNotFoundError:
    from tools.canonical_writer_provenance import (
        ALLOWED_AGENT_IDS,
        GENERIC_MODEL_ALIASES,
        RECEIPT_SCHEMA,
        combined_rules_sha,
        sha256_bytes,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_DIR = ROOT / "workflow/claude_writer_agent/locks"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def lock_path(lock_dir: Path, episode: str, version: int) -> Path:
    return lock_dir / f"{episode}_V{version}.writer.lock.json"


def acquire_lock(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def start(args: argparse.Namespace) -> int:
    if args.agent_id not in ALLOWED_AGENT_IDS:
        raise SystemExit("WRITER_AGENT_NOT_AUTHORIZED")
    if args.model_id.strip().lower() in GENERIC_MODEL_ALIASES:
        raise SystemExit("WRITER_MODEL_ID_NOT_EXACT")
    if not args.provider.strip() or not args.session_or_task_id.strip():
        raise SystemExit("WRITER_RUNTIME_IDENTITY_INCOMPLETE")
    input_bundle = args.input_bundle.resolve()
    if not input_bundle.is_file():
        raise SystemExit("WRITER_INPUT_BUNDLE_MISSING")
    rules: list[dict[str, str]] = []
    for rule_path in args.rule:
        resolved = rule_path.resolve()
        if not resolved.is_file():
            raise SystemExit(f"WRITER_RULE_MISSING:{resolved}")
        rules.append({"path": str(resolved), "sha256": sha256_file(resolved)})
    if not rules:
        raise SystemExit("WRITER_RULES_MISSING")

    expected = f"WRITER-{args.episode}-V{args.version}-"
    if not args.writer_run_id.startswith(expected):
        raise SystemExit("WRITER_RUN_ID_EPISODE_VERSION_MISMATCH")
    receipt = args.receipt.resolve()
    if receipt.exists():
        raise SystemExit("WRITER_RECEIPT_ALREADY_EXISTS")
    lease = lock_path(args.lock_dir.resolve(), args.episode, args.version)
    started_at = now()
    acquire_lock(lease, {
        "schema": "qingshan.canonical_writer_write_lease.v1",
        "writer_run_id": args.writer_run_id,
        "episode": args.episode,
        "version": args.version,
        "receipt": str(receipt),
        "acquired_at": started_at,
    })
    payload = {
        "schema": RECEIPT_SCHEMA,
        "status": "RUNNING",
        "writer_run_id": args.writer_run_id,
        "episode": args.episode,
        "version": args.version,
        "agent_id": args.agent_id,
        "provider": args.provider,
        "model_id": args.model_id,
        "session_or_task_id": args.session_or_task_id,
        "input_bundle": {"path": str(input_bundle), "sha256": sha256_file(input_bundle)},
        "writer_rules": {"files": rules, "combined_sha256": combined_rules_sha(rules)},
        "authority_output": None,
        "started_at": started_at,
        "completed_at": None,
        "write_lease": str(lease),
    }
    try:
        atomic_json(receipt, payload)
    except BaseException:
        lease.unlink(missing_ok=True)
        raise
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def finish(args: argparse.Namespace) -> int:
    receipt = args.receipt.resolve()
    authority = args.authority.resolve()
    if not receipt.is_file() or not authority.is_file():
        raise SystemExit("WRITER_RECEIPT_OR_AUTHORITY_MISSING")
    payload = read_json(receipt)
    if payload.get("status") != "RUNNING":
        raise SystemExit("WRITER_RUN_NOT_RUNNING")
    lease = Path(str(payload.get("write_lease") or ""))
    if not lease.is_file():
        raise SystemExit("WRITER_WRITE_LEASE_MISSING")
    lease_payload = read_json(lease)
    if lease_payload.get("writer_run_id") != payload.get("writer_run_id"):
        raise SystemExit("WRITER_WRITE_LEASE_OWNER_MISMATCH")
    payload["status"] = "COMPLETED"
    payload["authority_output"] = {"path": str(authority), "sha256": sha256_file(authority)}
    payload["completed_at"] = now()
    atomic_json(receipt, payload)
    lease.unlink()
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def abort(args: argparse.Namespace) -> int:
    receipt = args.receipt.resolve()
    if not receipt.is_file():
        raise SystemExit("WRITER_RECEIPT_MISSING")
    payload = read_json(receipt)
    if payload.get("status") == "COMPLETED":
        raise SystemExit("COMPLETED_WRITER_RUN_CANNOT_BE_ABORTED")
    lease = Path(str(payload.get("write_lease") or ""))
    payload["status"] = "ABORTED"
    payload["completed_at"] = now()
    payload["abort_reason"] = args.reason
    atomic_json(receipt, payload)
    lease.unlink(missing_ok=True)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--episode", required=True)
    start_parser.add_argument("--version", required=True, type=int)
    start_parser.add_argument("--writer-run-id", required=True)
    start_parser.add_argument("--agent-id", required=True)
    start_parser.add_argument("--provider", required=True)
    start_parser.add_argument("--model-id", required=True)
    start_parser.add_argument("--session-or-task-id", required=True)
    start_parser.add_argument("--input-bundle", required=True, type=Path)
    start_parser.add_argument("--rule", action="append", default=[], type=Path)
    start_parser.add_argument("--receipt", required=True, type=Path)
    start_parser.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    start_parser.set_defaults(func=start)

    finish_parser = subparsers.add_parser("finish")
    finish_parser.add_argument("--receipt", required=True, type=Path)
    finish_parser.add_argument("--authority", required=True, type=Path)
    finish_parser.set_defaults(func=finish)

    abort_parser = subparsers.add_parser("abort")
    abort_parser.add_argument("--receipt", required=True, type=Path)
    abort_parser.add_argument("--reason", required=True)
    abort_parser.set_defaults(func=abort)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
