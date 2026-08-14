#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path("/Users/rogerwu/qingshan_short_drama")
PROMPT_DIR = ROOT / "workflow/prompts/e18_parallel_start_20260714"
OUT_DIR = ROOT / "working_assets/e18_parallel_start_video_20260714"

REFS = {
    "chenji": ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "yunfei": ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-yunfei-ancient-card-20260709.jpg",
    "wuyun": ROOT / "ref_images/cat_wuyun_reference.jpg",
    "xibing": ROOT / "ref_images/female_xibing_ref_20260704.png",
    "baili": ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "nightroad": ROOT / "working_assets/e17_visual_locks_20260714/E17-VL-05/candidate_01.png",
    "courtyard": ROOT / "working_assets/e17_visual_locks_20260714/E17-VL-01/candidate_01.png",
    "evidence": ROOT / "working_assets/e17_visual_locks_20260714/E17-VL-04/candidate_01.png",
}

NEGATIVE = (
    "subtitles, captions, readable generated Chinese, English letters, Latin letters, modern signage, "
    "wrong face, face drift, body drift, stiff puppet, frozen pose, low motion talking head, overcutting, "
    "hunchback posture, on-screen text, text overlay, watermark, caption bar, letterbox text, 字幕, 文字, 标题条"
)


def prompt(visual_lines, audio_items):
    return (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        + "\n".join(visual_lines)
        + "\n\nNEGATIVE_PROMPT:\n"
        + NEGATIVE
        + "\nAUDIO_PROMPT_DIALOGUE_ONLY:\n"
        + json.dumps(audio_items, ensure_ascii=False, indent=2)
        + "\n\nRHYTHM_AND_EDITING_INTENT:\n"
        + "Hold each complete sentence or semantic beat before cutting. Preserve E16 V3 sentence-hold rhythm, reaction breath, and real-time physical motion.\n"
    )


