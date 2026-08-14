#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path("/Users/rogerwu/qingshan_short_drama")
PROMPT_DIR = ROOT / "workflow/prompts/e19_parallel_start_20260714"
OUT_DIR = ROOT / "working_assets/e19_parallel_start_video_20260714"

REFS = {
    "chenji": ROOT / "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "baili": ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "nightroad": ROOT / "working_assets/e17_visual_locks_20260714/E17-VL-05/candidate_01.png",
    "courtyard": ROOT / "working_assets/e17_visual_locks_20260714/E17-VL-01/candidate_01.png",
}

NEGATIVE = (
    "subtitles, captions, readable generated Chinese, English letters, Latin letters, modern signage, "
    "wrong face, face drift, body drift, stiff puppet, frozen pose, low motion talking head, overcutting, "
    "hunchback posture, on-screen text, text overlay, watermark, caption bar, letterbox text, 字幕, 文字, 标题条, "
    "BaiLi identity reveal words, 王府郡主 text, name plaques, readable signs"
)


def prompt(visual_lines, audio_items):
    return (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        + "\n".join(visual_lines)
        + "\n\nNEGATIVE_PROMPT:\n"
        + NEGATIVE
        + "\n\nAUDIO_PROMPT_DIALOGUE_ONLY:\n"
        + json.dumps(audio_items, ensure_ascii=False, indent=2)
        + "\n\nRHYTHM_AND_EDITING_INTENT:\n"
        + "Use one multimodal video request. Keep speech and mouth motion synchronized. Hold complete sentences and reaction breaths before cutting, following E16 V3 rhythm.\n"
    )


