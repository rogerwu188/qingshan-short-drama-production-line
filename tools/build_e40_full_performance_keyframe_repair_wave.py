#!/usr/bin/env python3
"""Precompile isolated E40 keyframe repairs; never authorizes a paid POST."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1"
SOURCE = BASE / "E40_FULL_PERFORMANCE_KEYFRAME_BATCH_V1.json"
OUT = BASE / "E40_FULL_PERFORMANCE_KEYFRAME_REPAIR_WAVE_V2.json"
PROMPT_DIR = BASE / "keyframe_prompts_repair_v2"
FAILED = {
    "E40-FP-R01-YUNFEI-A-V1-KF-QA-V2": "ACTION_STATE",
    "E40-FP-R03-YUNFEI-B-V1-KF-QA-V2": "ACTION_STATE",
    "E40-FP-R04-CHENJI-A-V1-KF-QA-V2": "ACTION_STATE",
    "E40-FP-R08-YUNFEI-A-V1-KF-QA-V2": "IDENTITY",
    "E40-FP-R08-YUNFEI-C-V1-KF-QA-V2": "ACTION_STATE",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repair_clause(reason: str) -> str:
    common = (
        "这是失败隔离后的新首帧，不得复制失败画面。整集空间图、王府正厅子空间、帘幕、案面、"
        "人物站位与轴线必须保持锁定。拓影纸只能平放在帘内案面上，完整可见但不得移到地面、"
        "前景、人物手中或帘外；不得新增第二张拓影。"
    )
    if reason == "IDENTITY":
        return common + "云妃必须严格复现 native registry 原图的脸型、五官比例、年龄、发型与服装，不得换脸或年轻化。"
    return common + "画面动作起始状态必须能直接进入后续对白/动作，不得改写道具归属或终态。"


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for prior in source["tasks"]:
        reason = FAILED.get(prior["task_key"])
        if not reason:
            continue
        task = copy.deepcopy(prior)
        old_prompt = (ROOT / prior["prompt_file"]).read_text(encoding="utf-8")
        task.update({
            "task_key": prior["task_key"] + "-REPAIR-V2",
            "status": "PRECOMPILED_WAITING_COST_AND_RETRY_CAP_ADMISSION",
            "provider_post_allowed": False,
            "maximum_new_submissions": 0,
            "retry_attempt": 2,
            "retry_kind": "Q1_REGISTERED_GATE_FAILURE_MATERIAL_PROMPT_REPAIR",
            "prior_prompt_sha256": [prior["prompt_sha256"]],
            "failed_registered_gate": (
                "CHARACTER-IDENTITY-ADMISSION" if reason == "IDENTITY"
                else "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF"
            ),
            "material_change_from_prior_attempt": repair_clause(reason),
            "native_registry_lookup_completed_before_compile": True,
        })
        prompt = PROMPT_DIR / f"{task['task_key']}.txt"
        prompt.write_text(old_prompt.rstrip() + "\n\n修复硬约束：" + repair_clause(reason) + "\n", encoding="utf-8")
        task["prompt_file"] = rel(prompt)
        task["prompt_sha256"] = sha(prompt)
        tasks.append(task)

    manifest = {
        "schema": "qingshan.e40.full_performance_keyframe_repair_wave.v2",
        "episode": "E40",
        "status": "PRECOMPILED_WAITING_COST_AND_RETRY_CAP_ADMISSION",
        "authorization_ref": "ROGER-20260821-NATIVE-REGISTRY-PAID-REBUILD-EXCEPTION",
        "provider_post_allowed": False,
        "maximum_new_submissions": 0,
        "source_manifest": rel(SOURCE),
        "source_manifest_sha256": sha(SOURCE),
        "registered_q1_required_after_harvest": True,
        "video_submit_forbidden_before_q1": True,
        "tasks": tasks,
    }
    write(OUT, manifest)
    print(json.dumps({
        "status": "PASS",
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
        "task_count": len(tasks),
        "provider_post_allowed": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
