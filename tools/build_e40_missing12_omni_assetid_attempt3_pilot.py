#!/usr/bin/env python3
"""Build the single final E40 native-dialogue pilot on the proven asset-id route."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.shot_media_admission_gate import compute_input_template_id


BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
SOURCE = BASE / "E40_MISSING_12_NATIVE_DIALOGUE_VIDEO_PREPRODUCTION_V1.json"
OUT = BASE / "E40_MISSING12_OMNI_ASSETID_ATTEMPT3_PILOT_V1.json"
PROMPT = BASE / "missing_12_omni_assetid_attempt3_prompts/E40-FP-R03-YUNFEI-B-OMNI-ASSETID-A3.txt"
COST = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/videos/E40_MISSING12_OMNI_ASSETID_ATTEMPT3_COST_GATE_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    original = next(task for task in source["tasks"] if "R03-YUNFEI-B" in task["task_key"])
    task = copy.deepcopy(original)

    prompt_text = (
        "9:16古装写实短剧。输入图只作为王府花厅空间、人物背面与霜印案面的连续性参考，"
        "不得把它解释为必须逐像素复制的首帧。保持陈迹和白鲤背对或侧背镜头，四枚霜印位置不变。"
        "云妃的唯一一句声音由@音频1作为同一Seedance任务的原生画外对白参考；画内所有人物闭口，"
        "只做克制的呼吸、眼神和指尖微动作，不出现任何可见说话口型。真实1倍速度，开场即有声音，"
        "4秒内完成反应并自然收束。保留本任务生成的原生对白、环境声和拟音。"
        "禁止字幕、文字、LOGO、水印、看镜头、变脸、年龄漂移、新增人物、重塑面孔、空间跳变、"
        "道具换位、慢动作、静态念稿、夸张表演、删除原生音轨或后配音覆盖。"
    )
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt_text + "\n", encoding="utf-8")

    task.update(
        {
            "task_key": "E40-FP-R03-YUNFEI-B-V1-VIDEO-MISSING12-OMNI-ASSETID-ATTEMPT3",
            "duration_seconds": 4,
            "prompt_file": str(PROMPT.relative_to(ROOT)),
            "prompt_sha256": sha(PROMPT),
            "reference_roles": ["CONTINUITY_REFERENCE"],
            "video_transport": {
                "mode": "omni_multi_reference",
                "endpoint": "/api/v1/generation/omni-video",
                "audio_transport": "PROVIDER_ASSET_ID_PREFERRED_URL_FALLBACK",
            },
            "retry_attempt": 3,
            "retry_kind": "FINAL_OMNI_PROVIDER_ASSET_ID_TRANSPORT_REPAIR",
            "prior_failure_code": "OMNI_URL_ROUTER_MAPPING_NOT_FOUND_THEN_I2V_PROVIDER_TIMEOUT",
            "failure_memory": {
                "attempts": [
                    {"attempt": 1, "transport": "OMNI_PUBLIC_AUDIO_URL", "error": "router mapping not found", "credit": "PASS_ZERO_REFUNDED"},
                    {"attempt": 2, "transport": "I2V_MODEL_NATIVE_TEXT", "error": "provider timeout", "credit": "PASS_ZERO_REFUNDED"},
                ],
                "root_cause": "The deployed Omni adapter discarded provider audio asset IDs and posted only public URLs.",
                "do_not_repeat": "Do not send URL-only Omni audio and do not use I2V native text for this final attempt.",
            },
            "material_change_from_prior_attempt": "Restored the historically completed Omni provider asset-id transport; reduced to one four-second offscreen line; removed the contradictory exact-first-frame instruction.",
            "prior_prompt_sha256": [
                original["prompt_sha256"],
                "e3761eb87615f320d7dbf49dc2914037435453146a574bb016b02d76296867bf",
            ],
            "no_further_automatic_retry": True,
            "terminal_decision_if_failed": "SWITCH_COVERAGE_NO_ATTEMPT4",
            "maximum_new_submissions": 1,
            "provider_post_allowed": True,
            "status": "READY_TO_SUBMIT",
        }
    )
    task.pop("exact_first_frame_sha256", None)
    task.pop("frame0_authority_contract", None)
    task.pop("post_harvest_exact_frame_gate", None)
    task["input_template_id"] = compute_input_template_id(task)

    cost = {
        "schema": "qingshan.registered_gate_evidence.v1",
        "gate_id": "PAID-GENERATION-BUDGET-AND-AUTHORIZATION",
        "status": "PASS",
        "episode": "E40",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "task_count": 1,
        "planned_pay_credits": 64,
        "episode_net_before": 4465,
        "episode_cap": 10000,
        "projected_episode_net": 4529,
        "retry_attempt": 3,
        "no_attempt4": True,
        "reroll_fraction_policy": "ONE_FINAL_PILOT_ONLY; REFUNDED_PROVIDER_FAILURES_NOT_COUNTED_AS_PAID_REROLLS",
    }
    write_json(COST, cost)
    manifest = {
        "schema": "qingshan.e40.missing12_omni_assetid_attempt3_pilot.v1",
        "episode": "E40",
        "status": "READY_TO_SUBMIT_AUTHORIZED",
        "provider": "giggle",
        "allowed_video_models": ["seedance-2.0-fast"],
        "provider_post_allowed": True,
        "maximum_new_submissions": 1,
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "source_manifest": str(SOURCE.relative_to(ROOT)),
        "source_manifest_sha256": sha(SOURCE),
        "machine_gate_reports": [
            "qa/e40_remake_20260818/global_space_maps_v1/E40_GLOBAL_SPACE_LAYOUT_GATE_V1.json",
            "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json",
            "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_PROVIDER_ASSET_REGISTRY_V1.json",
            str(COST.relative_to(ROOT)),
        ],
        "admitted_video_task_count": 1,
        "tasks": [task],
        "release_audio_rule": "Preserve this Seedance task native dialogue/ambience/foley/SFX; never post-redub.",
        "pilot_policy": "ONE_FINAL_ATTEMPT; EXPAND_ONLY_AFTER_PROVIDER_SUCCESS_AND_REGISTERED_Q1_Q2",
    }
    write_json(OUT, manifest)
    print(json.dumps({"manifest": str(OUT.relative_to(ROOT)), "manifest_sha256": sha(OUT), "prompt_sha256": sha(PROMPT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
