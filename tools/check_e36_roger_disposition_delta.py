#!/usr/bin/env python3
"""Fail-closed local check for a new E36 Roger disposition."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAILBOX = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
PACKET = ROOT / "workflow/tasks/E36_ROGER_ESCALATION_DECISION_PACKET_V1.json"
RESUME_PLAN = ROOT / "workflow/tasks/E36_POST_ROGER_DISPOSITION_PARALLEL_RESUME_PLAN_V1.json"
APPROVALS = ROOT / "workflow/approvals"
OUTPUT = ROOT / "qa/e36_agentcut_20260730/E36_ROGER_DISPOSITION_DELTA_CHECK_V1.json"

RELEVANT_NAME_TOKENS = ("E36", "DISPOSITION", "WAIVER", "RIGHTS", "U08")
DECISION_TOKENS = ("DISPOSITION", "WAIVER", "RIGHTS", "REPLACEMENT", "U08")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> None:
    required = (MAILBOX, PACKET, RESUME_PLAN)
    missing = [relative(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"missing required files: {missing}")

    mailbox_text = MAILBOX.read_text(encoding="utf-8")
    top_match = re.search(r"^CL2X-(\d+)\b", mailbox_text, re.MULTILINE)
    top_cl2x = f"CL2X-{top_match.group(1)}" if top_match else "UNKNOWN"
    packet_mtime = PACKET.stat().st_mtime

    newer = []
    relevant = []
    for path in sorted(APPROVALS.glob("*")):
        if not path.is_file() or path.stat().st_mtime <= packet_mtime:
            continue
        upper_name = path.name.upper()
        entry = {
            "path": relative(path),
            "sha256": sha256(path),
            "mtime_epoch": path.stat().st_mtime,
        }
        newer.append(entry)
        if "E36" in upper_name and any(token in upper_name for token in DECISION_TOKENS):
            relevant.append(entry)

    explicit_disposition = bool(relevant)
    status = "REVIEW_NEW_DISPOSITION" if explicit_disposition else "NO_NEW_DISPOSITION_KEEP_HOLD"
    payload = {
        "schema": "qingshan.e36.roger_disposition_delta_check.v1",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "source_cl2x": top_cl2x,
        "source_cl2x_mailbox_sha256": sha256(MAILBOX),
        "decision_packet": {"path": relative(PACKET), "sha256": sha256(PACKET)},
        "parallel_resume_plan": {"path": relative(RESUME_PLAN), "sha256": sha256(RESUME_PLAN)},
        "approval_files_newer_than_packet": newer,
        "relevant_disposition_candidates": relevant,
        "explicit_roger_disposition_found": explicit_disposition,
        "gate_results": {
            "mailbox_top": top_cl2x,
            "decision_packet_present": "PASS",
            "parallel_resume_plan_present": "PASS_PREPARED_NOT_AUTHORIZED",
            "new_relevant_approval": "REVIEW_REQUIRED" if explicit_disposition else "NOT_FOUND",
            "no_reply_default": "HOLD_ZERO_SPEND",
            "waiver_applied": "NO",
            "generation_credits": 0,
        },
        "blocked_by": (
            "Roger's explicit four-axis E36 disposition remains required. A candidate file must be "
            "reviewed for exact scope before any waiver, changed input, rights replacement or AgentCut release."
        ),
        "next_action": (
            "If a candidate appears, validate its exact scope and dispatch only independently authorized lanes "
            "concurrently. Otherwise preserve every FAIL and keep zero-spend AgentCut/E37 HOLD."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(status)


if __name__ == "__main__":
    main()
