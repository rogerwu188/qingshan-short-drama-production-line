#!/usr/bin/env python3
"""Resolve admitted storyboard sources and build one review-many batch."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_FOCUS = [
    "intentional shot diversity",
    "natural motivated cuts",
    "character identity continuity",
    "story action clarity",
    "no readable or pseudo-readable text",
    "scene authority",
]


def _abs(path):
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _portable(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build(episode, receipts, out_request, out_config, out_prompt, out_report, expected_slots, include_task_keys=None):
    admitted = {}
    include_task_keys = set(include_task_keys or [])
    gate_context = {}
    for receipt_path in receipts:
        receipt = json.loads(_abs(receipt_path).read_text())
        source_config = receipt.get("config")
        if source_config and _abs(source_config).is_file():
            payload = json.loads(_abs(source_config).read_text())
            for key in ("scene_contract_ref", "action_xuanhuan_gate", "storyboard_sheet_plan", "storyboard_sheet_gate_report"):
                if payload.get(key) is not None:
                    gate_context[key] = payload[key]
        for task in receipt.get("tasks", []):
            if task.get("status") != "qa_pass" and task.get("task_key") not in include_task_keys:
                continue
            source_id = task.get("source_id") or task.get("dialogue_id")
            output_path = task.get("output_path")
            if source_id and output_path:
                admitted[source_id] = task

    if len(admitted) != expected_slots:
        raise ValueError(f"expected {expected_slots} admitted slots, found {len(admitted)}: {sorted(admitted)}")

    items = []
    for source_id, task in sorted(admitted.items()):
        video = _abs(task["output_path"])
        if not video.is_file():
            raise FileNotFoundError(video)
        qa = task.get("qa") or {}
        evidence_inputs = {}
        if qa.get("frame_cadence"):
            evidence_inputs["frame_cadence"] = qa["frame_cadence"]
        if qa.get("ocr"):
            evidence_inputs["ocr"] = qa["ocr"]
            evidence_inputs["ocr_raw_audit"] = qa["ocr"]
        items.append({
            "path": str(video),
            "scope": "source_master",
            "kind": "video",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": f"{episode}-{source_id}-STANDARD-STORYBOARD-ADMITTED",
            "metadata": {
                "episode": episode,
                "source_id": source_id,
                "beat_id": task.get("metadata", {}).get("beat_id"),
                "source_sha256": task.get("sha256") or hashlib.sha256(video.read_bytes()).hexdigest(),
                "acceptance_mode": "STANDARD_STORYBOARD_SOURCE_GATE",
                "review_focus": REVIEW_FOCUS,
                "silent_visual_replacement": bool(task.get("metadata", {}).get("silent_visual_replacement")),
                "reuse_admitted_dialogue_audio_in_agentcut": bool(task.get("metadata", {}).get("reuse_admitted_dialogue_audio_in_agentcut")),
            },
            "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
            "evidence_inputs": evidence_inputs,
            "run_regression_ci": True,
            "use_existing_tools": True,
        })

    request_path = _abs(out_request)
    config_path = _abs(out_config)
    prompt_path = _abs(out_prompt)
    report_path = _abs(out_report)
    for path in (request_path, config_path, prompt_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n")
    scene_assertion = ""
    contract_ref = gate_context.get("scene_contract_ref")
    if contract_ref and _abs(contract_ref).is_file():
        contract = json.loads(_abs(contract_ref).read_text())
        states = contract.get("scene_state", [])
        admitted_scene_ids = {
            str(task.get("scene_id")) for task in admitted.values() if task.get("scene_id")
        }
        matched_states = [state for state in states if str(state.get("scene_id")) in admitted_scene_ids]
        selected_states = matched_states or states[:1]
        if selected_states:
            location_tokens = ", ".join(
                token
                for state in selected_states
                for token in state.get("location_prompt_tokens", [])
            )
            time_values = ", ".join(dict.fromkeys(str(state.get("time_of_day")) for state in selected_states))
            weather_values = ", ".join(dict.fromkeys(str(state.get("weather")) for state in selected_states))
            scene_assertion = (
                f" Scene authority: {location_tokens}; time={time_values}; "
                f"weather={weather_values}."
            )
    prompt_path.write_text(
        f"{episode} standard-storyboard admitted-source review.{scene_assertion} "
        f"Review all {expected_slots} sources independently; preserve passing items and return only failed item IDs.\n"
    )
    first = admitted[sorted(admitted)[0]]
    config = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": episode,
        "status": "READY_TO_SUBMIT_AI_REVIEW_BATCH",
        "parallel_submission": True,
        "concurrency": 1,
        "max_retries": 0,
        "qa_dir": _portable(report_path.parent),
        "output_dir": _portable(report_path.parent),
        "base_batch_note": f"Review all {expected_slots} admitted sources in one review-many batch; preserve passes and retry only failures.",
        "tasks": [{
            "task_key": f"{episode}-STANDARD-STORYBOARD-{expected_slots}-SOURCE-AI-REVIEW",
            "tool_type": "ai_review",
            "scene_id": first.get("scene_id"),
            "visual_zone": f"{expected_slots}_SOURCE_AI_REVIEW",
            "prompt_file": _portable(prompt_path),
            "video": str(_abs(first["output_path"])),
            "command": [".ai_review_env/bin/qingshan-review", "review-many", _portable(request_path)],
            "report": _portable(report_path),
        }],
    }
    config.update(gate_context)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
    return {"status": "PASS", "episode": episode, "admitted_sources": len(items), "request": str(request_path), "config": str(config_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--receipt", action="append", required=True)
    parser.add_argument("--out-request", required=True)
    parser.add_argument("--out-config", required=True)
    parser.add_argument("--out-prompt", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--expected-slots", type=int, required=True)
    parser.add_argument("--include-task-key", action="append")
    args = parser.parse_args()
    print(json.dumps(build(args.episode, args.receipt, args.out_request, args.out_config, args.out_prompt, args.out_report, args.expected_slots, args.include_task_key), ensure_ascii=False))


if __name__ == "__main__":
    main()
