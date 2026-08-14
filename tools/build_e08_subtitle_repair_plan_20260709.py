#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from build_e08_api_fallback_plan_20260709 import (
    ROOT,
    load_json,
    parse_prompt_sections,
    references_for,
    shot_duration,
)


AFFECTED_SHOTS = ["07", "09", "10", "14", "20", "22"]
OUT_DIR = ROOT / "working_assets/e08_subtitle_repair_20260709"
PROMPT_DIR = OUT_DIR / "prompts"
VIDEO_DIR = OUT_DIR / "videos"
CONTINUITY = ROOT / "configs/e08_continuity_config_v1_24shots_20260705.json"
HARD_PROMPTS = ROOT / "qa/e08_repair_20260709/e08_row05_23_hard_bound_storyboard_prompts_20260709.md"

NO_VISIBLE_SUBTITLE_RULE = """字幕返修硬规则：
1. 画面中绝对不要出现任何字幕、对白贴字、白色字幕、屏幕文字、漂浮文字、歌词条、说明文字或中英文叠字。
2. 不要把台词写在画面上；只让角色用普通话自然说出台词。
3. 保留真实环境声、衣料声、脚步声和必要拟音；对白清晰，BGM 低量避让。
4. 不能改变已经通过的角色、服装、道具、场景和空间方向。
5. 如果模型想生成字幕或屏幕文字，必须改为无文字画面。"""


def build_prompt(shot: dict, hard_prompt: str, refs: list[str]) -> str:
    shot_id = str(shot.get("id") or shot.get("shot_id")).zfill(2)
    ref_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1))
    return f"""E08《站桩救命》字幕污染返修镜头 {shot_id}

返修原因：
上一版源片中该镜头出现了模型自动烧入的画面字幕，导致整集有些镜头有字幕、有些镜头没有字幕，且字幕位置不统一。本次只修复“源片可见字幕污染”，不能改变镜头剧情和已通过的一致性。

参考图片顺序：
{ref_lines}

连续性锚点：
- 场景/房间：{shot.get("room_id", "")}
- 出场角色：{"、".join(shot.get("characters") or []) or "无"}
- 关键道具：{"、".join(shot.get("props") or []) or "无"}

原镜头硬绑定提示词：
{hard_prompt}

{NO_VISIBLE_SUBTITLE_RULE}

输出要求：
- 9:16，720p，电影写实中国古装短剧。
- 必须是真人动态短剧视频，有清晰普通话对白和同步动作。
- 不能生成静态图、分镜表、首帧幻灯片、无声片段、英文、外语、现代服装、欧美人物、随机换脸。
- 结尾保留半秒动作/声桥，便于与下一镜衔接。
"""


def main() -> int:
    continuity = load_json(CONTINUITY)
    hard_prompts = parse_prompt_sections(HARD_PROMPTS)
    shots_by_id = {
        str(shot.get("id") or shot.get("shot_id")).zfill(2): shot
        for shot in continuity.get("shots", [])
    }
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    plan = []
    for shot_id in AFFECTED_SHOTS:
        shot = shots_by_id[shot_id]
        hard_prompt = hard_prompts[shot_id]
        refs = references_for(shot)
        prompt_path = PROMPT_DIR / f"e08_shot_{shot_id}_no_visible_subtitles.txt"
        prompt_path.write_text(build_prompt(shot, hard_prompt, refs), encoding="utf-8")
        plan.append(
            {
                "shot_id": shot_id,
                "title": f"E08 Row{shot_id} subtitle repair",
                "duration": shot_duration(shot),
                "prompt_file": str(prompt_path),
                "references": refs,
                "out_dir": str((VIDEO_DIR / f"shot_{shot_id}").resolve()),
                "models": ["seedance-2.0-pro", "sora2", "veo3.1", "wan2.7", "kling"],
                "repair_reason": "remove inconsistent model-burned visible subtitles while preserving passed continuity",
            }
        )

    plan_path = OUT_DIR / "run_plan_subtitle_repair.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": AFFECTED_SHOTS, "run_plan": str(plan_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
