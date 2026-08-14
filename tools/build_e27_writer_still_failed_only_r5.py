#!/usr/bin/env python3
"""Build the fifth failed-only E27 still repair batch from R4 review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r4/image_batch_failed_only_r4.json"
REPORT = ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r4_ai_review_20260720/E27_WRITER_AGENT_1_STILL_R4_AI_REVIEW_RESULT.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r5"
SHOT_ID = "E27-N09"
CORRECTION = (
    "R5 唯一修复：采用证据特写构图，第三层唯一空置矩形格占画面右侧主要面积，纯红无纹圆形新封痕贴在该空格的右内壁。"
    "皎兔女阴神的半透明食指必须直接接触红色新封痕，指尖与红点发生清楚的物理接触，不留间隔；她的视线也落在接触点。"
    "青铜锁孔、穿锁的透明前臂、空格和指尖触封痕必须同时可见并形成连续动作因果。"
    "保持18岁女性面容与两只清晰半透明兔耳灵光剪影；禁止普通发髻替代兔耳。"
    "其余层只露纯色无字卷端；禁止文字、符号、刻痕、标签、印章纹样、额外红点和额外人物。"
)


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    review = json.loads(REPORT.read_text(encoding="utf-8"))
    failed_paths = {
        Path(issue["media_path"]).name
        for item in review.get("items", [])
        if item.get("content_status") == "CONTENT_FAIL"
        for issue in item.get("issues", [])
        if issue.get("media_path")
    }
    source_task = next(task for task in source["tasks"] if task["shot_id"] == SHOT_ID)
    expected_prefix = f"E27_{source_task['task_key']}_"
    if len(failed_paths) != 1 or not next(iter(failed_paths)).startswith(expected_prefix):
        raise SystemExit(f"failed-item drift: {sorted(failed_paths)}")

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    original = (ROOT / source_task["prompt_file"]).read_text(encoding="utf-8").rstrip()
    text = original + "\nFAILED_ONLY_R5_CORRECTION: " + CORRECTION + "\n"
    prompt_path = prompt_dir / f"{SHOT_ID}-R5.txt"
    prompt_path.write_text(text, encoding="utf-8")
    task = dict(source_task)
    task["task_key"] = source_task["task_key"].replace("-R4", "-R5")
    task["prompt_file"] = str(prompt_path.relative_to(ROOT))
    task["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    task["status"] = "READY_FAILED_ONLY_R5_PARALLEL_SUBMIT"
    task["retry_reason"] = "AI_REVIEW_0P8P0_R4_CONTENT_FAIL"

    config = dict(source)
    config.update({
        "status": "READY_FAILED_ONLY_R5_CONCURRENT_SUBMIT",
        "concurrency": 1,
        "output_dir": "working_assets/e27_writer_agent_stills_v1_failed_only_r5_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_stills_v1_failed_only_r5_20260720",
        "base_batch_note": "Retry only E27-N09 from R4; retain twenty-three admitted candidates.",
        "source_ai_review": str(REPORT.relative_to(ROOT)),
        "tasks": [task],
    })
    manifest_path = DEST / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R5.md"
    manifest_path.write_text(f"# E27 Writer Agent 静图 failed-only R5 提示词\n\n## {SHOT_ID}\n\n{text}\n", encoding="utf-8")
    config["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    config_path = DEST / "image_batch_failed_only_r5.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": 1, "config": str(config_path.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
