#!/usr/bin/env python3
"""Submit one changed-route E37 probe after the omni-video asset DB failure."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from episode_video_generation_guard import (
    evaluate_episode_credit_gate,
    evaluate_episode_submission_authority,
    find_existing_paid_candidate,
    generation_fingerprint,
)
from giggle_api_client import generate_video
from submit_giggle_task_manifest import ensure_giggle_api_key


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/video_prompts_first_wave_v1/E37-CW-U01-S1-FAST-I2V-PROBE-R1.txt"
START_FRAME = ROOT / "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U01-A1-STILL-V1_ZERO_CREDIT_ALT.png"
RECEIPT = ROOT / "workflow/tasks/E37_U01_S1_FAST_I2V_PROVIDER_WORKAROUND_R1_20260802.json"
RESPONSE = ROOT / "workflow/tasks/E37_U01_S1_FAST_I2V_PROVIDER_WORKAROUND_R1_20260802_submit_response.json"
PREVIOUS_RECEIPT = ROOT / "workflow/tasks/E37_FIRST_WAVE_VIDEO_SUBMIT_20260802.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipt(payload: dict) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECEIPT.with_suffix(RECEIPT.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RECEIPT)


def main() -> int:
    ensure_giggle_api_key()
    for path in (PROMPT, START_FRAME, PREVIOUS_RECEIPT):
        if not path.is_file():
            raise RuntimeError(f"missing required input: {path}")

    prior = json.loads(PREVIOUS_RECEIPT.read_text(encoding="utf-8"))
    prior_task = next(row for row in prior["tasks"] if row["task_key"] == "E37-CW-U01-S1-VIDEO-V1")
    if prior_task.get("state") != "remote_failed_preserved":
        raise RuntimeError("probe requires preserved terminal failure evidence")
    if "download_url_shorter" not in str(prior_task.get("failure_reason")):
        raise RuntimeError("probe is only authorized for the observed provider asset DB failure")
    prior_attempt = prior_task["credit_attempts"][-1]
    if prior_attempt.get("charge_status") != "FAILED_ZERO_NET_AFTER_REFUND":
        raise RuntimeError("prior attempt refund is not exact and complete")

    task = {
        "task_key": "E37-CW-U01-S1-FAST-I2V-PROBE-R1",
        "episode": "E37",
        "unit_id": "U01",
        "tool_type": "video_generation",
        "workflow_credit_scope": "e37_claude_writer_v2_07a63a0c_20260802",
        "model": "seedance-2.0-fast",
        "duration_seconds": 10,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generation_mode": "image_to_video_single_start_frame",
        "generation_transport_revision": "FAST_I2V_AFTER_OMNI_OUTPUT_ASSET_DB_1406_R1",
        "prompt_file": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "reference_images": [str(START_FRAME.relative_to(ROOT))],
        "reference_assets": [{"path": str(START_FRAME.relative_to(ROOT)), "sha256": sha256(START_FRAME)}],
        "source_failed_task_id": prior_task["task_id"],
        "source_failure": prior_task["failure_reason"],
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    credit_gate = evaluate_episode_credit_gate(
        "E37",
        limit=10000,
        current_receipt={"episode": "E37", "tasks": [task]},
    )
    authority_gate = evaluate_episode_submission_authority("E37")
    duplicate = find_existing_paid_candidate("E37", task)
    if credit_gate.get("status") != "PASS" or authority_gate.get("status") != "PASS" or duplicate:
        raise RuntimeError(json.dumps({
            "credit_gate": credit_gate,
            "authority_gate": authority_gate,
            "duplicate": duplicate,
        }, ensure_ascii=False))

    receipt = {
        "schema": "qingshan.e37.changed_route_probe.v1",
        "episode": "E37",
        "status": "PRECHECK_PASS_SUBMISSION_STARTING",
        "recorded_at": utc_now(),
        "credit_gate": credit_gate,
        "authority_gate": authority_gate,
        "tasks": [task],
    }
    write_receipt(receipt)

    args = SimpleNamespace(
        prompt=PROMPT.read_text(encoding="utf-8"),
        model=task["model"],
        duration=task["duration_seconds"],
        aspect_ratio=task["aspect_ratio"],
        resolution=task["resolution"],
        count=1,
        start_frame=str(START_FRAME),
        end_frame=None,
    )
    response = generate_video(args)
    RESPONSE.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_id = (response.get("data") or {}).get("task_id") or response.get("task_id")
    if not task_id:
        task.update({"state": "submit_failed_terminal", "failure": response})
        receipt["status"] = "SUBMIT_FAILED_TERMINAL"
        write_receipt(receipt)
        return 2
    task.update({
        "task_id": str(task_id),
        "state": "remote_running",
        "remote_status": "submitted",
        "submitted_at": utc_now(),
        "submit_response": str(RESPONSE.relative_to(ROOT)),
        "credit_attempts": [{
            "attempt": 1,
            "task_id": str(task_id),
            "success": None,
            "charge_status": "PENDING_REMOTE_RESULT",
            "actual_charged_credits": None,
            "generation_fingerprint": task["generation_fingerprint"],
        }],
    })
    receipt["status"] = "PROBE_REMOTE_RUNNING"
    receipt["active_task_count"] = 1
    receipt["active_task_ids"] = [str(task_id)]
    write_receipt(receipt)
    print(json.dumps({"status": receipt["status"], "task_id": task_id, "receipt": str(RECEIPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
