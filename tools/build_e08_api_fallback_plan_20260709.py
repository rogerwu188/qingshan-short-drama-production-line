#!/usr/bin/env python3
"""
Build an E08-specific Giggle API fallback run plan.

This avoids reusing older E06 prompt assumptions. It reads the 2026-07-09
hard-bound storyboard prompts and the E08 continuity config, then writes one
API prompt per shot plus a run_plan.json for tools/run_giggle_api_plan.py.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]

REFERENCE_ASSET_DIR = ROOT / "assets/reference/e08_api_fallback_20260709"
CHENJI_REF = REFERENCE_ASSET_DIR / "characters/CHAR-chenji-ancient-face-ref-clean-20260709.jpg"
CHENJI_GREY_CARD = REFERENCE_ASSET_DIR / "characters/CHAR-chenji-grey-apprentice-card-clean-20260709.jpg"
YAO_CARD = REFERENCE_ASSET_DIR / "characters/CHAR-yao-taiyi-card-clean-20260709.jpg"
SKINNY_REF = REFERENCE_ASSET_DIR / "characters/CHAR-skinny-apprentice-card-clean-20260709.jpg"
STURDY_REF = REFERENCE_ASSET_DIR / "characters/CHAR-sturdy-apprentice-derived-row05-clean-20260709.jpg"
REAR_COURTYARD_REF = REFERENCE_ASSET_DIR / "scenes/SCENE-taiping-rear-courtyard-clean-20260709.jpg"
DORM_REF = REFERENCE_ASSET_DIR / "scenes/SCENE-taiping-apprentice-dorm-clean-20260709.jpg"
FRONT_HALL_REF = REFERENCE_ASSET_DIR / "scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
STREET_REF = REFERENCE_ASSET_DIR / "scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
BAMBOO_HERB_TRAY_REF = REFERENCE_ASSET_DIR / "props/PROP-bamboo-herb-tray-clean-20260709.jpg"
WATCHER_REF = REFERENCE_ASSET_DIR / "characters/CHAR-secret-service-watcher-clean-20260709.jpg"


COMMON_API_RULES = """所有角色为中国/东亚古装角色。普通话中文对白必须完整说完，不能英文，不能外语，不能无对白，不能只做慢动作特写。画幅 9:16，720p，电影写实短剧。视频必须有真实人物动作、对白、环境声、拟音和低量 BGM；对白处 BGM 自动闪避。严格保持角色、道具、场景、服装和空间方向一致：同一后院必须是同一灰砖地、水井、晾药竹匾、药房木门；同一正堂必须是同一长柜台、药柜、算盘、药账本、煤油灯；同一晨街必须是同一青石街、灰檐、太平医馆门口。禁止静态照片推拉、故事板表格入镜、空白画面、欧美人物、现代服装、随机换脸、角色互换、道具漂移、场景漂移、服装漂移。"""


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_prompt_sections(path: Path) -> Dict[str, str]:
    text = path.read_text(encoding="utf-8")
    matches = list(re.finditer(r"^## Row(\d{2})\s*$", text, re.MULTILINE))
    sections: Dict[str, str] = {}
    for idx, match in enumerate(matches):
        shot_id = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections[shot_id] = body
    return sections


def shot_duration(shot: Dict[str, Any]) -> int:
    start = int(shot.get("start", 0))
    end = int(shot.get("end", start + 7))
    return max(4, min(10, end - start))


def references_for(shot: Dict[str, Any]) -> List[str]:
    chars = set(shot.get("characters") or [])
    props = set(shot.get("props") or [])
    room_id = shot.get("room_id") or ""
    refs: List[Path] = []
    if "CHAR-陈迹-古装" in chars:
        refs.extend(path for path in [CHENJI_REF, CHENJI_GREY_CARD] if path.exists())
    if "CHAR-姚太医-古装" in chars and YAO_CARD.exists():
        refs.append(YAO_CARD)
    if "CHAR-太平医馆瘦高师兄" in chars and SKINNY_REF.exists():
        refs.append(SKINNY_REF)
    if "CHAR-太平医馆魁梧师兄" in chars and STURDY_REF.exists():
        refs.append(STURDY_REF)
    if "CHAR-密谍司暗桩" in chars and WATCHER_REF.exists():
        refs.append(WATCHER_REF)
    if room_id == "ROOM-古装-太平医馆后院早课-A" and REAR_COURTYARD_REF.exists():
        refs.append(REAR_COURTYARD_REF)
    if room_id == "ROOM-古装-太平医馆学徒寝房-A" and DORM_REF.exists():
        refs.append(DORM_REF)
    if room_id == "ROOM-古装-太平医馆正堂-A" and FRONT_HALL_REF.exists():
        refs.append(FRONT_HALL_REF)
    if room_id == "SCENE-古装-洛城晨街" and STREET_REF.exists():
        refs.append(STREET_REF)
    if (
        room_id == "ROOM-古装-太平医馆后院早课-A"
        or "PROP-古装-药草竹匾" in props
        or "PROP-古装-竹条" in props
    ) and BAMBOO_HERB_TRAY_REF.exists():
        refs.append(BAMBOO_HERB_TRAY_REF)
    return [str(path.resolve()) for path in refs[:9]]


def prompt_for(shot: Dict[str, Any], hard_prompt: str, refs: List[str]) -> str:
    shot_id = str(shot.get("id") or shot.get("shot_id")).zfill(2)
    ref_lines = "\n".join(f"- 图片{idx}: {Path(path).name}" for idx, path in enumerate(refs, 1))
    if not ref_lines:
        ref_lines = "- 本镜头无可用本地人物图参考，严格按角色文字锚点生成。"
    scene = shot.get("room_id", "")
    chars = "、".join(shot.get("characters") or []) or "无"
    props = "、".join(shot.get("props") or []) or "无"
    return f"""{COMMON_API_RULES}

