#!/usr/bin/env python3
"""Build the third failed-only E27 still repair batch from R2 review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r2/image_batch_failed_only_r2.json"
REPORT = ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r2_ai_review_20260720/E27_WRITER_AGENT_5_STILL_R2_AI_REVIEW_RESULT.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r3"
CORRECTIONS = {
    "E27-N09": (
        "R3 唯一修复：画面内彻底禁止任何文字载体、书写痕迹、刻痕、标签、印章纹样、符号和伪字。"
        "柜内卷轴全部只露纯色无字卷面或圆形卷端；第三层空格右侧只保留一个没有任何纹理的纯红色圆点。"
        "女阴神透明指尖穿过青铜锁孔，明确指向唯一空置的第三层矩形格；不得新增纸条、封签、书脊文字或装饰纹样。"
    ),
    "E27-N19": (
        "R3 唯一修复：地点必须一眼读成文书房外的狭长木构回廊，而不是档房或书库。"
        "竖屏纵深中必须同时看见连续廊柱、横梁、栏杆、尽头转角和沿廊排列的壁灯；禁止书架、卷宗架、柜体或室内档房背景。"
        "陈迹仍在回廊中接住纯白无字拓片，并把纯色无字时辰签贴向男性文书残影胸前；人物与物证动作保持不变。"
    ),
}


def failed_shot_ids(source: dict, review: dict) -> set[str]:
    failed_paths = {
        Path(issue["media_path"]).name
        for item in review.get("items", [])
        if item.get("content_status") == "CONTENT_FAIL"
        for issue in item.get("issues", [])
        if issue.get("media_path")
    }
    return {
        task["shot_id"]
        for task in source["tasks"]
        if any(name.startswith(f"E27_{task['task_key']}_") for name in failed_paths)
    }


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    review = json.loads(REPORT.read_text(encoding="utf-8"))
    failed_ids = failed_shot_ids(source, review)
    if failed_ids != set(CORRECTIONS):
        raise SystemExit(f"failed-item drift: {sorted(failed_ids)}")

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    manifest = [
        "# E27 Writer Agent 静图 failed-only R3 提示词",
        "",
        "仅包含 R2 真实多模态复审仍失败的两项；其余 22 镜保留。",
        "",
    ]
    for task in source["tasks"]:
        shot_id = task["shot_id"]
        if shot_id not in CORRECTIONS:
            continue
        original = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        text = original + "\nFAILED_ONLY_R3_CORRECTION: " + CORRECTIONS[shot_id] + "\n"
        prompt_path = prompt_dir / f"{shot_id}-R3.txt"
        prompt_path.write_text(text, encoding="utf-8")
        row = dict(task)
        row["task_key"] = task["task_key"].replace("-R2", "-R3")
        row["prompt_file"] = str(prompt_path.relative_to(ROOT))
        row["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row["status"] = "READY_FAILED_ONLY_R3_PARALLEL_SUBMIT"
        row["retry_reason"] = "AI_REVIEW_0P8P0_R2_CONTENT_FAIL"
        tasks.append(row)
        manifest.extend([f"## {shot_id}", "", text, ""])

    config = dict(source)
    config.update({
        "status": "READY_FAILED_ONLY_R3_CONCURRENT_SUBMIT",
        "concurrency": len(tasks),
        "output_dir": "working_assets/e27_writer_agent_stills_v1_failed_only_r3_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_stills_v1_failed_only_r3_20260720",
        "base_batch_note": "Retry only two R2 content failures; retain twenty-two admitted candidates.",
        "source_ai_review": str(REPORT.relative_to(ROOT)),
        "tasks": tasks,
    })
    manifest_path = DEST / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R3.md"
    manifest_path.write_text("\n".join(manifest), encoding="utf-8")
    config["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    config_path = DEST / "image_batch_failed_only_r3.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": len(tasks), "config": str(config_path.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
