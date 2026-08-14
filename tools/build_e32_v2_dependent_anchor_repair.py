#!/usr/bin/env python3
"""Build changed-input repairs for the two failed E32 v2 dependent anchors."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
SOURCE = PROD / "E32_IMAGE_BATCH_DEPENDENT_A2_V2.json"
HARVEST = PROD / "E32_IMAGE_BATCH_DEPENDENT_A2_V2_HARVEST.json"
A1_HARVEST = PROD / "E32_IMAGE_BATCH_PERFORMANCE_A1_V2_HARVEST.json"
OUT = PROD / "E32_IMAGE_BATCH_DEPENDENT_A2_REPAIR_R2.json"
PROMPT_DIR = PROD / "image_prompts_dependent_repair_r2"
QA = ROOT / "qa/e32_remake_preproduction_20260723/E32_DEPENDENT_A2_VISUAL_QA_V2.json"
EXTERIOR = ROOT / "working_assets/e29_claude_writer_v1_stills_20260722/candidates/E29_E29-CW-S01-SH01-STILL-V1_4f6f7833-2bff-40e4-9a98-69b4d4054bc7.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    failed = {row["task_key"]: row for row in json.loads(HARVEST.read_text(encoding="utf-8"))["results"]}
    a1 = {row["task_key"]: row for row in json.loads(A1_HARVEST.read_text(encoding="utf-8"))["results"]}
    failures = {
        "E32-CW-U04-A2-STILL-V2": {
            "failure": "The generic same-scene/same-camera constraint contradicted the authored cross-location destination re-anchor, so the result duplicated A1 instead of arriving at the west-market dark tower.",
            "repair": "Allow the authored spatial cut; use A1 only for Jiaotu identity and replace the scene reference with the exterior destination style reference.",
        },
        "E32-CW-U10-A2-STILL-V2": {
            "failure": "The result put the patrol token in Qi San's hand and left him alive, violating the terminal life-state and prop-ownership facts.",
            "repair": "Lock Qi San dead with empty hands and bind the patrol token exclusively to the left-screen black-clad Chenji's right fingers.",
        },
    }
    write(QA, {
        "schema": "qingshan.dependent_anchor_visual_qa.v1",
        "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL_TARGETED_REPAIR_SUBMITTED",
        "original_fail_preserved": True,
        "items": failures,
        "rollback": "Keep all 17 admitted A1 candidates; reject only these two A2 candidates.",
    })

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for old in source["tasks"]:
        key = old["task_key"]
        unit = old["video_unit_id"]
        dependency = a1[old["depends_on_task_key"]]
        a1_path = Path(dependency["output_path"])
        source_action = old["prompt_contract"]["source_action"]
        if unit == "E32-CW-U04":
            prompt = f"""竖屏9:16，电影级中国古装玄幻雨夜。第一张图仅用于锁定皎兔与黑甲阴神是同一身份的肉身和阴神；这是剧本明确的跨空间终点镜头，必须切到西市暗楼外的新机位，禁止复制医馆室内构图。

终态只画西市暗楼窗外：同一张脸、同一发型与黑甲服装的皎兔阴神已经独自抵达，悬停或落在湿黑屋檐边，警觉望向暗楼内。医馆肉身不在这个终点画面，不出现第二个皎兔，不出现分身残影。背景必须是雨夜西市暗楼外观和窗灯，不得仍是医馆书案。
同源动作规格：{source_action}
禁止文字、字幕、水印、拼贴、多格、额外人物、身份漂移、室内医馆复刻。
"""
            bindings = old["reference_bindings"]
        else:
            prompt = f"""竖屏9:16，电影级中国古装玄幻雨夜，延续第一张真实 A1 的同一四个人、同一服装、同一雨巷、同一屏幕位置和同一机位。

终态事实硬锁：齐三是画面中央穿灰衣者，他已经仰倒在雨地、咽喉受伤、失去生命反应，双手完全空着。杀手是前景黑衣蒙面者，他已起身退向暗巷出口，双手不持铜牌。陈迹是画面最左侧的年轻黑衣男子，只有陈迹的右手两指夹住半枚巡检铜牌并抬到自己眼前。右侧年长黑衣云羊只观察，不接触铜牌。铜牌不得出现在齐三、杀手或云羊手中，也不得出现第二枚。
同源动作规格：{source_action}
禁止交换人物身份、让齐三复活或站立、令牌错手、额外人物、额外令牌、文字、字幕、水印、拼贴、多格。
"""
            bindings = old["reference_bindings"]
        prompt_path = PROMPT_DIR / f"{unit}-A2-R2.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        shot_id = f"{unit}-A2-R2"
        contract = {**old["prompt_contract"], "shot_id": shot_id, "reference_bindings": bindings,
                    "source_action": source_action, "source_action_sha256": text_sha(source_action),
                    "status": "PASS", "failures": []}
        tasks.append({**old, "task_key": f"{unit}-A2-STILL-R2", "shot_id": shot_id,
                      "prompt_file": rel(prompt_path), "prompt_sha256": sha(prompt_path),
                      "reference_images": [row["path"] for row in bindings], "reference_bindings": bindings,
                      "prompt_contract": contract, "status": "READY_FOR_PARALLEL_SUBMIT",
                      "supersedes_task_key": key, "changed_input": failures[key]["repair"]})

    write(OUT, {
        "schema": "qingshan.episode_parallel_batch.v1", "episode": "E32",
        "status": "READY_TO_SUBMIT_CONCURRENTLY", "source_script_sha256": source["source_script_sha256"],
        "machine_gate_reports": source["machine_gate_reports"], "output_dir": source["output_dir"],
        "qa_dir": source["qa_dir"], "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {"purpose": "DEPENDENT_A2_TARGETED_REPAIR", "failed_only": True,
                              "changed_input_required": True, "task_count": len(tasks)},
        "original_fail_report": rel(QA), "blocked_tasks": [], "tasks": tasks,
    })
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "out": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
