#!/usr/bin/env python3
"""Build the one-time editable all-episode script/dialogue review master."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "codex_docs" / "共享审稿_青山全剧剧本与对白_E01-E16_20260712.md"

FULL_SOURCES = {
    1: "upload_scripts/qingshan_E01_rework_12shot_consistency_locked_movie_mode.txt",
    2: "upload_scripts/qingshan_E02_grid_storyboard_mode_20shots_v1.txt",
    3: "upload_scripts/qingshan_E03_full_redo_chinese_audio_locked_v4_20260626.txt",
    4: "upload_scripts/qingshan_E04_clean_platform_dialogue_redo_v5_20260630.txt",
    5: "upload_scripts/qingshan_E05_grid_storyboard_mode_20shots_v3_20260703.txt",
    6: "upload_scripts/qingshan_E06_grid_storyboard_mode_20shots_v1_20260704.txt",
    7: "upload_scripts/qingshan_E07_grid_storyboard_mode_26shots_v3_20260705.txt",
    8: "upload_scripts/qingshan_E08_grid_storyboard_mode_24shots_v1_20260705.txt",
    9: "upload_scripts/qingshan_E09_grid_storyboard_mode_20shots_v2_fast_20260709.txt",
    10: "upload_scripts/qingshan_E10_grid_storyboard_mode_20shots_v1_director_coverage_20260709.txt",
    11: "upload_scripts/qingshan_E11_grid_storyboard_mode_20shots_v1_director_coverage_20260710.txt",
    12: "upload_scripts/qingshan_E12_grid_storyboard_mode_20shots_v1_director_coverage_20260710.txt",
}

STRUCTURED_SOURCES = {
    13: "configs/e13_continuity_config_20shots_20260710.json",
    14: "configs/e14_continuity_config_20shots_20260711.json",
    15: "configs/e15_continuity_config_20shots_20260711.json",
    16: "configs/e16_dialogue_beat_sheet_20260711.json",
}


def esc(value: Any) -> str:
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", "<br>")


def task_intro(ep: int) -> str:
    path = ROOT / "workflow" / "tasks" / f"E{ep:02d}_TASK.md"
    text = path.read_text(encoding="utf-8")
    end_markers = ("## P0 待产物", "## P0 Deliverables", "## P0 Files To Create", "## 执行记录", "## 2026-")
    positions = [text.find(marker) for marker in end_markers if text.find(marker) > 0]
    return text[: min(positions)] if positions else text[:5000]


def render_structured(ep: int, data: dict[str, Any]) -> str:
    out = [task_intro(ep).strip(), "", "### 结构化镜头/对白表", ""]
    if ep == 16:
        out.append("| ID | 说话人 | 听者 | 台词 | 听者反应 | 戏剧功能 |")
        out.append("|---|---|---|---|---|---|")
        for line in data.get("lines") or []:
            out.append("| " + " | ".join(esc(line.get(k)) for k in ("id", "speaker", "listener", "text", "listener_reaction", "function")) + " |")
        return "\n".join(out)

    shots = data.get("shots") or data.get("shot_expectations") or data.get("shot_requirements") or {}
    iterable = shots if isinstance(shots, list) else [dict({"id": key}, **value) for key, value in shots.items()]
    out.append("| 镜头 | 时间/地点 | 角色 | 动作/必须展示 | 对白/说话人 | 变化/禁止项 |")
    out.append("|---|---|---|---|---|---|")
    for shot in iterable:
        timing = f"{shot.get('start', '')}-{shot.get('end', '')}s" if "start" in shot else shot.get("location") or shot.get("room_id")
        must = shot.get("must_show") or shot.get("coverage") or shot.get("action") or "-"
        dialogue = shot.get("dialogue")
        if dialogue is True:
            dialogue = f"[原配置仅标记有对白，待审稿补全文] {shot.get('speaker', '')}"
        delta = shot.get("delta") or shot.get("must_not_show") or shot.get("text_composite_required") or "-"
        row = (shot.get("id"), timing, shot.get("characters"), must, dialogue, delta)
        out.append("| " + " | ".join(esc(v) for v in row) + " |")
    return "\n".join(out)


def main() -> None:
    sections = [
        "# 《青山》全剧剧本与对白共享审稿总稿（E01-E16）",
        "",
        f"> 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        "> 状态：`SHARED_EDITORIAL_SOURCE`。Roger 与 Claude 可直接修改本文件。修改后，本文件优先于旧上传稿、任务卡和镜头配置；Codex 在继续相关剧集前必须读取并把修改同步回生产配置。",
        "> 禁止自动覆盖：本生成器只用于首次汇总。文件进入人工审稿后，除非 Roger 明确要求重建，不得再次运行覆盖。",
        "",
        "## 审稿统一检查项",
        "",
        "- 人物目的、关系旧账、潜台词是否清楚；台词是否只能由这个人物在此刻说出。",
        "- 是否存在 AI 味：人人金句、抽象名词堆叠、工整排比、复述画面、连续解释世界观。",
        "- 天气、服装、身份和动作是否有剧情因果；是否又无理由回到雨夜/阴天模板。",
        "- 每场是否有 action / reaction / irreversible delta；对白是否真正改变关系或局面。",
        "- 修改请直接改正文，可用 `<!-- REVIEW: ... -->` 留监制意见；确认稿标记 `REVIEW_STATUS: APPROVED`。",
        "",
    ]

    for ep in range(1, 17):
        sections.extend([f"# E{ep:02d}", ""])
        if ep in FULL_SOURCES:
            source = ROOT / FULL_SOURCES[ep]
            sections.extend([
                f"- `REVIEW_STATUS`: PENDING",
                f"- 来源：`{source}`",
                "- 来源级别：当时正式/重做上传稿，以下原文完整保留。",
                "",
                source.read_text(encoding="utf-8").strip(),
                "",
            ])
        else:
            source = ROOT / STRUCTURED_SOURCES[ep]
            data = json.loads(source.read_text(encoding="utf-8"))
            sections.extend([
                "- `REVIEW_STATUS`: PENDING",
                f"- 来源：`workflow/tasks/E{ep:02d}_TASK.md` + `{source}`",
                "- 来源级别：从任务卡和结构化生产配置复原；标记“待审稿补全文”的位置不是新编对白。",
                "",
                render_structured(ep, data),
                "",
            ])

    OUT.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
