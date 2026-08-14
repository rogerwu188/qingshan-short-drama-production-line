#!/usr/bin/env python3
"""Write one truthful per-episode gate invocation result for the dashboard."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


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
    fd, temp_name = tempfile.mkstemp(prefix=f".{gate_id}.", suffix=".tmp", dir=out.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, out)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return out
