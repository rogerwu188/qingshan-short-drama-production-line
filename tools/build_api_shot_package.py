#!/usr/bin/env python3
"""
Build per-shot API prompts and reference lists from a Qingshan continuity config.

This prepares a portable package for Giggle API fallback generation. The package
does not contain API keys. It writes one prompt file per shot and a run plan with
the exact reference images that must be submitted with that shot.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]

COMMON_PREFIX = """所有角色为中国/东亚古装角色。中文普通话对白必须说完整，不能英文，不能无对白，不能只做慢动作特写。视频必须同时生成对白、环境声、拟音和低量 BGM；对白处 BGM 自动闪避。画幅 9:16，720p，电影写实，动作推进，每 4 秒完成一个明确事件。禁止静态照片感、慢脸特写、欧美人物、英文字幕、英文对白、现代医院服装、随机换脸。
"""

SHOT_TABLE_HEADER = (
    "| 镜头号 | 时长(秒) | 景别 | 机位/运动 | 画面内容（含角色锚点+微表情动词） | 台词 | 环境声 | 拟音 | 备注(口型/特效/受击配对) |"
)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_v2_rows(path: Path) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    in_table = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == SHOT_TABLE_HEADER:
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        if set(line.replace("|", "").strip()) <= {"-", ":"}:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 9 or not cells[0].isdigit():
            continue
        rows[cells[0]] = {
            "shot_id": cells[0],
            "duration": cells[1],
            "shot_size": cells[2],
            "camera": cells[3],
            "picture": cells[4],
            "dialogue": cells[5],
            "ambience": cells[6],
            "foley": cells[7],
            "notes": cells[8],
        }
    return rows


def abs_existing(path_text: Optional[str]) -> Optional[str]:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve()) if path.exists() else None


def add_unique(items: List[str], value: Optional[str]) -> None:
    if value and value not in items:
        items.append(value)


def find_old_scene_frame(shot_id: str) -> Optional[str]:
    frames_dir = ROOT / "qa/e06_final_repair08_video_oldaudio_20260704/continuity_audit/frames"
    if not frames_dir.exists():
        return None
    old_id = int(shot_id)
    # v2 has 27 micro-shots while old E06 had 20 shots; use nearest old shot as
    # a scene reference only, never as identity authority.
    old_id = min(max(old_id, 1), 20)
    matches = sorted(frames_dir.glob(f"shot_{old_id:02d}_*.jpg"))
    return str(matches[0].resolve()) if matches else None


def build_references(
    shot: Dict[str, Any],
    manifest: Dict[str, Any],
    shot_id: str,
    include_old_failed_frames: bool,
) -> List[str]:
    refs: List[str] = []
    characters = manifest.get("characters", {})

    for char_id in shot.get("characters", []):
        char = characters.get(char_id, {})
        ref = abs_existing(char.get("api_reference_image") or char.get("reference_image"))
        priority = char.get("level") or char.get("priority")
        if priority in {"S", "A", "A+"}:
            add_unique(refs, ref)

    # E06 root failure was Chenji source binding. If Chenji is present, force him
    # to image slot 1 by inserting this reference first.
    if "CHAR-陈迹-古装" in shot.get("characters", []):
        chenji = characters.get("CHAR-陈迹-古装", {})
        chenji_ref = abs_existing(chenji.get("api_reference_image") or chenji.get("reference_image"))
        refs = [item for item in refs if item != chenji_ref]
        if chenji_ref:
            refs.insert(0, chenji_ref)

    # Old failed video frames often contain the exact wrong face/costume we are
    # repairing. They are opt-in only, and should be used as scene plates only
    # after masking/cropping out polluted characters.
    if include_old_failed_frames:
        add_unique(refs, find_old_scene_frame(shot_id))

    # Keep within omni-video's 9-image limit.
    return refs[:9]


def build_prompt(shot: Dict[str, Any], row: Dict[str, str], refs: List[str]) -> str:
    dialogue = row["dialogue"]
    if dialogue == "无":
        dialogue_rule = "本镜头无台词，但必须有环境声与拟音，不得静音。"
    else:
        dialogue_rule = f"本镜头只说完这一句中文普通话台词：{dialogue}。说完后停顿半秒，口型和字幕同步。"
    ref_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1)) or "- 无参考图"
    character_rules: List[str] = []
    characters = shot.get("characters", [])
    if "CHAR-陈迹-古装" in characters:
        character_rules.append(
            "陈迹：图片1是陈迹唯一身份锚点，必须严格保持同一张脸：高额头、清晰眉骨、深黑眼睛、直鼻、薄唇、干净下颌线，成熟青年质感，冷静克制，古装束发，深墨绿或黑色古装外袍，浅色只允许作为内襟小面积出现；不得改成平台随机少年脸、浅灰外袍、灰蓝长衫、浅蓝病号服感男主、蓝色衣服、现代短发或其他男角色。"
        )
    if "CHAR-云羊-古装" in characters:
        character_rules.append(
            "云羊：必须继承云羊第三张锚点图，年轻中国男性，清瘦俊美长脸，黑色窄袖密谍司劲装，高束发，胸前或袖中细长银针，轻笑但眼神冷；不得变成女性、白衣公子、陈迹或欧美脸。"
        )
    if "CHAR-皎兔-古装" in characters:
        character_rules.append(
            "皎兔：必须继承皎兔参考图，年轻中国女性，黑色窄袖密谍司劲装，发间银针，轻盈危险；不得换脸、不得变成现代装或陌生女配。"
        )
    if "CHAR-周成义-古装" in characters:
        character_rules.append(
            "周成义：40-50岁中国男性，瘦削地方官，深色官员便服，伪装镇定后露破绽；不得变成现代商人或欧美角色。"
        )
    identity_block = "\n".join(f"- {item}" for item in character_rules) or "- 本镜头无 S/A 级角色参考图，按文本角色锚点生成。"
    known_roles = {
        "CHAR-陈迹-古装": "陈迹/男主",
        "CHAR-云羊-古装": "云羊",
        "CHAR-皎兔-古装": "皎兔",
        "CHAR-周成义-古装": "周成义",
        "CHAR-黑衣汉子": "黑衣汉子",
    }
    absent = [label for char_id, label in known_roles.items() if char_id not in characters]
    absent_rule = "未列入本镜头身份锁定的角色不得出现：" + "、".join(absent) + "。" if absent else "本镜头只出现身份锁定列表中的角色，不额外生成陌生人。"
    return f"""{COMMON_PREFIX}

