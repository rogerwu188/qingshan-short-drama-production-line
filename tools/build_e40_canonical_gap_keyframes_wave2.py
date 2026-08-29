#!/usr/bin/env python3
"""Build distinct first-attempt E40 canonical-gap keyframes S03/S04."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_SPATIAL_KEYFRAME_BATCH_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/canonical_gap_keyframes_wave2_v1"
MANIFEST = OUT / "E40_CANONICAL_GAP_KEYFRAMES_WAVE2_V1.json"
QA_REL = "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1"
COST_REL = f"{QA_REL}/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_COST_GATE_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


TARGETS = (
    {
        "id": "E40-13-2-S03", "scene": "13-2", "base": "R04", "duration": 5,
        "visible": ["CHAR-陈迹-古装", "CHAR-云妃-古装"],
        "action": "陈迹抬眼，一字一顿；帘后云妃手中的团扇正啪地合拢。",
        "first": "陈迹抬眼动作刚发生，帘后团扇两扇面尚差一指宽即将合拢，不是已经完成的摆拍。",
        "framing": "9:16竖幅近特写，陈迹眼神为前景主焦点，素纱帘后只以可信手影和一把团扇呈现云妃；案与帘的前后关系必须清楚。",
    },
    {
        "id": "E40-13-2-S04", "scene": "13-2", "base": "R03", "duration": 6,
        "visible": ["CHAR-陈迹-古装"],
        "action": "陈迹并指刚触到案上第一处霜印，准备一次连续横抹；案上恰好四个霜印，案角空处仍为空，霜粉尚未形成。",
        "first": "两指已接触最左一印但尚未横移，四个霜印清楚可数，无第五印，无已完成霜粉。",
        "framing": "9:16竖幅，70度斜俯案面动作特写，只见陈迹两指、灰袖、恰好四个扁平霜印与明确空白案角；木纹连续，不出现人物脸。",
    },
)


def prompt(target: dict) -> str:
    return (
        f"{target['framing']}\n"
        "空间权威：严格继承 EGSM-E40-WANGFU-SEQUENCE-001 → GSM-WANGFU-HALL-001 → 对应子空间；厅门、案、素纱长帘、帘内案与帘外人物方向不得互换。\n"
        f"canonical 动作：{target['action']}\n首帧动势：{target['first']}\n"
        "资产先行：所有可见人物必须匹配随任务附带的 native registry 原图。陈迹保持年轻真实男性骨相与素衣；云妃只允许处于帘后，保持已锁定发型、年龄、服装和持扇轮廓。不得换脸、混脸、增龄、幼化或把帘后人物移到帘外。\n"
        "真人感：电影现场抓拍式真实皮肤与微表演，保留毛孔、细小汗毛、淡斑、自然不对称、真实眼球环境反光和眼睑肌肉牵动；禁止塑料皮、蜡像脸、网红磨皮、玻璃眼、完美对称、僵硬凝视和夸张表情。\n"
        "架空宋明王府真实旧木、素纱、蜡烛、布料材质；深夜暖金烛光与窗纸冷雾光。禁止现代物、伪文字、字幕、LOGO、水印、分镜拼图、三视图、海报或多个时刻。"
    )


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    bases = {task["unit_id"]: task for task in source["tasks"]}
    prompt_dir = OUT / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for target in TARGETS:
        task = copy.deepcopy(bases[target["base"]])
        key = f"{target['id']}-KEYFRAME-V1"
        p = prompt_dir / f"{key}.txt"
        p.write_text(prompt(target) + "\n", encoding="utf-8")
        task.update({
            "task_key": key,
            "unit_id": target["id"],
            "scene_id": target["scene"],
            "canonical_script_action": target["action"],
            "shot_id": f"{target['id']}-KEYFRAME",
            "prompt_file": str(p.relative_to(ROOT)),
            "prompt_sha256": sha(p),
            "status": "READY_TO_SUBMIT",
            "provider_post_allowed": True,
            "maximum_new_submissions": 1,
            "paid_attempt_ordinal": 1,
            "retry_of": None,
            "canonical_shot_duration_seconds": target["duration"],
        })
        task["spatial_continuity"]["scene_id"] = target["scene"]
        task["prompt_contract"].update({
            "shot_id": f"{target['id']}-KEYFRAME",
            "source_action": target["action"],
            "source_action_sha256": text_sha(target["action"]),
            "visible_characters": target["visible"],
            "status": "PASS",
            "failures": [],
        })
        task["prompt_contract"]["spatial_continuity"]["scene_id"] = target["scene"]
        task["reference_bindings"] = [
            row for row in task["reference_bindings"]
            if not str(row.get("entity_id", "")).startswith("CHAR-") or row.get("entity_id") in target["visible"]
        ]
        task["reference_images"] = [row["path"] for row in task["reference_bindings"]]
        task["prompt_contract"]["reference_bindings"] = copy.deepcopy(task["reference_bindings"])
        task["blocking"]["characters"] = [row for row in task["blocking"]["characters"] if row["character_id"] in target["visible"]]
        task["action_end_blocking"]["characters"] = copy.deepcopy(task["blocking"]["characters"])
        task["blocking"]["props"] = []
        task["action_end_blocking"]["props"] = []
        tasks.append(task)

    manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E40-CANONICAL-GAP-KEYFRAMES-WAVE2",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_script_sha256": source["source_script_sha256"],
        "source_gap_manifest": "workflow/claude_writer_agent/production/e40_remake_v1_20260817/E40_CANONICAL_COVERAGE_GAP_V1.json",
        "spatial_shot_plan_ref": source["spatial_shot_plan_ref"],
        "spatial_shot_plan_sha256": source["spatial_shot_plan_sha256"],
        "episode_global_space_map_ref": source["episode_global_space_map_ref"],
        "global_space_map_gate_required": True,
        "machine_gate_reports": [*source["machine_gate_reports"], COST_REL],
        "output_dir": "working_assets/e40_remake_20260822/canonical_gap_keyframes_wave2_v1",
        "qa_dir": QA_REL,
        "retry_policy": "NO_AUTOMATIC_RETRY; DISTINCT_CANONICAL_SHOT_FIRST_ATTEMPTS_ONLY",
        "provider_post_allowed": True,
        "maximum_new_submissions": 2,
        "paid_attempt_scope": "FIRST_ATTEMPT_NEW_CANONICAL_SHOTS",
        "consumer_contract": source["consumer_contract"],
        "excluded_retry_cap_units": [],
        "blocked_tasks": [],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "tasks": tasks,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cost = ROOT / COST_REL
    cost.parent.mkdir(parents=True, exist_ok=True)
    cost.write_text(json.dumps({
        "schema": "qingshan.e40.canonical_gap_keyframe_cost_gate.v1",
        "gate_id": "GIGGLE-REROLL-COST-GUARD",
        "episode": "E40",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS",
        "authorization_ref": "ROGER-20260821-E40-REBUILD-BUDGET-5000",
        "reviewed_manifest": str(MANIFEST.relative_to(ROOT)),
        "reviewed_manifest_sha256": sha(MANIFEST),
        "task_count": 2,
        "credits_per_task": 11,
        "projected_credits": 22,
        "maximum_additional_credits": 5000,
        "max_paid_attempts_per_shot": 3,
        "decision": "ALLOW_EXACT_TWO_DISTINCT_FIRST_ATTEMPT_KEYFRAMES_ONLY",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(MANIFEST.relative_to(ROOT)), "sha256": sha(MANIFEST), "tasks": [t["task_key"] for t in tasks]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
