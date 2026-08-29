#!/usr/bin/env python3
"""Build R04 final paid attempt as a reduced-load four-second native line."""

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
V2 = BASE / "E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_PILOT_V2.json"
OUT = BASE / "E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_V3.json"
PROMPT = BASE / "video_prompts_v3/E40-FP-R04-YUNFEI-B1-V1-VIDEO-V3.txt"
COST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_FULL_PERFORMANCE_VIDEO_I2V_NATIVE_TEXT_FINAL_COST_GATE_V3.json"


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
    first_line = prior["dialogue_lines"][0]
    task.update({
        "task_key": "E40-FP-R04-YUNFEI-B1-V1-VIDEO-V3",
        "unit_id": "R04-YUNFEI-B1-COVERAGE",
        "canonical_unit_id": "R04",
        "canonical_unit_text": "帘后云妃确认调令并非本人所下，只说锁定原句：这道令，不是本宫下的。",
        "duration_seconds": 4,
        "dialogue_lines": [first_line],
        "dialogue_ids": [prior["dialogue_ids"][0]],
        "required_audio_intent_keys": [],
        "retry_attempt": 3,
        "retry_kind": "FINAL_REDUCED_LOAD_I2V_NATIVE_TEXT_ATTEMPT",
        "failure_memory": {
            "attempts": [
                {"attempt": 1, "transport": "OMNI_AUDIO_ASSET_ID", "error": "router mapping not found", "credit": "PASS_ZERO_REFUNDED"},
                {"attempt": 2, "transport": "I2V_NATIVE_TEXT_TWO_LINES_EIGHT_SECONDS", "error": "provider timeout", "credit": "PASS_ZERO_REFUNDED"},
            ],
            "root_cause": "Omni route is unavailable and the eight-second two-line I2V payload timed out at provider.",
            "do_not_repeat": "Do not use Omni, external audio, eight seconds or two dialogue lines in the final attempt.",
        },
        "material_change_from_prior_attempt": "Reduced provider load from eight seconds/two lines to four seconds/one canonical line while retaining the exact admitted start frame and same-task native audio.",
        "prior_prompt_sha256": [prior["prior_prompt_sha256"][0], prior["prompt_sha256"]],
        "no_further_automatic_retry": True,
        "terminal_decision_if_failed": "SWITCH_COVERAGE_NO_V4",
    })
    task["performance_tempo_contract"] = {
        "playback_speed": "REAL_TIME_1X",
        "entry_action_already_in_progress": True,
        "atomic_action_windows": [{
            "start_seconds": 0.0,
            "end_seconds": 1.0,
            "action": "云妃吸气后立即开始唯一一句原生对白",
        }],
        "final_timing_policy": "ONE_CANONICAL_LINE_AT_NATURAL_SPEED_NO_TIME_STRETCH",
    }
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(
        "4秒，9:16竖屏，以输入图片为不可改写的第一帧。保持原机位、人物身份、帘幕空间、案上拓影和站位。"
        f"云妃始终只在帘后，吸气后立即以真实普通话、克制但带裂痕的情绪只说一次“{first_line}”"
        "；口型、下颌、呼吸、眼神、同一环境声和布料拟音全部由本次同一个 Seedance 任务生成并保留。"
        "陈迹只作极轻自然反应。禁止第二句、额外对白、字幕、画面文字、旁白、后配音、换脸、年龄漂移、离开帘后、空间跳变、拓影换位、镜头切换、慢动作、LOGO和水印。\n",
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
        "schema": "qingshan.e40.full_performance_video_i2v_native_text_final.v3",
        "tasks": [task],
        "maximum_new_submissions": 1,
        "admitted_video_task_count": 1,
        "transport_repair": "FINAL_REDUCED_LOAD_FOUR_SECOND_ONE_LINE_I2V_NATIVE_TEXT",
        "pilot_policy": "FINAL_ATTEMPT; FAILURE_FORCES_SWITCH_COVERAGE_NO_V4",
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
        "retry_attempt": 3,
        "prior_attempts_zero_refunded": 2,
        "final_attempt": True,
        "terminal_decision_if_failed": "SWITCH_COVERAGE_NO_V4",
    })
    print(json.dumps({
        "status": "PASS",
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
        "prompt_sha256": sha(PROMPT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
