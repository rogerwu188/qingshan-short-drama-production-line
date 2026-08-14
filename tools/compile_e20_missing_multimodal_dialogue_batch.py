#!/usr/bin/env python3
"""Compile every missing E20 dialogue line into one concurrent video batch."""

from __future__ import annotations

import json
import re
from pathlib import Path

from shot_duration_policy import POLICY_VERSION, plan_dialogue_duration


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE = ROOT / "configs/e20_dialogue_performance_manifest_v2_20260716.json"
MANIFEST = ROOT / "configs/e20_missing_34_multimodal_dialogue_batch_v2_story_duration_20260718.json"
CORRECTION_MANIFEST = ROOT / "configs/e20_story_duration_correction_wave_v2_20260718.json"
PROMPT_DIR = ROOT / "workflow/prompts/e20_missing_34_multimodal_dialogue_batch_v2_story_duration_20260718"
PREFLIGHT = ROOT / "qa/e20_missing_34_multimodal_dialogue_batch_v2_story_duration_20260718/E20_MISSING_34_COMPILE_PREFLIGHT.json"

COMPLETED = {"DIA-012", "DIA-014", "DIA-017", "DIA-027"}

BEAT_VISUALS = {
    "B01": [
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-01/E20-VL-01-A.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-01/E20-VL-01-B.png",
    ],
    "B02": [
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-02/E20-VL-02-A.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-02/E20-VL-02-C.png",
    ],
    "B03": [
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-04/E20-VL-04-A.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-05/E20-VL-05-A.png",
    ],
    "B04": [
        "working_assets/e20_static_visual_lock_repairs_20260716/E20-VL-06-B-R2/E20-VL-06-B-R2.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-05/E20-VL-05-B.png",
    ],
    "B05": [
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-03/E20-VL-03-C.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-04/E20-VL-04-C.png",
    ],
    "B06": [
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-04/E20-VL-04-C.png",
        "working_assets/e20_static_visual_lock_candidates_20260716/E20-VL-05/E20-VL-05-B.png",
    ],
}

SPEAKER_REFS = {
    "陈迹": "ref_images/male_lead_chenji_ancient_face_ref_20260621.png",
    "皎兔": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "云羊": "ref_images/male_yunyang_ancient_ref_20260704.jpg",
    "白鲤": "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "佛子": "assets/reference/e20_20260716/characters/CHAR-fozi-luozhuisajia-e19-continuity-v1-20260716.jpg",
}

BEAT_ACTION = {
    "B01": "Warm patrol lamps advance along the wall route; the speaker turns toward the approaching pressure while Chenji scans the route before moving.",
    "B02": "The group moves along the wall-to-coffin route; the speaker shifts position as Chenji points the verifiable path toward the sealed coffin.",
    "B03": "At the sealed coffin site, the speaker leans toward the intact seal and coffin nails, then turns to the listener as the evidence enters the center of frame.",
    "B04": "Keep Jiaotu's physical body accounted for while the black-armored projection crosses the route; the speaker pivots between the body and coffin sightline.",
    "B05": "In the coffin-site reaction space, the speaker's controlled reaction changes the group reading; a hand lowers and the nearest patrol lamp shifts behind them.",
    "B06": "Only now reveal the coherent empty coffin interior; the speaker turns from the evidence to Chenji as the nearest patrol light stops.",
}

