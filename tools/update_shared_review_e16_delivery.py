#!/usr/bin/env python3
"""Update only the E16 tail of the shared review master, preserving E01-E15 edits."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "codex_docs" / "共享审稿_青山全剧剧本与对白_E01-E16_20260712.md"
DIALOGUE = ROOT / "configs" / "e16_dialogue_beat_sheet_20260711.json"
TASK = ROOT / "workflow" / "tasks" / "E16_TASK.md"


def esc(value) -> str:
    if isinstance(value, list):
        value = "、".join(str(v) for v in value)
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", "<br>")


def main() -> None:
    master = MASTER.read_text(encoding="utf-8")
    marker = "# E16\n"
    if marker not in master:
        raise SystemExit("E16 marker missing")
    prefix = master.split(marker, 1)[0]
    task = TASK.read_text(encoding="utf-8")
    cut = task.find("## P0 待产物")
    task_intro = task[:cut if cut > 0 else 5000].strip()
    data = json.loads(DIALOGUE.read_text(encoding="utf-8"))
    out = [
        "# E16",
        "",
        "- `REVIEW_STATUS`: APPROVED_WITH_MANDATORY_REVISIONS",
        f"- 来源：`{TASK}` + `{DIALOGUE}`",
        "- 台词状态：62 句已按爆款语料实测规范完成 v2 改写，待 Claude 复核。",
        "- 表演状态：角色表演圣经 v2 已获监制定调批准；逐句受限枚举 delivery 等本轮对白终审后编译。旧自由散文语气包已标 SUPERSEDED_DRAFT_DO_NOT_USE。",
        "",
        task_intro,
        "",
        "### 结构化镜头/对白/表演表",
        "",
        "| ID | 说话人→听者 | 台词 | 戏剧功能 | 表演状态 | 听者反应 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for line in data["lines"]:
        row = [
            line["id"],
            f"{line['speaker']}→{line['listener']}",
            line["text"],
            line["function"],
            line.get("delivery_status", "PENDING"),
            line["listener_reaction"]
        ]
        out.append("| " + " | ".join(esc(v) for v in row) + " |")
    MASTER.write_text(prefix + "\n".join(out) + "\n", encoding="utf-8")
    print(f"updated E16 lines={len(data['lines'])}")


if __name__ == "__main__":
    main()
