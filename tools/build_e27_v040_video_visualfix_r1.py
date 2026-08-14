#!/usr/bin/env python3
"""Build the 14-shot failed-only E27 semantic visual repair batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE_CONFIG = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_v1/video_batch_v1.json"
REVIEW = ROOT / "qa/e27_writer_agent_v040_video_visual_sheets_20260720/E27_24_VIDEO_VISUAL_SHEET_AI_REVIEW_RESULT.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_visualfix_r1_failed_only"


REPAIR_TEXT = {
    "canonical_identity_continuity": "三时点人物必须保持参考图同一张脸、同一年龄、同一性别、同一妆发服装；禁止换脸或身份漂移。",
    "scene_authority": "起始、中段、结尾都必须留在输入图锁定的同一地点、同一时段和同一光源；禁止切换房间、街巷或天气。",
    "story_action_clarity": "全镜只把既定唯一事件按起因、接触、结果清晰做完；每一阶段都必须看得出同一动作因果，禁止用站立、空镜或特效替代动作。",
    "no_text_or_pseudotext": "所有纸张、账册、封签、门牌和背景表面必须纯净无字或彻底失焦；禁止任何汉字轮廓、拉丁字母、数字和伪文字纹理。",
    "no_extra_or_duplicated_bodies": "人物数量严格等于参考图与剧情合同；同一角色全程只出现一次，禁止镜面复制、残影实体化、分身或多余人形。",
    "native_anatomy": "手、臂、腿和躯干保持自然人体结构与受力关系；手指数目正确，关节不反折，肢体不融合、不穿模。",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    base = load(BASE_CONFIG)
    review = load(REVIEW)
    failed: dict[str, list[str]] = {}
    for item in review["items"]:
        checks = item.get("capabilities", {}).get("image_analysis", {}).get("checks", {})
        failures = [name for name, status in checks.items() if status == "FAIL"]
        if failures:
            failed[item["agentcut"]["clip_id"]] = failures
    if len(failed) != 14:
        raise SystemExit(f"expected 14 failed shots, got {len(failed)}")

    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for source_task in base["tasks"]:
        shot_id = source_task["shot_id"]
        if shot_id not in failed:
            continue
        original = (ROOT / source_task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        addendum = "\n【R1多模态审片定向修复硬门】\n" + "\n".join(
            f"- {REPAIR_TEXT[name]}" for name in failed[shot_id]
        )
        addendum += (
            "\n- 输入图继续作为唯一身份、场景、服装、道具和空间锚点；修复只针对上述失败项，禁止改变剧本事实。"
            "\n- 生成前逐项自检；任一修复项不满足时不得用奇观、雾气、月光、字幕或新角色掩盖。\n"
        )
        prompt_path = prompt_dir / f"{shot_id}.txt"
        prompt_path.write_text(original + addendum, encoding="utf-8")
        task = dict(source_task)
        task.update({
            "task_key": f"{shot_id}-WRITER-AGENT-V040-VIDEO-VISUALFIX-R1",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "prompt_sha256": sha256(prompt_path),
            "retry_reason": "AI_REVIEW_V080_VISUAL_SHEET_CONTENT_FAIL",
            "repair_checks": failed[shot_id],
            "status": "READY_FAILED_ONLY_CONCURRENT_SUBMIT",
        })
        tasks.append(task)

    config = dict(base)
    config.update({
        "status": "READY_14_VISUALFIX_R1_FAILED_ONLY_CONCURRENT_SUBMIT",
        "concurrency": 14,
        "max_retries": 0,
        "output_dir": "working_assets/e27_writer_agent_v040_video_visualfix_r1_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v040_video_visualfix_r1_20260720",
        "base_batch_note": (
            "One targeted semantic visual repair for the 14 AI-review failures. Preserve the 10 visual PASS videos; "
            "never resubmit them. After this batch, select the best candidate under the conditional-admission policy."
        ),
        "tasks": tasks,
    })
    DEST.mkdir(parents=True, exist_ok=True)
    config_path = DEST / "video_batch_visualfix_r1_failed_only.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "tasks": len(tasks),
        "shots": sorted(failed),
        "config": str(config_path.relative_to(ROOT)),
        "config_sha256": sha256(config_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
