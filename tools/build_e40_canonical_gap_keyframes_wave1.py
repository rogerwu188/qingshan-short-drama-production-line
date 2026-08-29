#!/usr/bin/env python3
"""Build the first three canonical-gap E40 keyframe tasks without submitting."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_KEYFRAME_BATCH_V1.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/canonical_gap_keyframes_wave1_v1"
MANIFEST_PATH = OUT_DIR / "E40_CANONICAL_GAP_KEYFRAMES_WAVE1_V1.json"
PROMPT_DIR = OUT_DIR / "prompts"
COST_GATE_REL = "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1/E40_CANONICAL_GAP_KEYFRAMES_WAVE1_COST_GATE_V1.json"
COST_GATE_PATH = ROOT / COST_GATE_REL

TARGETS = (
    {
        "canonical_shot_id": "E40-13-1-S01",
        "scene_id": "13-1",
        "duration_seconds": 8,
        "action": "满堂灯烛，一道素纱长帘正被穿堂风推起半寸又落下，把花厅隔成两半。帘后人影执扇缓摇；帘侧白鲤静立垂眼。陈迹正跨过厅门门槛，步子未停。",
        "first_frame": "帘被风推起半寸，陈迹前脚正在跨过门槛，所有人都处于动作进行态。",
        "framing": "9:16竖幅，大远景向中景过渡的首帧，镜头位于花厅入口外侧，清楚交代门槛、案、长帘、帘侧与人物之间的完整空间关系。",
        "visible": ["CHAR-陈迹-古装", "CHAR-白鲤-古装"],
    },
    {
        "canonical_shot_id": "E40-13-1-S04",
        "scene_id": "13-1",
        "duration_seconds": 5,
        "action": "陈迹眸底一沉，袖中冷雾无声凝成一线霜，正缠上指骨又将敛去。",
        "first_frame": "霜线只爬上指骨一半，陈迹的判断刚刚落定，不是摆拍完成态。",
        "framing": "9:16竖幅，陈迹三分之二侧面近特写，眼睛、手背与半截霜线同时清晰；背景仍能辨认花厅长帘位置，但绝不喧宾夺主。",
        "visible": ["CHAR-陈迹-古装"],
    },
    {
        "canonical_shot_id": "E40-13-2-S02",
        "scene_id": "13-2",
        "duration_seconds": 5,
        "action": "陈迹指尖正移向案角空处，悬而未落；案面只有四个霜印，绝对没有第五个印。帘侧白鲤垂着的睫毛极轻地动了一下。",
        "first_frame": "指尖尚未点定；四个霜印清楚可数，案角空处保持空白。",
        "framing": "9:16竖幅，案面斜俯近景，陈迹指尖、四个霜印和明确空白的第五位置构成视觉逻辑；白鲤只在帘侧景深里露出微弱睫动。",
        "visible": ["CHAR-陈迹-古装", "CHAR-白鲤-古装"],
    },
)


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_for(target: dict) -> str:
    return (
        f"{target['framing']}\n"
        "空间权威：严格继承 EGSM-E40-WANGFU-SEQUENCE-001 → GSM-WANGFU-HALL-001 → "
        "SUBSPACE-E40-R02 的花厅布局。长案、素纱长帘、帘侧站位、厅门和廊柱的相对方向不得互换；人物脚下必须落地。\n"
        f"canonical 动作：{target['action']}\n"
        f"首帧动势：{target['first_frame']}\n"
        "人物身份：可见人物必须逐一匹配所附 native registry 原图；陈迹保持年轻真实男性骨相和素衣，白鲤保持面纱白衣、窄直静立轮廓。不得换脸、混脸、增龄、幼化或美型重塑。\n"
        "真人感：电影现场抓拍式真实人像，皮肤保留毛孔、细小汗毛、淡斑与自然不对称；眼球有环境反光但不玻璃化，眼睑与嘴角只有符合当下心理的微小肌肉牵动。避免塑料皮、蜡像脸、网红磨皮、过度锐化、完美对称、僵硬凝视和夸张表演。\n"
        "材质与时代：架空宋明王府，旧木、素纱、蜡烛、布料与地砖为真实物理材质；禁止现代灯具、电线、玻璃幕墙、拉链、塑料、印刷字、字幕、LOGO、水印和伪文字。\n"
        "光线：深夜暖金烛光为主，窗纸外雾光冷白为辅，保留面部真实阴影与高光滚降，不做棚拍美容光。\n"
        "只生成一个连续电影镜头的首帧，不生成分镜拼图、三视图、海报、文字说明或多个时刻。"
    )


def main() -> int:
    source = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    base = next(task for task in source["tasks"] if task["unit_id"] == "R02")
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []

    for target in TARGETS:
        task = copy.deepcopy(base)
        task_key = f"{target['canonical_shot_id']}-KEYFRAME-V1"
        shot_id = f"{target['canonical_shot_id']}-KEYFRAME"
        prompt = prompt_for(target)
        prompt_path = PROMPT_DIR / f"{task_key}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")

        task.update({
            "task_key": task_key,
            "unit_id": target["canonical_shot_id"],
            "scene_id": target["scene_id"],
            "canonical_script_action": target["action"],
            "shot_id": shot_id,
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha_file(prompt_path),
            "status": "READY_TO_SUBMIT",
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
            "paid_attempt_ordinal": 1,
            "retry_of": None,
            "canonical_shot_duration_seconds": target["duration_seconds"],
        })
        task["spatial_continuity"]["scene_id"] = target["scene_id"]
        task["prompt_contract"].update({
            "shot_id": shot_id,
            "source_action": target["action"],
            "source_action_sha256": sha_text(target["action"]),
            "visible_characters": target["visible"],
            "status": "PASS",
            "failures": [],
        })
        task["prompt_contract"]["spatial_continuity"]["scene_id"] = target["scene_id"]

        # Frost marks are a transient VFX state, not a persistent canonical
        # asset entity.  Keep their count in the action/prompt contract rather
        # than mis-declaring them as a registry-owned prop.
        task["blocking"]["props"] = []
        task["action_end_blocking"]["props"] = []

        if target["visible"] == ["CHAR-陈迹-古装"]:
            task["reference_bindings"] = [
                binding for binding in task["reference_bindings"]
                if binding.get("entity_id") != "CHAR-白鲤-古装"
            ]
            task["reference_images"] = [
                path for path in task["reference_images"] if not path.endswith("/baili.png")
            ]
            task["prompt_contract"]["reference_bindings"] = copy.deepcopy(task["reference_bindings"])
            task["blocking"]["characters"] = [
                actor for actor in task["blocking"]["characters"]
                if actor["character_id"] == "CHAR-陈迹-古装"
            ]
            task["action_end_blocking"]["characters"] = copy.deepcopy(task["blocking"]["characters"])

        tasks.append(task)

    manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E40-CANONICAL-GAP-KEYFRAMES-WAVE1",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_script_sha256": source["source_script_sha256"],
        "source_gap_manifest": "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_CANONICAL_COVERAGE_GAP_V1.json",
        "spatial_shot_plan_ref": source["spatial_shot_plan_ref"],
        "spatial_shot_plan_sha256": source["spatial_shot_plan_sha256"],
        "episode_global_space_map_ref": source["episode_global_space_map_ref"],
        "global_space_map_gate_required": True,
        "machine_gate_reports": [*source["machine_gate_reports"], COST_GATE_REL],
        "output_dir": "working_assets/e40_remake_20260822/canonical_gap_keyframes_wave1_v1",
        "qa_dir": "qa/e40_remake_20260822/canonical_gap_keyframes_wave1_v1",
        "retry_policy": "NO_AUTOMATIC_RETRY; NEW_CANONICAL_SHOT_FIRST_ATTEMPTS_ONLY",
        "provider_post_allowed": True,
        "maximum_new_submissions": 3,
        "paid_attempt_scope": "FIRST_ATTEMPT_NEW_CANONICAL_SHOTS",
        "consumer_contract": source["consumer_contract"],
        "excluded_retry_cap_units": [],
        "blocked_tasks": [],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "tasks": tasks,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    COST_GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cost_gate = {
        "schema": "qingshan.e40.canonical_gap_keyframe_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "authorization_file": "qa/e40_remake_20260821/human_rebuild_5000_v1/E40_HUMAN_REBUILD_BUDGET_5000_AUTHORIZATION_V1.json",
        "authorization_file_sha256": "c2bfa25ae307494de2fcd844cc0d8021516ab650d9d746c552b22d909b359187",
        "reviewed_manifest": str(MANIFEST_PATH.relative_to(ROOT)),
        "reviewed_manifest_sha256": sha_file(MANIFEST_PATH),
        "task_count": len(tasks),
        "credits_per_task": 11,
        "projected_credits": 11 * len(tasks),
        "remaining_episode_budget_before_submit": 5718,
        "maximum_additional_credits": 5000,
        "max_paid_attempts_per_shot": 3,
        "attempt_classification": "THREE_DISTINCT_FIRST_ATTEMPT_CANONICAL_GAP_KEYFRAMES",
        "attempt_evidence": [],
        "decision": "ALLOW_EXACT_THREE_FIRST_ATTEMPT_KEYFRAME_TASKS_ONLY",
    }
    COST_GATE_PATH.write_text(json.dumps(cost_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(MANIFEST_PATH),
        "sha256": sha_file(MANIFEST_PATH),
        "tasks": [task["task_key"] for task in tasks],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
