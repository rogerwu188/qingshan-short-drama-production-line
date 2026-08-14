#!/usr/bin/env python3
"""Turn an external liveness result into an auditable recovery request.

This is a sidecar for the external scheduler. It never counts its own output
as production activity and never replaces the external watchdog.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from production_liveness_probe import probe


def recovery_request(root: Path, now: float | None = None) -> dict[str, Any]:
    result = probe(root, now=now)
    state = result["state"]
    if state in {"ALIVE", "SLOW"}:
        action = "NO_ACTION"
        next_step = "continue_external_polling"
    else:
        action = "RECOVERY_REQUIRED"
        next_step = "resume_non_conflicting_local_work_or_declare_legal_blocker"
    return {
        "schema": "qingshan.production_liveness_recovery.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "detector": "external_filesystem_liveness_probe",
        "state": state,
        "action": action,
        "next_step": next_step,
        "evidence": {
            "newest_artifact": result.get("newest_artifact"),
            "idle_seconds": result.get("idle_seconds"),
            "action_required": result.get("action_required"),
        },
        "self_declared_ledger_for_reference_only": result.get("self_declared_ledger_FOR_REFERENCE_ONLY", []),
        "boundary": "External watchdog remains primary; this record is not counted as production liveness.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = recovery_request(Path(args.root).expanduser().resolve())
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("state", "action", "next_step")}, ensure_ascii=False))
    return 0 if result["action"] == "NO_ACTION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
