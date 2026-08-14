#!/usr/bin/env python3
"""CAS-register the real zero-cost QA successor for E40 U12 exact audio."""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "workflow/production_line/E40_TASK_LANES_V1.json"
sys.path.insert(0, "/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
from task_lane_state_store import commit_task_updates, read_scheduler_snapshot  # noqa: E402

TASK_ID = "E40-U12-DIA010-EXACT-AUDIO-SECONDARY-ASR-AND-HUMAN-LISTEN-PACKET-QA"


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "terminal"), nargs="?", default="register")
    parser.add_argument("--evidence-ref")
    parser.add_argument("--evidence-sha256")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = read_scheduler_snapshot(STATE)
    existing = next((copy.deepcopy(row) for row in snapshot.payload.get("tasks", []) if row.get("task_id") == TASK_ID), None)
    if args.action == "register":
        if existing is not None:
            raise SystemExit(f"refusing duplicate QA successor: {existing.get('state')}")
        task = {
            "task_id": TASK_ID,
            "lane_id": "AUDIO_QA",
            "state": "RUNNING",
            "zero_cost": True,
            "deliverable_type": "SECONDARY_EXACT_ASR_AND_HUMAN_LISTEN_PACKET",
            "priority": 100,
            "scope": ["E40", "U12", "DIA010", "EXACT_AUDIO", "SECONDARY_ASR", "HUMAN_LISTEN_PACKET"],
            "exact_predecessor_task_id": "E40-U12-DIA010-EXACTLY-ONE-TTS-EXECUTION",
            "liveness_role": "QA",
            "observation_only": False,
            "lease_owner": "codex-e40-u12:exact-audio-secondary-qa",
            "lease_expires_at": stamp(now + timedelta(hours=2)),
            "last_progress_at": stamp(now),
            "next_due_at": stamp(now + timedelta(minutes=10)),
            "progress": "EXACT_WAV_SHA_BOUND_SECONDARY_UNCONDITIONED_ASR_AND_HUMAN_LISTEN_PACKET_STARTED",
            "evidence_ref": "workflow/tasks/E40_U12_DIA010_EXACTLY_ONE_TTS_EXECUTION_20260809.json",
            "evidence_sha256": "a3a2e524fac2c1f9dc79cfb1679a8c9f33c463951664edf4e7edbe26d7c28f51",
            "maximum_new_submissions": 0,
            "authorization": False,
            "next_action": "Run zero-cost unconditioned/alternate-decode ASR on exact WAV, compile a human listening packet and preserve AgentCut attachment closed until full-line mouth-nonvisible video QA exists.",
        }
    else:
        if existing is None or existing.get("state") != "RUNNING":
            raise SystemExit("QA successor is not RUNNING")
        if not args.evidence_ref or not args.evidence_sha256:
            raise SystemExit("terminal requires evidence ref and SHA")
        task = existing
        task.update({
            "state": "TERMINAL",
            "last_progress_at": stamp(now),
            "next_due_at": None,
            "progress": "PASS_SECONDARY_MACHINE_QA_HUMAN_LISTEN_PACKET_READY",
            "terminal_status": "PASS_SECONDARY_MACHINE_QA_PACKET_READY_HUMAN_LISTEN_PENDING",
            "completed_at": stamp(now),
            "evidence_ref": args.evidence_ref,
            "evidence_sha256": args.evidence_sha256,
            "blocked_by": "HUMAN_LISTEN_PENDING_AND_U12_FULL_LINE_MOUTH_NONVISIBLE_VIDEO_QA_NOT_YET_AVAILABLE",
            "next_action": "Roger or a delegated human listener may play the exact WAV SHA and record the checklist verdict. AgentCut attachment remains closed until human listen and full-line mouth-nonvisible video QA both pass.",
        })
    result = commit_task_updates(
        STATE,
        base_snapshot=snapshot,
        task_updates={TASK_ID: copy.deepcopy(task)},
        writer_id="codex-e40-u12:exact-audio-secondary-qa",
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
