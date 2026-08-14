#!/usr/bin/env python3
"""Compile E16 speaker A-source generation tasks with performance directions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
DIALOGUE = BASE / "configs/e16_dialogue_beat_sheet_20260711.json"
COVERAGE = BASE / "configs/e16_director_coverage_hotfix_20260711.json"
PERFORMANCE = BASE / "configs/character_performance_bible_20260712.json"
ASSETS = BASE / "configs/series_character_asset_registry_20260712.json"
OUT_ROOT = BASE / "working_assets/e16_api_20260711/a_coverage_tasks_20260713"


SPEAKER_ASSET_IDS = {
    "陈迹": "CHAR-陈迹-古装",
    "白鲤": "CHAR-白鲤-古装",
    "乌云": "CHAR-乌云-猫",
    "验尸官": "CHAR-验尸官",
}

SUPPORTING_REFERENCES = {
    "官差": BASE / "assets/reference/e16_supporting_cast_20260712/CONSTABLE_FRONTMAN_clean_solo_720x1280.jpg",
}

TONE_BY_FUNCTION = {
    "pressure": ("official_control", "pressed", "medium", "seize_procedure"),
    "golden_counterattack": ("plain_fact", "normal", "medium", "redirect_to_evidence"),
    "accusation": ("institutional_bluff", "pressed", "medium", "seize_procedure"),
    "evidence_redirect": ("evidence_pressure", "normal", "medium", "redirect_to_evidence"),
    "question": ("group_doubt", "normal", "fast", "shift_allegiance"),
    "evidence_reveal": ("plain_fact", "normal", "slow", "redirect_to_evidence"),
    "denial": ("institutional_bluff", "pressed", "fast", "hide_knowledge"),
    "trap": ("evidence_pressure", "pressed", "slow", "lock_contradiction"),
    "secret_agenda": ("dry_politeness", "pressed", "slow", "test_alibi"),
    "action_command": ("plain_fact", "normal", "medium", "stop_force"),
    "evidence_confirmation": ("group_doubt", "normal", "medium", "shift_allegiance"),
    "cover_story": ("institutional_bluff", "pressed", "fast", "hide_knowledge"),
    "rebuttal": ("evidence_pressure", "pressed", "slow", "lock_contradiction"),
    "proof": ("plain_fact", "normal", "slow", "redirect_to_evidence"),
    "witness_confirmation": ("group_doubt", "normal", "medium", "shift_allegiance"),
    "power_shift": ("quiet_power", "pressed", "slow", "stop_force"),
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reference_for_speaker(speaker: str, assets: dict[str, Any]) -> Path | None:
    asset_id = SPEAKER_ASSET_IDS.get(speaker)
    if asset_id:
        ref = assets["characters"][asset_id].get("reference_image")
        return Path(ref) if ref else None
    return SUPPORTING_REFERENCES.get(speaker)


def voice_for_speaker(speaker: str, assets: dict[str, Any]) -> str:
    asset_id = SPEAKER_ASSET_IDS.get(speaker)
    if not asset_id:
        return "native natural Chinese supporting-role voice, not chorus, not modern police tone"
    voice = assets["characters"][asset_id].get("voice_asset_id")
    if voice:
        return f"voice asset {voice}"
    return "native natural Chinese voice for this exact character identity"


def stress_words(text: str, function: str) -> list[str]:
    if function in {"pressure", "accusation"}:
        return [w for w in ["本官", "陈迹", "手", "尸身"] if w in text][:2]
    if function in {"evidence_redirect", "evidence_reveal", "proof", "rebuttal", "trap"}:
        return [w for w in ["尸", "腕", "两道", "证据", "线", "褶"] if w in text][:2]
    if function in {"denial", "cover_story"}:
        return [w for w in ["三日", "褶", "格目", "县衙"] if w in text][:2]
    return [text[: min(4, len(text))]]


def build_prompt(
    *,
    line: dict[str, Any],
    coverage: dict[str, Any],
    performance: dict[str, Any],
    assets: dict[str, Any],
) -> str:
    speaker = line["speaker"]
    function = line.get("function", "")
    tone_code, volume, pace, subtext_code = TONE_BY_FUNCTION.get(function, ("plain_fact", "normal", "medium", "redirect_to_evidence"))
    profile = performance["characters"].get(speaker, {})
    source_shot = coverage["A"]["source_shot_id"]
    listener_reaction = line.get("listener_reaction", "")
    stress = "、".join(stress_words(line["text"], function))
    voice = voice_for_speaker(speaker, assets)

    visual_prompt = (
        f"E16 A-source {line['id']} speaker performance clip, 4 seconds, vertical 9:16. "
        f"Use @Image1 as the exact visual-lock anchor for source shot {source_shot}; keep the same Song/Ming period setting, "
        f"warm oil-lamp interior plus cold rain spill, no daylight, no modern objects. "
        f"Use @Image2 only as the identity/body/wardrobe reference for speaker {speaker}; preserve same face and body identity. "
        f"Speaker {speaker} performs the line with natural mouth movement, but do not render any written words from the line. "
        f"Body-voice link: {profile.get('body_voice_link', 'face reacts first, body follows naturally')}. "
        f"Listener reaction target for edit continuity: {listener_reaction}. "
        f"Camera: stable A-side speaker coverage, 50-85mm medium or close-medium according to the visual lock, speaker 45-65% frame height, "
        f"natural eye-line, no static puppet stare, no repeated movement, no freeze, real-time speed. "
        "Visual negative: no subtitles, no captions, no central bold captions, no duplicate subtitle layer, no speech bubbles, "
        "no karaoke text, no Chinese characters, no English, no Latin letters, no readable pseudo-Chinese on plot props, "
        "no modern police uniform, no peaked cap, no clinic/hospital signage, no glass kerosene lamp, no briefcase or suitcase, no gore. "
        "Exquisite cinematic short-drama realism."
    )
    audio_prompt = (
        f"Audio-only dialogue instruction: speaker {speaker} says the exact Mandarin line once, with clear mouth movement and no changed words: "
        f"“{line['text']}”. Bind {voice}; tone_code={tone_code}; subtext_code={subtext_code}; pace={pace}; volume={volume}; "
        f"stress no more than two words: {stress}; pause 0.25-0.45s before speaking and 0.25-0.55s after speaking. "
        f"Acting fingerprint: {profile.get('sentence_fingerprint', 'natural short-drama conversational delivery')}. "
        f"Forbidden performance: {profile.get('forbidden', 'announcer voice, theatrical recitation, same tone every line')}. "
        "The dialogue belongs only to audio and lip movement, never to on-screen text."
    )
    return (
        "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n"
        f"{visual_prompt}\n\n"
        "AUDIO_PROMPT_DIALOGUE_ONLY:\n"
        f"{audio_prompt}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--start", default="D01")
    args = parser.parse_args()

    dialogue = load_json(DIALOGUE)
    coverage = load_json(COVERAGE)
    performance = load_json(PERFORMANCE)
    assets = load_json(ASSETS)
    coverage_by_id = {beat["dialogue_beat_id"]: beat for beat in coverage["beats"]}
    lines = dialogue["lines"]
    start_idx = next((idx for idx, item in enumerate(lines) if item["id"] == args.start), 0)
    selected = lines[start_idx : start_idx + args.limit]

    tasks = []
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for line in selected:
        cov = coverage_by_id[line["id"]]
        source_shot = cov["A"]["source_shot_id"]
        visual_lock = BASE / f"assets/reference/e16_visual_locks_20260711/shot_{source_shot}_visual_lock.jpg"
        if not visual_lock.exists():
            png_lock = visual_lock.with_suffix(".png")
            visual_lock = png_lock if png_lock.exists() else visual_lock
        speaker_ref = reference_for_speaker(line["speaker"], assets)
        task_dir = OUT_ROOT / line["id"]
        task_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = task_dir / "prompt.txt"
        prompt = build_prompt(line=line, coverage=cov, performance=performance, assets=assets)
        prompt_path.write_text(prompt, encoding="utf-8")
        problems = []
        if not visual_lock.exists():
            problems.append(f"missing visual lock: {visual_lock}")
        if not speaker_ref or not speaker_ref.exists():
            problems.append(f"missing speaker reference: {speaker_ref}")
        tasks.append(
            {
                "dialogue_id": line["id"],
                "speaker": line["speaker"],
                "text": line["text"],
                "visual_prompt_contract": "VISUAL_PROMPT_NO_DIALOGUE_TEXT",
                "audio_prompt_contract": "AUDIO_PROMPT_DIALOGUE_ONLY",
                "source_shot_id": source_shot,
                "prompt_path": str(prompt_path.relative_to(BASE)),
                "visual_lock": str(visual_lock.relative_to(BASE)) if visual_lock.exists() else str(visual_lock),
                "speaker_reference": str(speaker_ref.relative_to(BASE)) if speaker_ref and speaker_ref.exists() else str(speaker_ref),
                "duration": 4,
                "model": "seedance-2.0-pro",
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "status": "READY_TO_SUBMIT" if not problems else "BLOCKED_PRECHECK",
                "problems": problems,
            }
        )

    manifest = {
        "schema": "qingshan.e16.a_source_task_manifest.v1",
        "episode": "E16",
        "status": "READY_TO_SUBMIT" if all(not task["problems"] for task in tasks) else "BLOCKED_PRECHECK",
        "start": args.start,
        "limit": args.limit,
        "tasks": tasks,
    }
    out = OUT_ROOT / f"a_source_batch_{args.start}_{selected[-1]['id']}.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "task_count": len(tasks), "manifest": str(out)}, ensure_ascii=False))
    return 0 if manifest["status"] == "READY_TO_SUBMIT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
