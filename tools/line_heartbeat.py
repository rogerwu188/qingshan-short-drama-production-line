"""Atomic, machine-readable heartbeat updates for production line ledgers.

The external liveness probe remains the primary stall detector. This module
only makes submit/harvest state writes explicit and vocabulary-checked.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_BLOCKED_BY = frozenset(
    {
        "NONE",
        "REMOTE_GENERATION",
        "AWAITING_ROGER",
        "AWAITING_SUPERVISOR_REPLY",
        "SESSION_ENDED",
        "SCRIPT_DENSITY_GATE",
        "HUMAN_REVIEW",
        "VOICE_ISOLATION",
        "REMOTE_VOICE_ASSET_REGISTRATION",
        "PROVIDER_TIMEOUT",
        "PLATFORM_BACKFILL",
        "CREDIT_OR_QUOTA",
    }
)


def timestamp(now: str | None = None) -> str:
    return now or datetime.now().astimezone().isoformat(timespec="seconds")


def validate_blocked_by(value: str) -> str:
    if value not in ALLOWED_BLOCKED_BY:
        raise ValueError(f"blocked_by must be one of {sorted(ALLOWED_BLOCKED_BY)}: {value!r}")
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def record_line_heartbeat(
    ledger_path: Path,
    line_id: str,
    *,
    active_work: str,
    blocked_by: str = "NONE",
    blocker_ref: str | None = None,
    evidence_ref: str | None = None,
    next_work: str | None = None,
    state: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Update one parallel line and fail before writing on invalid state."""
    validate_blocked_by(blocked_by)
    if blocked_by == "NONE" and blocker_ref:
        raise ValueError("blocker_ref is only allowed when blocked_by is not NONE")
    if blocked_by != "NONE" and not blocker_ref:
        raise ValueError("blocker_ref is required when blocked_by is not NONE")

    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    lines = payload.get("parallel_lines") or []
    line = next((item for item in lines if item.get("line_id") == line_id), None)
    if line is None:
        raise ValueError(f"line_id not found in {ledger_path}: {line_id}")

    observed_at = timestamp(now)
    line["active_work"] = active_work
    line["blocked_by"] = blocked_by
    line["blocker_ref"] = blocker_ref
    line["last_heartbeat_at"] = observed_at
    line["last_progress_at"] = observed_at
    if evidence_ref is not None:
        line["evidence_ref"] = evidence_ref
    if next_work is not None:
        line["next_work"] = next_work
    if state is not None:
        line["state"] = state
    if blocked_by == "NONE":
        line.pop("blocked_since_at", None)
    else:
        line.setdefault("blocked_since_at", observed_at)
    payload["updated_at"] = observed_at
    write_json_atomic(ledger_path, payload)
    return line
