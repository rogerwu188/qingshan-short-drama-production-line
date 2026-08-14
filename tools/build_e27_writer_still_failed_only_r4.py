#!/usr/bin/env python3
"""Build the fourth failed-only E27 still repair batch from R3 review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r3/image_batch_failed_only_r3.json"
REPORT = ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r3_ai_review_20260720/E27_WRITER_AGENT_2_STILL_R3_AI_REVIEW_RESULT.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r4"
SHOT_ID = "E27-N09"
CORRECTION = (
    "R4 唯一修复：女阴神必须保持皎兔法定身份，18 岁年轻女性面容，并在头顶显出两只清晰、对称、半透明的兔耳灵光剪影；"
    "不得生成普通发髻轮廓替代兔耳，不得变成男性或泛用女鬼。构图必须让她的透明食指从青铜锁孔穿入，"
    "指尖几乎触到第三层唯一空置矩形格右边缘的纯红无纹圆点；指尖、空格、红点三者处于同一焦平面并形成明确对角线。"
    "第一、第二层卷轴只能露纯色无字卷端，画面禁止任何文字、符号、刻痕、标签和印章纹样。"
)


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
    if failed_ids != {SHOT_ID}:
        raise SystemExit(f"failed-item drift: {sorted(failed_ids)}")
    source_task = next(task for task in source["tasks"] if task["shot_id"] == SHOT_ID)

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    original = (ROOT / source_task["prompt_file"]).read_text(encoding="utf-8").rstrip()
    text = original + "\nFAILED_ONLY_R4_CORRECTION: " + CORRECTION + "\n"
    prompt_path = prompt_dir / f"{SHOT_ID}-R4.txt"
    prompt_path.write_text(text, encoding="utf-8")

    task = dict(source_task)
    task["task_key"] = source_task["task_key"].replace("-R3", "-R4")
    task["prompt_file"] = str(prompt_path.relative_to(ROOT))
    task["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    task["status"] = "READY_FAILED_ONLY_R4_PARALLEL_SUBMIT"
    task["retry_reason"] = "AI_REVIEW_0P8P0_R3_CONTENT_FAIL"

    config = dict(source)
    config.update({
        "status": "READY_FAILED_ONLY_R4_CONCURRENT_SUBMIT",
        "concurrency": 1,
        "output_dir": "working_assets/e27_writer_agent_stills_v1_failed_only_r4_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_stills_v1_failed_only_r4_20260720",
        "base_batch_note": "Retry only E27-N09 from R3; retain twenty-three admitted candidates.",
        "source_ai_review": str(REPORT.relative_to(ROOT)),
        "tasks": [task],
    })
    manifest_path = DEST / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R4.md"
    manifest_path.write_text(f"# E27 Writer Agent 静图 failed-only R4 提示词\n\n## {SHOT_ID}\n\n{text}\n", encoding="utf-8")
    config["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    config_path = DEST / "image_batch_failed_only_r4.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": 1, "config": str(config_path.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