JOBS = [
    {
        "shot_id": "01",
        "source_id": "E18-SRC-B01-A-C",
        "title": "喜饼入手与陈迹反问",
        "duration": 6,
        "refs": ["chenji", "xibing", "nightroad"],
        "audio": [
            {"dia_id": "DIA-001", "speaker": "王府仆从", "text": "夫人赏你的。", "tone_code": "soft_formal"},
            {"dia_id": "DIA-002", "speaker": "陈迹", "text": "赏我，还是记我？", "tone_code": "low_alert", "voice_asset_id": "cypqud0bu7t"}
        ],
        "visual": [
            "Ancient Wangfu night road, restrained lantern light, period clothing, blank pastry gift box, no readable text.",
            "A young Wangfu servant calmly offers the gift box; Chenji receives it with guarded eyes.",
            "Chenji stands upright and tall, shoulders square, controlled calculation, no hunching.",
            "Medium close holds and a clear prop insert, real-time hand movement."
        ],
    },
    {
        "shot_id": "02",
        "source_id": "E18-BED-B02-STRETCHER",
        "title": "担架擦肩与低声警告",
        "duration": 7,
        "refs": ["chenji", "nightroad"],
        "audio": [
            {"dia_id": "DIA-003", "speaker": "路人低声", "text": "别看。", "tone_code": "low_offscreen_urgent"}
        ],
        "visual": [
            "Dim ancient side road outside Wangfu, controlled lantern light, no signs, no plaques, no readable text.",
            "A covered stretcher passes close by Chenji; only one slender bruised hand is visible.",
            "No blood, no gore, no corpse face, restrained single-detail dread.",
            "Chenji holds a short reaction breath after the offscreen warning."
        ],
    },
    {
        "shot_id": "03",
        "source_id": "E18-SRC-B03-A-B",
        "title": "温柔传话与账我会算",
        "duration": 7,
        "refs": ["chenji", "xibing", "yunfei"],
        "audio": [
            {"dia_id": "DIA-004", "speaker": "王府传话人", "text": "王府记恩，也记账。", "tone_code": "warm_threat"},
            {"dia_id": "DIA-005", "speaker": "陈迹", "text": "账我会算。", "tone_code": "dry_controlled", "voice_asset_id": "cypqud0bu7t"}
        ],
        "visual": [
            "Quiet Wangfu threshold, warm light and cold pressure, blank pastry box pushed closer as a threat.",
            "Messenger speaks gently with controlled posture; Chenji does not bow or retreat.",
            "Chenji remains upright and tall, steady close hold, no readable text on props or walls."
        ],
    },
    {
        "shot_id": "04",
        "source_id": "E18-SRC-B04-A-B-C",
        "title": "车中试探",
        "duration": 12,
        "refs": ["chenji", "yunfei", "courtyard"],
        "audio": [
            {"dia_id": "DIA-006", "speaker": "车中人", "text": "你怀疑我？", "tone_code": "soft_testing"},
            {"dia_id": "DIA-007", "speaker": "陈迹", "text": "我怀疑证据。", "tone_code": "steady_factual", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-008", "speaker": "车中人", "text": "证据也认主人。", "tone_code": "calm_dangerous"}
        ],
        "visual": [
            "Period carriage interior or threshold at night, speaker partly hidden behind curtain, warm dim light.",
            "Chenji answers by focusing on evidence, not allegiance; upright posture, no hunching.",
            "Minimal movement, pressure built through stillness, no readable emblem, no modern vehicle elements."
        ],
    },
    {
        "shot_id": "05",
        "source_id": "E18-SRC-B05-B-C",
        "title": "红玉伏笔与乌云泄压",
        "duration": 8,
        "refs": ["chenji", "wuyun", "baili"],
        "audio": [
            {"dia_id": "DIA-009", "speaker": "乌云", "text": "饼里没毒。", "tone_code": "dry_cat_voice", "voice_asset_id": "7zksqweu9xu"},
            {"dia_id": "DIA-010", "speaker": "陈迹", "text": "比毒贵。", "tone_code": "cold_humor", "voice_asset_id": "cypqud0bu7t"}
        ],
        "visual": [
            "Brief red jade pendant atmosphere, no inscription, no identity reveal, no readable text.",
            "Small natural black cat Wuyun near Chenji, correct cat scale, no oversized body, no human mouth movement for cat line.",
            "Chenji reacts with restrained dry humor, upright posture preserved."
        ],
    },
    {
        "shot_id": "06",
        "source_id": "E18-SRC-B06-B",
        "title": "夹缝钩子",
        "duration": 6,
        "refs": ["chenji", "nightroad", "evidence"],
        "audio": [
            {"dia_id": "DIA-011", "speaker": "远处声音", "text": "该进府了。", "tone_code": "distant_understated"}
        ],
        "visual": [
            "The blank pastry box closes like a small lock; Chenji stands between Wangfu pressure and the next-stage pull.",
            "Ancient night atmosphere, restrained hook, no action spectacle, no readable text, no modern objects.",
            "Hold the complete offscreen hook line, then Chenji reaction."
        ],
    },
]


def write_e18():
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = []
    for job in JOBS:
        prompt_path = PROMPT_DIR / f"{job['source_id']}_prompt.txt"
        prompt_path.write_text(prompt(job["visual"], job["audio"]), encoding="utf-8")
        plan.append({
            "shot_id": job["shot_id"],
            "source_id": job["source_id"],
            "title": job["title"],
            "prompt_file": str(prompt_path),
            "references": [str(REFS[key]) for key in job["refs"] if REFS[key].exists()],
            "audio_references": [],
            "out_dir": str(OUT_DIR / job["source_id"]),
            "duration": job["duration"],
            "method": "roger_parallel_start_multimodal_source",
            "dialogue_ids": [item["dia_id"] for item in job["audio"]],
            "qa_required": ["OCR critical=0", "ASR sentence complete", "multimodal audio/video source", "E16 V3 sentence hold"],
            "submit_status": "READY_TO_SUBMIT_ROGER_OVERRIDE"
        })
    run_plan = ROOT / "configs/e18_parallel_start_giggle_run_plan_20260714.json"
    run_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run_plan


def write_e19():
    task = ROOT / "workflow/tasks/E19_TASK.md"
    if not task.exists():
        task.write_text("""# E19 Task - 佛子一笑

## 基本信息

- `episode_id`: E19
- `title`: 佛子一笑
- `status`: P0_PARALLEL_START_SAFE_PREP
- `source_scope`: 第一卷方向 A；原著 41 章佛子首次正面出场 + 白鲤男装白衣/红玉领坠同场。
- `creative_goal`: 在 E18 王府夹缝后，把王府线推向更大的修行世界观：佛子用一句“三贼”看穿陈迹，白鲤身份可埋但不硬爆。
- `hook`: 一个翻墙都费劲的小和尚，却一眼看出陈迹心里只剩“痴”。
- `episode_type`: mixed / dialogue_mystery / worldbuilding
- `CI 分档`: standard with dialogue-mystery pacing
- `上集 director_strategy_update`: inherit E16 V3 sentence-hold rhythm and E18 one-multimodal-prompt speaking workflow.
- `共享审稿状态`: PENDING_STORYCLAW

## 当前门禁

- Roger has approved E18 and E19 simultaneous start.
- E19 may proceed with P0 script, asset inheritance, coverage, prompt contract and QA prep.
- Do not final-lock, edit-package, or platform-publish E19 before E18/E17 order is respected.
- If Giggle generation starts, use one multimodal video request for every dialogue/offscreen-audio source.

## 原著/长线依据

- 原著 41 章「佛子」：罗追萨迦、靖王府世子、白鲤郡主深夜翻墙出府夜游。
- 长线方向 A：E19 佛子一笑，E20 第一场局。
- 关键语料：三贼“贪、嗔、痴”；“不历劫，不成佛”；“我葛宁派从不讲慈悲 / 讲大无畏”。

## 红线

- 不把佛子拍成庄严静态神像；出场反差是翻墙费劲、但眼神极准。
- 不提前用台词硬解释所有修行体系。
- 白鲤身份如未到揭示点，不用“郡主/王府/靖王/白鲤郡主”等明示词。
- 视觉 prompt 不写对白原文。
- 陈迹保持挺拔，不佝偻。
- 不把世界观金句堆成旁白朗读。

## 下一步

1. 建 E19 剧本 beat sheet。
2. 建 E19 资产继承 manifest：陈迹、白鲤、佛子、世子、乌云可选。
3. 建 E19 coverage plan 与 prompt contract。
4. 共享给 StoryClaw 复核。
""", encoding="utf-8")
    preflight = ROOT / "configs/e19_p0_preflight_plan_20260714.json"
    preflight.write_text(json.dumps({
        "episode": "E19",
        "title": "佛子一笑",
        "created_at": "2026-07-14T22:15:00-07:00",
        "status": "P0_PARALLEL_START_SAFE_PREP",
        "generation_allowed": False,
        "roger_override": "E18 and E19 simultaneous start approved",
        "source_basis": [
            "原著 41 章：佛子罗追萨迦首次正面出场",
            "白鲤男装白衣 + 红玉领坠同场",
            "长线方向 A：E19 佛子一笑，E20 第一场局"
        ],
        "must_include_scene_candidates": [
            {"id": "E19-SCENE-01", "name": "夜墙费劲", "function": "用反差介绍佛子，不做静态神像"},
            {"id": "E19-SCENE-02", "name": "三贼看心", "function": "佛子一句看穿陈迹的痴"},
            {"id": "E19-SCENE-03", "name": "白衣红玉", "function": "白鲤身份伏笔或揭示前奏"},
            {"id": "E19-SCENE-04", "name": "大无畏钩子", "function": "把修行世界观推向第一场局"}
        ],
        "carry_forward_rules": [
            "E16 V3 sentence-hold rhythm",
            "one multimodal video request for speaking/offscreen audio",
            "visual prompt contains no dialogue text",
            "BaiLi reveal terms forbidden unless explicitly moved to reveal beat",
            "Chenji upright posture",
            "runtime target 165-185 seconds"
        ]
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return task, preflight


def main():
    run_plan = write_e18()
    e19_task, e19_preflight = write_e19()
    print(json.dumps({
        "e18_run_plan": str(run_plan),
        "e18_prompt_dir": str(PROMPT_DIR),
        "e18_out_dir": str(OUT_DIR),
        "e19_task": str(e19_task),
        "e19_preflight": str(e19_preflight),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
