#!/usr/bin/env python3
"""Build a materially changed retry for E37 units rejected by direct watch."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v2/E37_ATOMIC_ACTION_REPLACEMENT_BATCH_V2.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v3/E37_ATOMIC_ACTION_DIRECT_WATCH_RETRY_BATCH_V3.json"
PROMPT_DIR = ROOT / "working_assets/e37_prompt_repair_20260803/compiled_prompts_v3"
FAILED = {"E37-R-A01", "E37-R-A03", "E37-R-A04", "E37-R-A05", "E37-R-A07", "E37-R-A08"}

TIMELINES = {
    "E37-R-A01": "0.0-1.2秒火把必须在空中清楚可见；1.2-2.0秒火把头撞到灯油地面；2.0-3.8秒火线只从该接触点扩展，火把弹停。禁止开场已有大火。",
    "E37-R-A03": "0.0-1.0秒燃梁正在下坠且纸人双掌仍低于梁；1.0-2.0秒双掌迎上梁底；2.0-4.5秒纸人肘部受力下沉、脚后滑后才稳住。禁止开场已经托住。",
    "E37-R-A04": "0.0-1.0秒完整土墙、右拳收在肋侧；1.0-1.8秒右拳直线撞墙；1.8-3.8秒拳面停在新破口边、土块只向屋外飞。右拳必须接触墙，双脚始终踩实地面。",
    "E37-R-A05": "0.0-1.0秒账册必须清楚在陈迹左手，阴神空手；1.0-2.0秒账册书脊由左向右飞；2.0-3.8秒阴神双掌接住并抱紧胸前。账册全程唯一且可见。",
    "E37-R-A07": "0.0-1.0秒三人仍在屋内左侧，阴神双臂抱紧唯一账册；1.0-3.2秒三人依次穿墙洞向右；3.2-5.0秒都落在屋外湿地且不回位，账册始终在阴神胸前。",
    "E37-R-A08": "0.0-1.0秒完整燃烧屋架仍立、三人在右前景；1.0-3.5秒屋架必须清楚向内向下连续坍塌直至屋顶轮廓消失；3.5-5.0秒火星雨汽上冲、三人受冲击低身。禁止只拍人物回望。",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    retry = copy.deepcopy(source)
    retry["status"] = "READY_FOR_DIRECT_WATCH_FAILED_ONLY_RETRY"
    retry["concurrency"] = len(FAILED)
    retry["output_dir"] = "working_assets/e37_action_replacement_v3_20260803/outputs"
    retry["qa_dir"] = "qa/e37_action_replacement_v3_20260803"
    retry["retry_policy"] = "DIRECT_WATCH_FAILED_ONLY_MATERIALLY_CHANGED_TIMELINE"
    retry["direct_watch_failure_evidence"] = "qa/e37_action_replacement_v2_20260803/E37_ACTION_DIRECT_WATCH_ADJUDICATION_V2.json"
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for task in source["tasks"]:
        unit_id = task["unit_id"]
        if unit_id not in FAILED:
            continue
        prompt = (ROOT / task["prompt_path"]).read_text(encoding="utf-8")
        changed = (
            prompt.splitlines()[0]
            + "\n【直观看审失败后的强制分时动作合同】"
            + TIMELINES[unit_id]
            + "镜头全程固定；每帧必须让前态、接触、反馈、终态按此顺序只发生一次。\n"
            + "\n".join(prompt.splitlines()[1:])
            + "\n"
        )
        prompt_path = PROMPT_DIR / f"{unit_id}.txt"
        prompt_path.write_text(changed, encoding="utf-8")
        task = copy.deepcopy(task)
        task["task_key"] = f"{unit_id}-ATOMIC-DIRECT-WATCH-RETRY-V3"
        task["batch_id"] = "E37-ATOMIC-DIRECT-WATCH-FAILED-RETRY-V3-20260803"
        task["prompt_path"] = str(prompt_path.relative_to(ROOT))
        task["prompt_file"] = task["prompt_path"]
        task["prompt_sha256"] = digest(prompt_path)
        task["status"] = "READY_TO_SUBMIT"
        task["dependencies_ready"] = True
        task["material_change"] = {
            "type": "DIRECT_WATCH_CAUSAL_TIMELINE_REWRITE",
            "source_failure": retry["direct_watch_failure_evidence"],
            "timeline": TIMELINES[unit_id],
        }
        task["performance_spec"]["motion_beats"][0]["viewer_read"] = TIMELINES[unit_id]
        tasks.append(task)
    retry["tasks"] = tasks
    source_anchor_path = ROOT / retry["anchor_count_plan_ref"]
    anchor = json.loads(source_anchor_path.read_text(encoding="utf-8"))
    anchor["units"] = [row for row in anchor["units"] if row["unit_id"] in FAILED]
    anchor["planned_reference_image_count"] = sum(row["planned_reference_image_count"] for row in anchor["units"])
    anchor_path = OUT.parent / "E37_ACTION_DIRECT_WATCH_RETRY_ANCHOR_PLAN_V3.json"
    anchor_path.parent.mkdir(parents=True, exist_ok=True)
    anchor_path.write_text(json.dumps(anchor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    retry["anchor_count_plan_ref"] = str(anchor_path.relative_to(ROOT))
    manifest_path = OUT.parent / "E37_ACTION_DIRECT_WATCH_RETRY_COMPLETE_PROMPT_MANIFEST_V3.json"
    manifest = {
        "schema": "qingshan.complete_video_prompt_manifest.v1",
        "episode": "E37",
        "all_units_have_prompt": True,
        "unit_count": len(tasks),
        "source_plan": retry["anchor_count_plan_ref"],
        "source_plan_sha256": digest(ROOT / retry["anchor_count_plan_ref"]),
        "source_scene_authority": retry["scene_contract_ref"],
        "source_scene_authority_sha256": digest(ROOT / retry["scene_contract_ref"]),
        "rows": [
            {
                "unit_id": task["unit_id"],
                "scene_id": task["scene_id"],
                "weather": "RAIN_NIGHT",
                "prompt_path": task["prompt_path"],
                "prompt_sha256": task["prompt_sha256"],
            }
            for task in tasks
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    retry["complete_video_prompt_manifest_ref"] = str(manifest_path.relative_to(ROOT))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(retry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", "config": str(OUT.relative_to(ROOT)), "tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
