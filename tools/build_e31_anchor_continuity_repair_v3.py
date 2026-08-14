#!/usr/bin/env python3
"""Rebuild only E31 A2 anchors that were generated without their real A1 input."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
A1_HARVEST = PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1_HARVEST.json"
V2 = PRODUCTION / "E31_IMAGE_BATCH_VARIABLE_ANCHOR_SUPPLEMENT_V2.json"
ANCHOR_GATE = ROOT / "qa/e31_performance_preproduction_20260722/E31_VIDEO_UNIT_ANCHOR_COUNT_GATE_V3.json"
QA = ROOT / "qa/e31_performance_stills_20260722/E31_VARIABLE_ANCHOR_PAIR_VISUAL_QA_V1.json"
OUT = PRODUCTION / "E31_IMAGE_BATCH_ANCHOR_CONTINUITY_REPAIR_V3.json"
PROMPT_DIR = PRODUCTION / "image_prompts_anchor_continuity_repair_v3"


UNITS = {"E31-CW-U02", "E31-CW-U05", "E31-CW-U10"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    harvest = json.loads(A1_HARVEST.read_text(encoding="utf-8"))
    a1_rows = {
        row["beat_id"]: row
        for row in harvest["results"]
        if row.get("beat_id") in UNITS and row.get("remote_status") == "completed"
    }
    if set(a1_rows) != UNITS:
        raise SystemExit("All three admitted A1 anchors must be harvested before A2 repair")

    v2 = json.loads(V2.read_text(encoding="utf-8"))
    source_tasks = {task["video_unit_id"]: task for task in v2["tasks"]}
    failures = {
        unit_id: {
            "status": "FAIL",
            "failure": "A2 was generated without the actual admitted A1 image; visual inspection found camera, population, identity or spatial-topology jumps that are not safely interpolable.",
            "rollback": "Keep admitted A1 and discard only the original A2 candidate from video input.",
            "repair": "Regenerate only A2 with admitted A1 as the first real image reference and a changed continuity-only prompt.",
        }
        for unit_id in sorted(UNITS)
    }
    write_json(QA, {
        "schema": "qingshan.variable_anchor_pair_visual_qa.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL_REPAIR_IN_PROGRESS",
        "units": failures,
        "original_fail_preserved": True,
    })

    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for unit_id in sorted(UNITS):
        source = source_tasks[unit_id]
        a1 = a1_rows[unit_id]
        a1_path = Path(a1["output_path"])
        old_contract = source["prompt_contract"]
        continuity = old_contract["source_action"]
        prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物与真实物理，禁止现代物件。

第一张参考图是 {unit_id} 已验收的真实 A1 锚。必须延续它的同一机位、同一人物面孔与数量、同一服装、同一场景、同一道具归属和同一屏幕方向；不得另起构图或重新选角。

只把 A1 沿下列物理链推进到一个终态，不添加链外动作：{continuity}

这是连续动作的后继锚，不是独立海报。A1 中每个可见人物都必须仍可对应；主体位移只能由所述受力产生。禁止新增或删除人物，禁止身份交换、道具瞬移、机位反打、拼贴、多格分镜、可读文字、伪文字、字幕、水印、标志和界面。
"""
        prompt_path = PROMPT_DIR / f"{unit_id}-A2-R2.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        a1_binding = {
            "role": "continuity_anchor",
            "entity_id": f"{unit_id}-A1-ADMITTED",
            "path": rel(a1_path),
            "sha256": sha256(a1_path),
            "qa_status": "PASS",
            "qa_report": rel(A1_HARVEST),
        }
        bindings = [a1_binding, *source["reference_bindings"]]
        shot_id = f"{unit_id}-A2-R2"
        contract = {
            **old_contract,
            "shot_id": shot_id,
            "source_action": continuity,
            "source_action_sha256": text_sha(continuity),
            "reference_bindings": bindings,
            "status": "PASS",
            "failures": [],
            "continuity_anchor_is_first_real_reference": True,
            "supersedes_task_key": source["task_key"],
        }
        tasks.append({
            **source,
            "task_key": f"{unit_id}-A2-STILL-CONTINUITY-R2",
            "shot_id": shot_id,
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": contract,
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "repair_reason": failures[unit_id]["failure"],
            "changed_input": "ACTUAL_ADMITTED_A1_ADDED_AS_FIRST_IMAGE_REFERENCE_AND_CONTINUITY_ONLY_PROMPT",
        })

    write_json(OUT, {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E31",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": v2["source_script_sha256"],
        "machine_gate_reports": [rel(ANCHOR_GATE)],
        "output_dir": v2["output_dir"],
        "qa_dir": v2["qa_dir"],
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "PAIR_CONTINUITY_REPAIR_ONLY",
            "video_unit_count": 20,
            "repaired_successor_anchor_count": 3,
            "previous_admitted_anchor_required_as_first_real_reference": True,
        },
        "original_fail_report": rel(QA),
        "blocked_tasks": [],
        "tasks": tasks,
    })
    print(json.dumps({"status": "PASS", "repair_tasks": len(tasks), "manifest": rel(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