NEGATIVE = (
    "Negative controls: no modern police uniform, peaked cap, epaulettes, republic of china era, "
    "suitcase, briefcase, modern signage, modern police; no subtitles, captions, central bold dialogue text, "
    "readable generated Chinese, English letters, Latin letters; no slow motion, dreamy pace, floating, "
    "weightless, rubber physics; no static puppet, frozen pose, repeated movement, face drift, body drift, "
    "hunched posture, hands holding prop, foreground object, wrong face, malformed mouth or lip movement."
)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def main() -> int:
    source = json.loads(PERFORMANCE.read_text(encoding="utf-8"))
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    PREFLIGHT.parent.mkdir(parents=True, exist_ok=True)
    tasks = []
    failures = []

    for line in source["lines"]:
        dia_id = line["dia_id"]
        if dia_id in COMPLETED:
            continue
        beat = line["beat_id"]
        speaker = line["speaker"]
        refs = list(BEAT_VISUALS[beat])
        if speaker in SPEAKER_REFS:
            refs.append(SPEAKER_REFS[speaker])
        refs = refs[:3]
        missing_refs = [value for value in refs if not (ROOT / value).is_file()]
        if missing_refs:
            failures.append({"dia_id": dia_id, "missing_references": missing_refs})
            continue

        visual = (
            "Vertical 9:16 cinematic realism in the authoritative E20 continuous deep-night route from the patrol wall lane "
            "to the sealed coffin site. Dry or lightly damp ground, no new rain event; cool moon ambient and moving warm "
            "patrol lanterns. Preserve the reference identities, wardrobe, coffin geometry, route geography and light axis. "
            f"{BEAT_ACTION[beat]} Show {speaker} with restrained short-drama performance when visible; use a listener reaction "
            "or evidence insert if the mouth is obscured. Complete the action in real time. Do not invent a new location, "
            "time, weather, prop, character or event. Do not reveal the empty coffin before B06. Do not render spoken words. "
            + NEGATIVE
        )
        audio = (
            f"Speaker: {speaker}. Generate native Mandarin production audio synchronized in the same video pass. "
            f"Speak exactly and completely: \"{line['text']}\" Delivery: {line['delivery']['tone_code']}, "
            f"pace {line['delivery']['pace']}, volume {line['delivery']['volume']}, breath {line['delivery']['breath']}. "
            "Do not add, omit, paraphrase, substitute homophones, sing, shout, narrate or repeat. "
            "No standalone BGM; retain restrained location ambience and action sound only."
        )
        prompt_path = PROMPT_DIR / f"{slug(dia_id)}_{slug(speaker)}_multimodal_prompt.txt"
        prompt_path.write_text(
            f"VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n{visual}\nAUDIO_PROMPT_DIALOGUE_ONLY:\n{audio}\n",
            encoding="utf-8",
        )
        duration_plan = plan_dialogue_duration(
            line["text"],
            line["delivery"]["pace"],
            line["function"],
        )
        tasks.append(
            {
                "dialogue_id": dia_id,
                "source_id": f"E20-{dia_id}-STORY-DURATION-V2",
                "beat_id": beat,
                "speaker": speaker,
                "text": line["text"],
                "status": "READY_TO_SUBMIT",
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "reference_images": refs,
                "model": "seedance-2.0-pro",
                "duration": duration_plan["duration_seconds"],
                "duration_plan": duration_plan,
                "aspect_ratio": "9:16",
                "resolution": "720p",
                "force_resubmit": False,
            }
        )

    manifest = {
        "schema": "qingshan.giggle_task_manifest.v1",
        "episode": "E20",
        "authorization_ref": "ROGER-20260718-E20-FULL-MISSING-DIALOGUE-CONCURRENT-BATCH",
        "approval_refs": ["CL2X-291", "ROGER-20260718-E20-FULL-MISSING-DIALOGUE-CONCURRENT-BATCH"],
        "prompt_constitution_version": "v1",
        "shot_duration_policy": {
            "version": POLICY_VERSION,
            "range_seconds": [4, 15],
            "rule": "Duration is computed per shot from dialogue pace, required action and reaction/button coverage; batch concurrency never forces equal duration.",
        },
        "episode_total_prompt_count": len(tasks),
        "script_gate": {
            "beat_sheet": "configs/e20_dialogue_beat_sheet_v1_script_readiness_20260716.json",
            "report": "qa/e20_preflight_20260716/E20_SCRIPT_V2_EXCITEMENT_GATE_20260716.json",
        },
        "script_density_gate": {
            "script": "configs/e20_dialogue_beat_sheet_v1_script_readiness_20260716.json",
            "review": "workflow/script_review/reviews/E20_剧情密度审核_20260717.md",
        },
        "batch_policy": "Submit all missing dialogue video tasks concurrently; preserve the four completed multimodal candidates and retry only failures.",
        "completed_dialogue_ids_not_resubmitted": sorted(COMPLETED),
        "bgm_policy": "NO_EXTERNAL_BGM_MULTIMODAL_NATIVE_AUDIO_ONLY",
        "tasks": tasks,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    correction_manifest = {
        **manifest,
        "authorization_ref": "ROGER-20260718-STORY-DRIVEN-SHOT-DURATION-CORRECTION",
        "approval_refs": ["ROGER-20260718-STORY-DRIVEN-SHOT-DURATION-CORRECTION"],
        "episode_total_prompt_count": sum(task["duration"] > 4 for task in tasks),
        "batch_policy": "Preserve complete four-second sources. Concurrently regenerate only shots whose story-driven plan requires more than the prior four-second source.",
        "tasks": [
            {**task, "force_resubmit": True}
            for task in tasks
            if task["duration"] > 4
        ],
    }
    CORRECTION_MANIFEST.write_text(
        json.dumps(correction_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    preflight = {
        "schema": "qingshan.e20_missing_dialogue_compile_preflight.v1",
        "status": "PASS" if len(tasks) == 34 and not failures else "FAIL",
        "performance_line_count": len(source["lines"]),
        "preserved_completed_count": len(COMPLETED),
        "compiled_missing_count": len(tasks),
        "unique_dialogue_ids": len({task["dialogue_id"] for task in tasks}),
        "missing_reference_failures": failures,
        "scene_authority": "configs/e20_state_bible_20260716.json",
        "submission_manifest": str(MANIFEST.relative_to(ROOT)),
        "duration_correction_manifest": str(CORRECTION_MANIFEST.relative_to(ROOT)),
        "duration_correction_count": len(correction_manifest["tasks"]),
    }
    PREFLIGHT.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(preflight, ensure_ascii=False))
    return 0 if preflight["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
