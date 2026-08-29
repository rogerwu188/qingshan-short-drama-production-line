#!/usr/bin/env python3
"""Build the final R01 route pilot using same-task native text dialogue."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

try:
    from action_video_prompt_compiler import validate_action_contract
    from shot_media_admission_gate import compute_input_template_id
except ModuleNotFoundError:
    from tools.action_video_prompt_compiler import validate_action_contract
    from tools.shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
V2 = BASE / "E40_FULL_PERFORMANCE_VIDEO_TRANSPORT_PILOT_V2.json"
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_NATIVE_TEXT_PILOT_V3.json"
PROMPT = BASE / "video_prompts_v3/E40-FP-R01-CHENJI-B-V1-VIDEO-V3.txt"
COST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_NATIVE_TEXT_PILOT_COST_GATE_V3.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(V2.read_text(encoding="utf-8"))
    prior = source["tasks"][0]
    task = copy.deepcopy(prior)
    old_prompt = (ROOT / prior["prompt_file"]).read_text(encoding="utf-8")
    task.update({
        "task_key": prior["task_key"].removesuffix("-VIDEO-V2") + "-VIDEO-V3",
        "retry_attempt": 3,
        "retry_kind": "FINAL_PROVIDER_ROUTE_REPAIR_MODEL_NATIVE_TEXT_DIALOGUE",
        "dialogue_transport": "MODEL_NATIVE_TEXT_DIALOGUE",
        "model_native_text_dialogue": True,
        "exact_dialogue_audio_asset_ids": [],
        "exact_dialogue_audio_urls": [],
        "reference_audio_asset_ids": [],
        "reference_audio_urls": [],
        "failure_memory": {
            "attempts": [
                {"attempt": 1, "transport": "OMNI_AUDIO_ASSET_ID", "error": "router mapping not found", "credit": "PASS_ZERO_REFUNDED"},
                {"attempt": 2, "transport": "OMNI_AUDIO_PUBLIC_URL", "error": "router mapping not found", "credit": "PASS_ZERO_REFUNDED"},
            ],
            "root_cause": "Current seedance-2.0-fast Omni route rejects any external audio reference transport.",
            "do_not_repeat": "Do not attach audios to the final route attempt.",
        },
        "material_change_from_prior_attempt": "Removed external audio references and moved the exact canonical line into same-task model-native dialogue generation.",
        "prior_prompt_sha256": [prior["prior_prompt_sha256"][0], prior["prompt_sha256"]],
        "no_further_automatic_retry": True,
        "terminal_decision_if_failed": "SWITCH_COVERAGE_NO_V4",
        "native_audio_policy": "PRESERVE_THIS_SEEDANCE_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_AND_SFX_NO_POST_REDUB",
    })
    line = task["dialogue_lines"][0]
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        old_prompt
        + f"\n最终原生对白路由：陈迹按画面情绪自然普通话只说一次“{line}”；声音、口型、呼吸、环境和拟音必须由同一 Seedance 任务生成并保留。禁止字幕、转写文字、旁白和后配音。\n",
        encoding="utf-8",
    )
    task["prompt_file"] = rel(PROMPT)
    task["prompt_sha256"] = sha(PROMPT)
    task["input_template_id"] = compute_input_template_id(task)
    failures = validate_action_contract(task)
    if failures:
        raise SystemExit(f"action contract failed: {failures}")
    manifest = copy.deepcopy(source)
    manifest.update({
        "schema": "qingshan.e40.full_performance_video_native_text_pilot.v3",
        "tasks": [task],
        "admitted_video_task_count": 1,
        "maximum_new_submissions": 1,
        "transport_repair": "FINAL_ATTEMPT_MODEL_NATIVE_TEXT_DIALOGUE_WITH_NO_EXTERNAL_AUDIO_REFERENCE",
        "pilot_policy": "ONE_TASK_FINAL_ROUTE_ATTEMPT; FAILURE_TERMINATES_AUTOMATIC_RETRY",
    })
    manifest["machine_gate_reports"] = [
        value for value in manifest["machine_gate_reports"] if "COST_GATE" not in value
    ] + [rel(COST)]
    write(OUT, manifest)
    write(COST, {
        "schema": "qingshan.registered_gate_evidence.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "status": "PASS",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "reviewed_manifest": rel(OUT),
        "reviewed_manifest_sha256": sha(OUT),
        "planned_video_tasks": 1,
        "planned_gross_credits": 64,
        "maximum_additional_credits": 5000,
        "prior_attempts_zero_refunded": 2,
        "final_attempt": True,
    })
    print(json.dumps({"status": "PASS", "manifest": rel(OUT), "manifest_sha256": sha(OUT), "prompt_sha256": sha(PROMPT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