JOBS = [
    {
        "shot_id": "01",
        "source_id": "E19-SRC-B01",
        "title": "夜墙费劲",
        "duration": 10,
        "refs": ["chenji", "nightroad", "courtyard"],
        "audio": [
            {"dia_id": "DIA-001", "speaker": "陈迹", "text": "你们翻墙？", "tone_code": "guarded_dry", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-002", "speaker": "佛子", "text": "墙有点高。", "tone_code": "plain_calm_young_monk"}
        ],
        "visual": [
            "Ancient night wall near a medical hall, dim moonlight and lantern spill, no readable plaque or sign.",
            "A white-robed young monk finishes an awkward wall climb, slightly breathless but calm, not a grand statue entrance.",
            "Chenji watches from below, upright and tall, wary but dryly amused.",
            "Use a clear physical action contrast: clumsy climb first, precise eyes after landing."
        ],
    },
    {
        "shot_id": "02",
        "source_id": "E19-SRC-B02",
        "title": "白衣红玉",
        "duration": 12,
        "refs": ["chenji", "baili", "nightroad"],
        "audio": [
            {"dia_id": "DIA-003", "speaker": "白衣少年", "text": "别笑他。", "tone_code": "light_protective", "voice_asset_id": "19uxvuf5yl1"},
            {"dia_id": "DIA-004", "speaker": "陈迹", "text": "我没笑。", "tone_code": "deadpan", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-005", "speaker": "佛子", "text": "你心里笑了。", "tone_code": "quietly_seeing_through"}
        ],
        "visual": [
            "White-robed youth with refined male-disguise feeling steps beside the monk; red jade pendant is visible but has no inscription.",
            "Chenji stays upright, not bowing or shrinking; group triangle composition under the wall.",
            "The young monk looks at Chenji with calm precision after the awkward climb.",
            "No explicit identity reveal, no readable symbols, no labels."
        ],
    },
    {
        "shot_id": "03",
        "source_id": "E19-SRC-B03",
        "title": "三贼看心",
        "duration": 16,
        "refs": ["chenji", "baili", "nightroad"],
        "audio": [
            {"dia_id": "DIA-006", "speaker": "佛子", "text": "人心有三贼。", "tone_code": "soft_worldview"},
            {"dia_id": "DIA-007", "speaker": "陈迹", "text": "哪三贼？", "tone_code": "skeptical_short", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-008", "speaker": "佛子", "text": "贪，嗔，痴。", "tone_code": "simple_clear"},
            {"dia_id": "DIA-009", "speaker": "佛子", "text": "你只剩痴。", "tone_code": "gentle_cutting"},
            {"dia_id": "DIA-010", "speaker": "陈迹", "text": "这也能看？", "tone_code": "low_disbelief", "voice_asset_id": "cypqud0bu7t"}
        ],
        "visual": [
            "Calm close hold on the young monk, then Chenji reaction, then the white-robed youth watching with curiosity.",
            "Avoid static lecture: subtle steps, sleeve movement, shifting lantern light, eye contact changes.",
            "Chenji remains straight-backed and controlled; the monk remains young and physically grounded.",
            "No written doctrine, no floating characters, no subtitle-like bottom text."
        ],
    },
    {
        "shot_id": "04",
        "source_id": "E19-SRC-B04",
        "title": "不历劫",
        "duration": 14,
        "refs": ["chenji", "nightroad"],
        "audio": [
            {"dia_id": "DIA-011", "speaker": "佛子", "text": "我来找我的痴。", "tone_code": "calm_confession"},
            {"dia_id": "DIA-012", "speaker": "陈迹", "text": "找到了呢？", "tone_code": "testing", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-013", "speaker": "佛子", "text": "斩了它。", "tone_code": "quiet_danger"}
        ],
        "visual": [
            "Moonlit night wall, the young monk and Chenji face each other with quiet danger.",
            "The monk is not cruel or theatrical; he says dangerous things with simple stillness.",
            "Chenji measures him without hunching, a small breath before replying.",
            "Keep the scene playable and embodied, not an abstract religious poster."
        ],
    },
    {
        "shot_id": "05",
        "source_id": "E19-SRC-B05",
        "title": "大无畏",
        "duration": 14,
        "refs": ["chenji", "baili", "nightroad"],
        "audio": [
            {"dia_id": "DIA-014", "speaker": "白衣少年", "text": "你们和尚真吓人。", "tone_code": "light_release", "voice_asset_id": "19uxvuf5yl1"},
            {"dia_id": "DIA-015", "speaker": "佛子", "text": "我门不讲慈悲。", "tone_code": "matter_of_fact"},
            {"dia_id": "DIA-016", "speaker": "陈迹", "text": "那讲什么？", "tone_code": "watchful", "voice_asset_id": "cypqud0bu7t"},
            {"dia_id": "DIA-017", "speaker": "佛子", "text": "大无畏。", "tone_code": "soft_hook"}
        ],
        "visual": [
            "Group pressure releases briefly; the white-robed youth almost laughs, then notices the monk is serious.",
            "Young monk half-smile, Chenji rejudges him, red jade pendant glints without readable markings.",
            "This is worldview as performance, not narration; keep motion small but alive.",
            "No text, no subtitles, no identity labels."
        ],
    },
    {
        "shot_id": "06",
        "source_id": "E19-SRC-B06",
        "title": "第一场局门口",
        "duration": 8,
        "refs": ["chenji", "baili", "nightroad"],
        "audio": [
            {"dia_id": "DIA-018", "speaker": "远处巡夜声", "text": "谁在墙下？", "tone_code": "distant_offscreen_alert"}
        ],
        "visual": [
            "A distant patrol light turns the corner; the group under the night wall freezes and turns.",
            "Chenji is pulled into the next game by circumstance, not exposition.",
            "End with a clean hook toward the first larger scheme, no action fight yet.",
            "No readable lantern tags, no signage, no bottom subtitles."
        ],
    },
]


def main():
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plan = []
    for job in JOBS:
        prompt_path = PROMPT_DIR / f"{job['source_id']}_prompt.txt"
        prompt_path.write_text(prompt(job["visual"], job["audio"]), encoding="utf-8")
        refs = [str(REFS[key]) for key in job["refs"] if REFS[key].exists()]
        plan.append({
            "shot_id": job["shot_id"],
            "source_id": job["source_id"],
            "title": job["title"],
            "prompt_file": str(prompt_path),
            "references": refs,
            "audio_references": [],
            "out_dir": str(OUT_DIR / job["source_id"]),
            "duration": job["duration"],
            "method": "roger_parallel_start_multimodal_source",
            "dialogue_ids": [item["dia_id"] for item in job["audio"]],
            "qa_required": [
                "OCR critical=0",
                "ASR sentence complete",
                "Fozi wall-climb contrast",
                "BaiLi reveal policy respected",
                "Chenji upright",
                "E16 V3 sentence hold"
            ],
            "submit_status": "READY_TO_SUBMIT_ROGER_OVERRIDE"
        })
    run_plan = ROOT / "configs/e19_parallel_start_giggle_run_plan_20260714.json"
    run_plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "run_plan": str(run_plan),
        "prompt_dir": str(PROMPT_DIR),
        "out_dir": str(OUT_DIR),
        "jobs": len(plan),
        "source_duration_total": sum(job["duration"] for job in JOBS),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