E08《站桩救命》API 兜底镜头 {shot_id}

参考图片顺序：
{ref_lines}

连续性锚点：
- 场景/房间：{scene}
- 出场角色：{chars}
- 关键道具：{props}

本镜头硬绑定提示词：
{hard_prompt}

API 执行硬规则：
1. 如果本镜头出现陈迹，必须同时使用陈迹脸部参考和陈迹灰布学徒角色卡：同脸同骨相、去眼镜、20岁左右、灰布学徒长衫，不得改成陌生男主或青绿/华丽外袍。
2. 如果本镜头出现姚太医，必须使用姚太医角色卡：白发白须九十余岁中国老医者，灰色长衫，手持竹条，不得变成现代医生或道士。
3. 如果出现瘦高师兄或魁梧师兄，必须和陈迹明显区分，不得共用陈迹的脸。
4. 本镜头必须是动态短剧视频，有人物动作和中文对白声画同步。不能生成静态图、分镜表、首帧幻灯片或无声片段。
5. 角色、道具、场景、服装、空间方向必须和连续性锚点一致；任何换脸、换衣、换院子、换正堂、换街道、道具消失或新增陌生核心道具都算失败。
6. 结尾保留半秒动作/声桥，便于与下一镜衔接。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build E08 API fallback run_plan.")
    parser.add_argument("--continuity", default=str(ROOT / "configs/e08_continuity_config_v1_24shots_20260705.json"))
    parser.add_argument(
        "--hard-prompts",
        default=str(ROOT / "qa/e08_repair_20260709/e08_row05_23_hard_bound_storyboard_prompts_20260709.md"),
    )
    parser.add_argument("--out-dir", default=str(ROOT / "working_assets/e08_api_fallback_20260709"))
    parser.add_argument("--shots", nargs="*", default=[f"{i:02d}" for i in range(5, 24)])
    args = parser.parse_args()

    continuity = load_json(Path(args.continuity))
    hard_prompts = parse_prompt_sections(Path(args.hard_prompts))
    requested = {shot.zfill(2) for shot in args.shots}
    out_dir = Path(args.out_dir).resolve()
    prompt_dir = out_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    plan: List[Dict[str, Any]] = []
    shots_by_id = {str(shot.get("id") or shot.get("shot_id")).zfill(2): shot for shot in continuity.get("shots", [])}
    for shot_id in sorted(requested):
        if shot_id == "24":
            continue
        shot = shots_by_id.get(shot_id)
        if not shot:
            raise SystemExit(f"Missing continuity shot {shot_id}")
        hard_prompt = hard_prompts.get(shot_id)
        if not hard_prompt:
            raise SystemExit(f"Missing hard-bound prompt for Row{shot_id}")
        refs = references_for(shot)
        prompt_path = prompt_dir / f"e08_shot_{shot_id}.txt"
        prompt_path.write_text(prompt_for(shot, hard_prompt, refs), encoding="utf-8")
        plan.append(
            {
                "shot_id": shot_id,
                "title": f"E08 Row{shot_id}",
                "duration": shot_duration(shot),
                "prompt_file": str(prompt_path),
                "references": refs,
                "out_dir": str((out_dir / "videos" / f"shot_{shot_id}").resolve()),
                "models": ["seedance-2.0-pro", "sora2", "veo3.1", "wan2.7", "kling"],
            }
        )

    plan_path = out_dir / "run_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"shots": len(plan), "run_plan": str(plan_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
