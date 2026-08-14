#!/usr/bin/env python3
"""Build the second failed-only E27 still repair batch from R1 review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r1/image_batch_failed_only_r1.json"
REPORT = ROOT / "qa/e27_writer_agent_stills_v1_failed_only_r1_ai_review_20260720/E27_WRITER_AGENT_9_STILL_R1_AI_REVIEW_RESULT.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r2"
CORRECTIONS = {
    "E27-N01": "R2 唯一修复：搜查令以完全空白、没有任何墨迹或印纹的背面朝上拍在诊案；纸面必须是纯白纤维，只允许纸边阴影和折痕，禁止任何书法、笔划、红印、符号、伪字。保持十一名以上轮廓分离的铁甲兵与刀锋压案。",
    "E27-N09": "R2 唯一修复：柜体正面明确做成纵向三层，第一、第二层装满卷轴，第三层是唯一完全空置的矩形格；女阴神透明指尖伸入青铜锁孔并准确指向第三层空格，空格右侧只有一枚无字纯红圆形新封痕。层级、空格、指尖三者不可遮挡。",
    "E27-N11": "R2 唯一修复：前景陈迹两指正把铜钥匙从第一名守卫腰带铜环抽出；背景必须另有第二名守卫作为清楚分离的完整人物，持刀朝陈迹冲来，身体运动方向指向前景；两名守卫不得重叠或合并。",
    "E27-N19": "R2 唯一修复：执行动作的人必须是陈迹[[c_chenji]]，17 岁男性、与参考图一致的年轻男性面容和浅灰长袍，绝不能是黑衣女性。陈迹左手在空中接住正在下落的纯白无字拓片，右手把纯色无字时辰签贴向男性文书残影胸前；画面不出现其他女性实体。",
    "E27-N24": "R2 唯一修复：彻底移除前景所有展开纸张、挂纸、卷轴标签和可见书脊；剩余书册全部以纯色无字封面背向镜头，任何表面不得出现墨迹、刻痕、符号或伪字。保持陈迹跃窗、女性兔耳阴神穿墙、脚下双刀交叉三个动作关系。",
}


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    review = json.loads(REPORT.read_text(encoding="utf-8"))
    failed = {Path(row["path"]).name.split("_E27-")[1].split("-")[0] for row in []}
    failed_ids = {
        task["shot_id"]
        for task in source["tasks"]
        if any(Path(row["path"]).name.startswith(f"E27_{task['task_key']}_") for row in review["content_failed_items"])
    }
    if failed_ids != set(CORRECTIONS):
        raise SystemExit(f"failed-item drift: {sorted(failed_ids)}")
    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    manifest = ["# E27 Writer Agent 静图 failed-only R2 提示词", "", "仅包含 R1 复审仍失败的五项。", ""]
    for task in source["tasks"]:
        shot_id = task["shot_id"]
        if shot_id not in CORRECTIONS:
            continue
        original = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        text = original + "\nFAILED_ONLY_R2_CORRECTION: " + CORRECTIONS[shot_id] + "\n"
        prompt_path = prompt_dir / f"{shot_id}-R2.txt"
        prompt_path.write_text(text, encoding="utf-8")
        row = dict(task)
        row["task_key"] = task["task_key"].replace("-R1", "-R2")
        row["prompt_file"] = str(prompt_path.relative_to(ROOT))
        row["prompt_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row["status"] = "READY_FAILED_ONLY_R2_PARALLEL_SUBMIT"
        row["retry_reason"] = "AI_REVIEW_0P8P0_R1_CONTENT_FAIL"
        tasks.append(row)
        manifest.extend([f"## {shot_id}", "", text, ""])
    config = dict(source)
    config.update({
        "status": "READY_FAILED_ONLY_R2_CONCURRENT_SUBMIT",
        "concurrency": len(tasks),
        "output_dir": "working_assets/e27_writer_agent_stills_v1_failed_only_r2_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_stills_v1_failed_only_r2_20260720",
        "base_batch_note": "Retry only five R1 content failures; retain nineteen admitted candidates.",
        "source_ai_review": str(REPORT.relative_to(ROOT)),
        "tasks": tasks,
    })
    manifest_path = DEST / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R2.md"
    manifest_path.write_text("\n".join(manifest), encoding="utf-8")
    config["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    config_path = DEST / "image_batch_failed_only_r2.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": len(tasks), "config": str(config_path.relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
