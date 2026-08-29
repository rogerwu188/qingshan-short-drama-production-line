#!/usr/bin/env python3
"""Build failed-only E43 curtain keyframe repairs after visual review."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_preproduction_20260828"
SOURCE = PROD / "E43_V6_GIGGLE_KEYFRAME_MANIFEST_PRECHECK_V1.json"
ORIGINAL = PROD / "E43_V6_GIGGLE_KEYFRAME_MANIFEST_AUTHORIZED_V1.json"
HARVEST = QA / "E43_V6_GIGGLE_KEYFRAME_HARVEST_V1.json"
OUT = PROD / "E43_V6_CURTAIN_KEYFRAME_REPAIRS_A2_PRECHECK.json"
FAILURE_MEMORY = QA / "E43_V6_CURTAIN_KEYFRAME_FAILURE_MEMORY_A1.json"
PROMPT_DIR = PROD / "keyframe_prompts_curtain_repairs_a2"

REPAIRS = {
    "E43-S02-01": "只拍无人帘亭与帘面向外鼓起的一次物理动作；画面内绝对不得出现陈迹、春华、静妃或任何人形。",
    "E43-S02-06": "只拍无人帘亭与帘面从内侧被抓住后保持的布料张力；画面内绝对不得出现陈迹、春华、静妃或任何人形。",
    "E43-S03-06": "只拍帘角被从内侧攥出的第二道新褶及布料受力；不得出现手、身体、剪影、倒影或任何人形。",
}
INITIALS = {"E43-S02-03", "E43-S02-08"}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    fresh = {row["editorial_shot_id"]: row for row in read(SOURCE)["tasks"]}
    originals = {row["editorial_shot_id"]: row for row in read(ORIGINAL)["tasks"]}
    outputs = {row["task_key"]: row for row in read(HARVEST)["results"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks, failures = [], []
    for shot_id, correction in REPAIRS.items():
        task = copy.deepcopy(fresh[shot_id])
        if any(row.get("role") == "character" for row in task.get("reference_bindings") or []):
            raise SystemExit(f"{shot_id} curtain repair still carries a character reference")
        original = originals[shot_id]
        output = outputs[original["task_key"]]
        task_key = f"{shot_id}-KF-A2"
        source_prompt = ROOT / task["prompt_file"]
        prompt = source_prompt.read_text(encoding="utf-8").rstrip()
        prompt += "\n【A1视觉失败后的实质修正】\n" + correction
        prompt += "\n首版的人物构图已判定失败，严禁复用首版人物、站位和人脸。"
        prompt_path = PROMPT_DIR / f"{task_key}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        task.update({
            "task_key": task_key, "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path),
            "attempt_index": 2, "status": "PRECHECK_ONLY", "provider_post_allowed": False,
            "maximum_new_submissions": 0, "failure_attribution": "VISIBLE_CHARACTER_IN_OFFSCREEN_CURTAIN_SHOT",
            "changed_variables": ["VISIBLE_CAST", "BLOCKING", "PROMPT"],
            "do_not_repeat_prompt_sha256": original["prompt_sha256"],
            "do_not_repeat_output_sha256": output["sha256"], "unchanged_retry": False,
        })
        tasks.append(task)
        failures.append({
            "editorial_shot_id": shot_id, "candidate_task_key": original["task_key"],
            "candidate_output": output["output_path"], "candidate_output_sha256": output["sha256"],
            "prompt_sha256": original["prompt_sha256"],
            "failure_attribution": "VISIBLE_CHARACTER_IN_OFFSCREEN_CURTAIN_SHOT",
            "reason": correction, "do_not_repeat": True, "content_attempt_consumed": 1,
            "next_task_key": task_key, "changed_variables": ["VISIBLE_CAST", "BLOCKING", "PROMPT"],
        })
    for shot_id in sorted(INITIALS):
        task = copy.deepcopy(fresh[shot_id])
        task.update({
            "status": "PRECHECK_ONLY", "provider_post_allowed": False,
            "maximum_new_submissions": 0, "attempt_index": 1,
            "unchanged_retry": False,
        })
        tasks.append(task)
    FAILURE_MEMORY.write_text(json.dumps({
        "schema": "qingshan.provider_healthy_content_failure_memory.v1", "episode": "E43",
        "status": "RECORDED_3_FAILED_ONLY", "provider_health": "HEALTHY_54_OF_54_COMPLETED",
        "failure_count": len(failures), "failures": failures,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source = read(SOURCE)
    manifest = {
        **{k: v for k, v in source.items() if k != "tasks"},
        "schema": "qingshan.giggle_image_batch_manifest.v2", "status": "PRECHECK_ONLY",
        "provider_post_allowed": False, "maximum_new_submissions": 0,
        "repair_scope": sorted(REPAIRS), "initial_missing_scope": sorted(INITIALS),
        "failure_memory": rel(FAILURE_MEMORY),
        "tasks": tasks,
    }
    manifest["consumer_contract"] = copy.deepcopy(source["consumer_contract"])
    manifest["consumer_contract"]["planned_anchor_count"] = len(tasks)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "provider_posts": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
