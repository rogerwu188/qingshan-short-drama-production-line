#!/usr/bin/env python3
"""Write one truthful per-episode gate invocation result for the dashboard."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# F-R530-01：改名之后连目录项一起落盘。单一实现在 tools/durable_rename.py。
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from durable_rename import durable_replace  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_STATUSES = {"PASS", "FAIL", "N_A", "PENDING_MANUAL"}


def write_gate_result(
    episode: str,
    gate_id: str,
    *,
    invoked: bool,
    status: str,
    runner: str,
    evidence: str | Path,
    score: int | float | None = None,
    root: Path = ROOT,
    extra: dict[str, Any] | None = None,
) -> Path:
    episode = str(episode).upper()
    status = str(status).upper()
    if not re.fullmatch(r"E\d+R?", episode):
        raise ValueError(f"invalid episode id: {episode}")
    if invoked is not True:
        raise ValueError("invoked=false must not be written to the execution matrix")
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"invalid gate result status: {status}")
    if not gate_id or "/" in gate_id or ".." in gate_id:
        raise ValueError(f"invalid gate id: {gate_id}")
    payload = {
        "schema": "qingshan.gate_result.v1",
        "gate_id": gate_id,
        "episode": episode,
        "invoked": True,
        "status": status,
        "score": score,
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runner": runner,
        "evidence": str(evidence),
    }
    if extra:
        payload.update(extra)
    out = root / "qa" / "gate_results" / episode / f"{gate_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    # Serialise before touching the filesystem. A payload that cannot be encoded
    # then fails with its own TypeError and creates no temporary file at all,
    # instead of failing halfway through a write and leaving cleanup to decide
    # which error the caller gets to see.
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    fd, temp_name = tempfile.mkstemp(prefix=f".{gate_id}.", suffix=".tmp", dir=out.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        durable_replace(temp_name, out)
    except BaseException:
        _discard_temporary(temporary)
        raise
    return out


def _discard_temporary(temporary: Path) -> None:
    """Best-effort cleanup that never masks the real error with its own.

    The previous ``finally: if exists: unlink`` did mask it. On the production
    mount ``unlink`` is refused outright (``PermissionError [Errno 1]``), so the
    cleanup raised on its way out and *replaced* the exception the caller needed
    to see -- a non-serialisable payload surfaced as "Operation not permitted".
    Same ladder as ``tools/episode_stage_gate_runner._discard_temporary`` and
    the dispatcher's: remove it, else rename it out of the way, else give up
    quietly. Cleanup is a courtesy; it never gets to speak over the real error.
    """
    try:
        temporary.unlink()
        return
    except FileNotFoundError:
        return
    except OSError:
        pass
    try:
        temporary.replace(temporary.with_name(f"{temporary.name}.discarded"))
    except OSError:
        pass
