#!/usr/bin/env python3
"""Submit the one allowed changed-input U08-S3 repair after local salvage."""

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
PROMPT = ROOT / "working_assets/e37_video_20260803/u08_s3_changed_i2v_repair_v1/E37_U08_S3_CHANGED_I2V_REPAIR_PROMPT_V1.txt"
START_FRAME = ROOT / "working_assets/e37_video_20260803/u08_s3_changed_i2v_repair_v1/E37_U08_S3_CLOSE_START_FRAME_V1.png"
END_FRAME = ROOT / "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U08-A1-STILL-V2_ZERO_CREDIT_ALT_PASS.png"
PRIOR_RECEIPT = ROOT / "workflow/tasks/E37_U08_S3_PROVIDER_RECOVERY_CANARY_SUBMIT_RECEIPT_V1_20260803.json"
PRIOR_QA = ROOT / "qa/e37_video_20260803/provider_recovery_canary_v1/E37_U08_S3_PROVIDER_RECOVERY_CANARY_QA_V1.json"
LOCAL_SALVAGE_AHASH = ROOT / "qa/e37_video_20260803/u08_s3_zero_credit_salvage_v1/E37_U08_S3_SALVAGE_FPS1_ADJACENT_AHASH_V5.json"
RECEIPT = ROOT / "workflow/tasks/E37_U08_S3_CHANGED_I2V_REPAIR_V1_20260803.json"
RESPONSE = ROOT / "workflow/tasks/E37_U08_S3_CHANGED_I2V_REPAIR_V1_20260803_responses/submit_response.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write_receipt(payload: dict) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECEIPT.with_suffix(RECEIPT.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(RECEIPT)


def main() -> int:
    ensure_giggle_api_key()
    for path in (PROMPT, START_FRAME, END_FRAME, PRIOR_RECEIPT, PRIOR_QA, LOCAL_SALVAGE_AHASH):
        if not path.is_file():
            raise RuntimeError(f"missing required input: {path}")

    prior = json.loads(PRIOR_RECEIPT.read_text(encoding="utf-8"))
    prior_task = prior["tasks"][0]
    prior_qa = json.loads(PRIOR_QA.read_text(encoding="utf-8"))
    local_ahash = json.loads(LOCAL_SALVAGE_AHASH.read_text(encoding="utf-8"))
    if prior_task.get("state") != "local_qa_failed_preserved_dialogue_salvage_candidate":
        raise RuntimeError("changed repair requires preserved prior QA failure")
    if prior_qa.get("status") != "FAIL_PRESERVED_PROVIDER_RECOVERED_OUTPUT_NOT_ADMITTED":
        raise RuntimeError("prior output must remain not admitted")
    if local_ahash.get("status") != "PASS":
        raise RuntimeError("zero-credit local salvage must be executed before remote repair")

    task = {
        "task_key": "E37-CW-U08-S3-CHANGED-I2V-REPAIR-V1",
        "episode": "E37",
        "unit_id": "U08",
        "segment_id": "U08-S3",
        "tool_type": "video_generation",
        "workflow_credit_scope": "e37_claude_writer_v2_07a63a0c_20260802",
        "model": "seedance-2.0-pro",
        "duration_seconds": 6,
        "aspect_ratio": "9:16",
        "resolution": "720p",
        "generation_mode": "image_to_video_exact_start_end_frames",
        "generation_transport_revision": "CHANGED_I2V_EXACT_START_END_AFTER_STATIC_CANARY_FAIL_V1",
        "prompt_file": rel(PROMPT),
        "prompt_sha256": sha256(PROMPT),
        "start_frame": rel(START_FRAME),
        "start_frame_sha256": sha256(START_FRAME),
        "end_frame": rel(END_FRAME),
        "end_frame_sha256": sha256(END_FRAME),
        "source_failed_task_id": prior_task["task_id"],
        "source_failure_qa": rel(PRIOR_QA),
        "local_salvage_evidence": rel(LOCAL_SALVAGE_AHASH),
        "automatic_changed_input_repair_attempt": 1,
        "maximum_automatic_changed_input_repair_attempts": 1,
    }
    task["generation_fingerprint"] = generation_fingerprint(task)
    duplicate = find_existing_paid_candidate("E37", task)
    credit_gate = evaluate_episode_credit_gate(
        "E37", limit=10000, current_receipt={"episode": "E37", "tasks": [task]}
    )
    authority_gate = evaluate_episode_submission_authority("E37")
    if duplicate or credit_gate.get("status") != "PASS" or authority_gate.get("status") != "PASS":
        raise RuntimeError(json.dumps({
            "duplicate": duplicate,
            "credit_gate": credit_gate,
            "authority_gate": authority_gate,
        }, ensure_ascii=False))

    receipt = {
        "schema": "qingshan.e37.changed_i2v_repair.v1",
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
        end_frame=str(END_FRAME),
    )
    response = generate_video(args)
    RESPONSE.parent.mkdir(parents=True, exist_ok=True)
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
        "submit_response": rel(RESPONSE),
        "credit_attempts": [{
            "attempt": 1,
            "task_id": str(task_id),
            "success": None,
            "charge_status": "PENDING_REMOTE_RESULT",
            "actual_charged_credits": None,
            "generation_fingerprint": task["generation_fingerprint"],
        }],
    })
    receipt.update({
        "status": "CHANGED_REPAIR_REMOTE_RUNNING",
        "active_task_count": 1,
        "active_task_ids": [str(task_id)],
    })
    write_receipt(receipt)
    print(json.dumps({"status": receipt["status"], "task_id": task_id, "receipt": rel(RECEIPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
