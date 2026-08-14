#!/usr/bin/env python3
"""Compile E38 clean replacement prompts with frozen voices and expressive delivery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804"
OLD_PLAN = BASE / "E38_PRO_V1_RUN_PLAN.json"
VOICE = BASE / "E38_EXPRESSIVE_VOICE_PROFILES_V1.json"
PROMPT_DIR = BASE / "video_prompts_v4_expressive_clean"
RUN_PLAN = BASE / "E38_PRO_V4_EXPRESSIVE_CLEAN_RUN_PLAN.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def voice_clause(row: dict) -> str:
    return (
        f"{row['speaker']}逐字准确说：{{{row['text']}}}。心理：{row['psychological_state']}；"
        f"情绪：{row['emotion']}，强度{row['emotion_intensity']}/5；语速：{row['pace']}；"
        f"停连：{row['pause_map']}；重音：{'、'.join(row['emphasis_words'])}；"
        f"音量：{row['volume_arc']}；气息：{row['breath_pattern']}；"
        f"句内转变：{row['delivery_transition']}；身体同步：{row['body_sync']}。"
    )


def main() -> int:
    plan = json.loads(OLD_PLAN.read_text(encoding="utf-8"))
    voice = json.loads(VOICE.read_text(encoding="utf-8"))
    by_unit: dict[str, list[dict]] = {}
    for row in voice["profiles"]:
        by_unit.setdefault(row["unit_id"], []).append(row)
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in plan:
        unit = item["shot_id"]
        old_prompt = Path(item["prompt_file"]).read_text(encoding="utf-8").rstrip()
        profiles = by_unit.get(unit, [])
        expressive = ""
        if profiles:
            expressive = (
                "\n【逐句心理与语音表演硬锁】保持角色既定声纹、年龄、音色和口音；禁止播报腔、"
                "整段同语气、机械匀速、无停连、无重音。\n"
                + "\n".join(voice_clause(row) for row in profiles)
            )
        clean_visual = (
            "\n【清晰画面硬锁】画面主体、人物脸、手、药柜、账页和文书全部真实清晰；"
            "禁止景深虚化、背景高斯模糊、运动模糊遮错、文字区域涂抹或失焦。"
            "账页、标签、文书只呈无字纹理和空白排版，真实汉字只在后期字幕/道具合成层添加。"
            "字幕不得由视频模型生成。"
        )
        prompt_path = PROMPT_DIR / f"E38-{unit}-V4-EXPRESSIVE-CLEAN-PRO1080P.txt"
        prompt_path.write_text(old_prompt + expressive + clean_visual + "\n", encoding="utf-8")
        speakers = list(dict.fromkeys(row["speaker"] for row in profiles))
        audio_refs = [voice["voice_identity_assets"].get(name) for name in speakers]
        pending = [name for name, ref in zip(speakers, audio_refs) if not ref or str(ref).startswith("PENDING_")]
        visual_pending = []
        if unit in {"U06", "U07", "U08"}:
            visual_pending.append("取药暗桩")
        if unit in {"U12", "U14"}:
            visual_pending.append("阿栓")
        if unit in {"U13", "U14"}:
            visual_pending.extend(["领头差役", "差役群"])
        blocked = list(dict.fromkeys(pending + visual_pending))
        out = dict(item)
        out.update({
            "prompt_file": str(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "audio_references": [ref for ref in audio_refs if ref and not str(ref).startswith("PENDING_")],
            "native_dialogue_required": bool(profiles),
            "expressive_voice_profile_count": len(profiles),
            "expressive_voice_profile_sha256": sha(VOICE),
            "out_dir": str(ROOT / f"working_assets/e38_replacement_v4_20260805/pro/{unit}"),
            "blocked_character_assets": blocked,
            "status": "BLOCKED_CHARACTER_ASSET" if blocked else "READY_TO_SUBMIT",
        })
        rows.append(out)
    RUN_PLAN.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ready = [row["shot_id"] for row in rows if row["status"] == "READY_TO_SUBMIT"]
    blocked = {row["shot_id"]: row["blocked_character_assets"] for row in rows if row["status"] != "READY_TO_SUBMIT"}
    print(json.dumps({"status": "PASS", "ready": ready, "blocked": blocked, "plan": str(RUN_PLAN)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
