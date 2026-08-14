#!/usr/bin/env python3
"""Build one last narrowly scoped N17 repair without replaying the entry action."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_visualfix_r1_failed_only/video_batch_visualfix_r1_failed_only.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/video_batch_n17_visualfix_r2_failed_only"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    source = next(row for row in base["tasks"] if row["shot_id"] == "E27-N17")
    prompt = """这是《青山》E27 E27-N17 的 Seedance 2.0 Pro 多模态分镜视频。
【唯一输入锚点】[[image_1]]是本镜唯一身份、人数、构图、服装、道具、地点、夜间光线与空间锚点。画面中严格只有两个人：左侧唯一守卫、右侧唯一陈迹。不得增加第三人，不得让任何人从门外进入，不得出现残影、分身、镜像或背景人形。
【规格】7秒，竖屏9:16，720p，写实国漫古装武侠电影质感；禁止外部BGM、字幕、水印、Logo、文字或伪文字。
【景别与定场】本镜是唯一大远景定场，保持输入图的 ultra-wide establishing 纵深；全程不切换到中景或近景。
【单一连续镜头】全程不切镜，不重演破门，不改变场景。直接从输入图已经形成的争夺姿态开始：左侧守卫双手只抓住同一张拓片左端，右侧陈迹右手只抓住同一张拓片右端并以肩抵住守卫胸甲。两人维持一条明确受力轴，拓片始终绷直、完整、不复制、不变成绳索。
【0.0-2.0秒】固定超广角构图，只有两人短促呼吸、衣袖与甲片轻微受力；两张脸、四条手臂、两双手位置稳定，绝不长出额外肢体。
【2.0-5.5秒】两人沿现有相反方向各自增加一次持续发力，肩甲接触更紧，纸纤维轻响；人物脚位不换，守卫不离开左侧，陈迹不离开右侧，不新增动作阶段。
【5.5-7.0秒】力量达到峰值后停稳在输入图同一决定性瞬间；拓片仍为一张、笔直、完整，两人仍各出现一次。
镜头1【0.0-7.0秒，超广角大远景，稳定固定机位】：左侧守卫持续抓紧拓片左端，右侧陈迹持续拉紧拓片右端并以肩抵住胸甲，两人增加一次相反方向的发力后停稳；不切镜、不改变视角，仅允许极轻微自然呼吸感。{无对白}<纸纤维受力、甲片轻碰、短促呼吸> 禁止推拉摇移、反向揭示、快速剪切、特写插入或视角跳变。宁可保持输入图稳定，也不得生成新角色或改变动作事实。
【色彩与光影】保持输入图冷蓝黑位与暖色灯笼动机光，三角色控制 palette，肤色自然，甲片与纸纤维材质清晰；禁止改变光源方向。
【力量与环境介质】力量只通过两人肩甲接触、甲片轻颤、衣料绷紧与纸纤维受力表现；环境木架与灯火只允许极轻微真实反馈，禁止木屑、尘雾、碎片、火焰爆发或额外人形。
【现场声】仅纸纤维受力声、甲片轻碰、两人呼吸、室内木构微响；声音与发力同步，禁止台词、旁白与外部BGM。
【绝对禁止】重新破门、人物入场、第三人、背景守卫、多人围观、分身、双胞胎、残影实体化、镜像人物、肢体融合、手臂增生、换脸、换装、换地点、换时段、纸张复制、纸张断裂、月亮雾气奇观、慢动作、循环动作、可读文字、伪文字、字幕、水印、Logo。
"""
    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / "E27-N17.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    task = dict(source)
    task.update({
        "task_key": "E27-N17-WRITER-AGENT-V040-VIDEO-VISUALFIX-R2",
        "prompt_file": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256(prompt_path),
        "retry_reason": "R1_CREATED_EXTRA_ENTERING_GUARD_BY_REPLAYING_ALREADY_COMPLETED_ENTRY_ACTION",
        "repair_checks": [
            "exact_two_person_cast",
            "single_tug_action_from_existing_source_pose",
            "no_entry_or_replayed_break_in",
            "no_extra_or_duplicated_bodies",
            "stable_scene_authority",
        ],
        "status": "READY_FAILED_ONLY_SUBMIT",
    })
    config = dict(base)
    config.update({
        "status": "READY_N17_VISUALFIX_R2_FAILED_ONLY_SUBMIT",
        "concurrency": 1,
        "max_retries": 0,
        "output_dir": "working_assets/e27_writer_agent_v040_video_n17_visualfix_r2_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_v040_video_n17_visualfix_r2_20260720",
        "base_batch_note": "Final narrow N17 repair. Reuse the exact approved still and animate only the already-established two-person tug pose.",
        "tasks": [task],
    })
    DEST.mkdir(parents=True, exist_ok=True)
    config_path = DEST / "video_batch_n17_visualfix_r2_failed_only.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "config": str(config_path.relative_to(ROOT)),
        "config_sha256": sha256(config_path),
        "prompt": str(prompt_path.relative_to(ROOT)),
        "prompt_sha256": sha256(prompt_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
