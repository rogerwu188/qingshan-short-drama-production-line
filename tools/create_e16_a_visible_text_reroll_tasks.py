#!/usr/bin/env python3
"""Create reroll tasks for E16 A sources that show forbidden in-picture text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")
ROOT = BASE / "working_assets/e16_api_20260711/a_coverage_tasks_20260713"


TEXT_CLEAN_PREFIX = """\
This is a visible-text failure reroll. The previous candidate showed generated in-picture words. Fix only that failure.

ABSOLUTE ZERO VISUAL TEXT: the frame must contain no rendered words, no subtitles, no captions, no karaoke lyrics, no lower-third, no central dialogue text, no speech bubble, no Chinese character, no pseudo-Chinese, no English, no Latin letters, no labels, no plaques, no signboards, no seals, no UI text and no decorative writing. If the model would show words, keep that area as blank wood, cloth, rain, skin, robe, wall, or shadow. Dialogue must exist only in audio and mouth movement.

Keep the speaker moving naturally: one eye-line shift, one breath, one small hand/finger/shoulder movement tied to the spoken stress. Do not freeze.

"""


SPECIALS = {
    "D03": {
        "variant": "R3",
        "base_prompt": ROOT / "D03/prompt_r2.txt",
        "visual_lock": BASE / "assets/reference/e16_visual_locks_20260711/shot_01_visual_lock.jpg",
        "speaker_reference": BASE / "assets/reference/e16_supporting_cast_20260712/CORONER_B12R3_solo_clean_720x1280.jpg",
    }
}


def load_task(dialogue_id: str) -> dict:
    batch_files = sorted(ROOT.glob("a_source_batch_*.json"))
    for batch_file in batch_files:
        data = json.loads(batch_file.read_text(encoding="utf-8"))
        for task in data.get("tasks", []):
            if task.get("dialogue_id") == dialogue_id:
                return task
    raise SystemExit(f"Cannot find source task for {dialogue_id}")


def build_reroll_prompt(base_prompt_path: Path, source_task: dict, dialogue_id: str) -> str:
    dialogue_text = (source_task.get("text") or "").strip()
    legacy_prompt = base_prompt_path.read_text(encoding="utf-8")
    visual_marker = "VISUAL_PROMPT_NO_DIALOGUE_TEXT:"
    audio_marker = "AUDIO_PROMPT_DIALOGUE_ONLY:"
    if visual_marker in legacy_prompt and audio_marker in legacy_prompt:
        visual = legacy_prompt.split(visual_marker, 1)[1].split(audio_marker, 1)[0].strip()
        audio = legacy_prompt.split(audio_marker, 1)[1].strip()
    else:
        visual = (
            f"E16 visible-text reroll for {dialogue_id}. Use the same visual lock and speaker reference. "
            "The speaker performs the same dialogue with natural lip movement, but the dialogue text must never appear in the picture. "
            "Keep the same scene, lighting, identity, wardrobe, eyeline, camera distance and short-drama acting continuity. "
            "Do not copy any legacy instruction that asks for written dialogue, captions, labels or subtitles."
        )
        audio = (
            "Audio-only dialogue instruction: "
            f"say the exact Mandarin line once with clear mouth movement and no changed words: “{dialogue_text}”. "
            "The dialogue belongs only to audio and lip movement, never to on-screen text."
        )
    return (
        f"{visual_marker}\n"
        f"{TEXT_CLEAN_PREFIX}"
        f"{visual}\n\n"
        f"{audio_marker}\n"
        f"{audio}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="R2")
    parser.add_argument("dialogue_ids", nargs="+")
    args = parser.parse_args()
    tasks = []
    for dialogue_id in args.dialogue_ids:
        special = SPECIALS.get(dialogue_id)
        if special:
            variant = special["variant"]
            base_prompt = special["base_prompt"]
            visual_lock = special["visual_lock"]
            speaker_reference = special["speaker_reference"]
            source_task = load_task(dialogue_id)
        else:
            variant = args.variant
            source_task = load_task(dialogue_id)
            base_prompt = BASE / source_task["prompt_path"]
            visual_lock = BASE / source_task["visual_lock"]
            speaker_reference = BASE / source_task["speaker_reference"]
        out_dir = ROOT / f"{dialogue_id}_{variant}"
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = out_dir / "prompt.txt"
        prompt = build_reroll_prompt(base_prompt, source_task, dialogue_id)
        prompt_path.write_text(prompt, encoding="utf-8")
        tasks.append(
            {
                "dialogue_id": f"{dialogue_id}_{variant}",
                "source_dialogue_id": dialogue_id,
                "text": source_task.get("text", ""),
                "visual_prompt_contract": "VISUAL_PROMPT_NO_DIALOGUE_TEXT",
                "audio_prompt_contract": "AUDIO_PROMPT_DIALOGUE_ONLY",
                "reroll_reason": "visible_in_picture_text",
                "prompt_path": str(prompt_path.relative_to(BASE)),
                "visual_lock": str(visual_lock.relative_to(BASE)),
                "speaker_reference": str(speaker_reference.relative_to(BASE)),
                "duration": 4,
                "model": "seedance-2.0-pro",
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "status": "READY_TO_SUBMIT",
            }
        )
    manifest = {
        "schema": "qingshan.e16.a_source_visible_text_reroll_manifest.v1",
        "episode": "E16",
        "status": "READY_TO_SUBMIT",
        "tasks": tasks,
    }
    out = ROOT / "a_source_visible_text_rerolls_20260713.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "READY_TO_SUBMIT", "task_count": len(tasks), "manifest": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