参考图片顺序：
{ref_lines}

本镜头身份锁定：
{identity_block}

本镜头排除规则：
- {absent_rule}
- 不要把参考图外的人物补进画面；不要让女性角色替代男性角色；不要用陌生女特写覆盖陈迹、云羊或道具镜头。

E06 v2 镜头 {row['shot_id']} / {shot.get('title', '')}
- 时长：{shot.get('duration', row['duration'])} 秒
- 景别：{row['shot_size']}
- 机位/运动：{row['camera']}
- 画面内容：{row['picture']}
- 台词：{dialogue}
- 环境声：{row['ambience']}
- 拟音：{row['foley']}
- 备注：{row['notes']}

硬性执行：
1. {dialogue_rule}
2. 使用事件驱动和动作推进，镜头内必须有明确动作变化，不要停留在脸部心理描写。
3. 角色、服装、场景、道具以参考图和本地素材库为准；出现陈迹时必须优先服从图片1。
4. 不要生成英文、外语、欧美人物、西式警匪片角色、现代病号服或随机年轻男主。
5. 本镜头结束时保留动作或声桥，便于和下一镜转场。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E06 API shot prompts and run plan.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--prompt-source", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--shots", nargs="*", help="Optional shot ids to package, e.g. 01 02.")
    parser.add_argument(
        "--include-old-failed-frames",
        action="store_true",
        help="Opt in to using old failed video frames as scene references. Default off to avoid identity pollution.",
    )
    args = parser.parse_args()

    config = load_json(Path(args.config))
    manifest = load_json(Path(args.manifest))
    rows = parse_v2_rows(Path(args.prompt_source))
    requested = set(args.shots or [])
    out_dir = Path(args.out_dir).resolve()
    prompt_dir = out_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    plan: List[Dict[str, Any]] = []
    for shot in config.get("shots", []):
        shot_id = str(shot["shot_id"]).zfill(2)
        if requested and shot_id not in requested:
            continue
        row = rows.get(shot_id)
        if not row:
            raise SystemExit(f"Missing v2 prompt table row for shot {shot_id}")
        refs = build_references(shot, manifest, shot_id, args.include_old_failed_frames)
        prompt = build_prompt(shot, row, refs)
        prompt_path = prompt_dir / f"e06_shot_{shot_id}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        plan.append(
            {
                "shot_id": shot_id,
                "title": shot.get("title", ""),
                "duration": shot.get("duration", 4),
                "prompt_file": str(prompt_path),
                "references": refs,
                "out_dir": str((out_dir / "videos" / f"shot_{shot_id}").resolve()),
                "models": ["seedance-2.0-pro", "sora2", "veo3.1", "wan2.7", "kling"],
            }
        )

    (out_dir / "run_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(plan), "run_plan": str(out_dir / "run_plan.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
