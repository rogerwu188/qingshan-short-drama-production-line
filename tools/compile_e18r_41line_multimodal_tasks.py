#!/usr/bin/env python3
"""Compile E18R's 41 approved lines into one native multimodal source task per line."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CANONICAL_REFERENCES = {
    "陈迹": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "白鲤": "assets/reference/characters_canonical_20260709/images/CHAR-baili-ancient-card-20260709.jpg",
    "乌云": "ref_images/cat_wuyun_reference.jpg",
}

BEAT_VISUALS = {
    "B01": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-PASTRY-BOX.png",
    "B02": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-NIGHT-ROAD-STRETCHER.png",
    "B03": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-PASTRY-BOX.png",
    "B04": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-CARRIAGE-TEST.png",
    "B05": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-RED-JADE-PENDANT.png",
    "B06": "working_assets/e18r_visual_lock_static_candidates_20260716/E18R-VL-NEW-ASSETS/E18R-VL-PASTRY-BOX.png",
}

EXTRA_BEAT_VISUALS = {
    "B02": "working_assets/e18r_visual_lock_static_repair_v2_20260716/E18R-VL-BRUISED-HAND-R2/E18R-VL-BRUISED-HAND-INSERT-R2.png",
}

TWO_ASR_SEGMENT_LINES = {"DIA-A7", "DIA-A9", "DIA-A11"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def speaker_direction(speaker: str) -> str:
    if speaker == "陈迹":
        return "Canonical Chenji remains tall and upright, turns his level gaze toward the evidence, and delivers one short line with restrained mouth movement."
    if speaker == "白鲤":
        return "Canonical Baili keeps her identity guarded, shifts one hand toward the evidence, and delivers one short line with controlled mouth movement."
    if speaker == "乌云":
        return "The canonical deep-gray to black long-haired Wuyun cat, with thick neck fur and pointed ears, stays on the same plane, turns its head toward the evidence, and the registered Wuyun voice is heard without human lips or a human face."
    return "Keep the side-role speaker offscreen or face-obscured while one hand or moving shadow advances the evidence action; the registered voice delivers one short line."


def render_prompt(line: dict, beat: dict) -> str:
    beat_id = beat["beat_id"]
    pauses = "Use one brief semantic breath at the punctuation so ASR may form two complete segments." if line["dia_id"] in TWO_ASR_SEGMENT_LINES else "Deliver as one complete natural sentence without truncation."
    visual = (
        "Vertical 9:16 cinematic period realism, pre-dawn after rain, cold blue ambient light with one warm period lantern. "
        f"Beat {beat_id} is {beat['name']}; show a real-time information-bearing action around the approved evidence reference. "
        f"{speaker_direction(line['speaker'])} Preserve wet ground, period materials, physical cause and effect, and continuous non-repeating motion. "
        "No generated story text appears in the image."
    )
    negative = (
        "modern police uniform, peaked cap, epaulettes, republic of china era, suitcase, briefcase, modern signage, modern police, "
        "readable generated Chinese, English letters, Latin letters, subtitles, captions, on-screen text, text overlay, watermark, "
        "caption bar, letterbox text, 字幕, 文字, 标题条, slow motion, dreamy pace, floating, weightless, rubber physics, "
        "static puppet, frozen pose, repeated movement, face drift, body drift, hunched posture, wrong face, extra person, duplicate person"
    )
    audio = {
        "dia_id": line["dia_id"],
        "speaker": line["speaker"],
        "voice_asset_id": line["voice_asset_id"],
        "text": line["text"],
        "performance": pauses,
    }
    return (
        f"VISUAL_PROMPT_NO_DIALOGUE_TEXT:\n{visual}\n\n"
        f"NEGATIVE_PROMPT:\n{negative}\n\n"
        "AUDIO_PROMPT_DIALOGUE_ONLY:\n"
        f"{json.dumps(audio, ensure_ascii=False, indent=2)}\n"
    )


def compile_tasks(binding: dict, coverage: dict, prompt_dir: Path, ready_beat: str = "B01") -> tuple[list[dict], dict]:
    lines = binding.get("lines") or []
    if len(lines) != 41:
        raise ValueError(f"Expected 41 voice-bound lines, found {len(lines)}")
    beat_by_dialogue = {}
    beats = {}
    for beat in coverage.get("beats") or []:
        beats[beat["beat_id"]] = beat
        for dia_id in beat.get("dialogue_ids") or []:
            if dia_id in beat_by_dialogue:
                raise ValueError(f"Duplicate dialogue coverage: {dia_id}")
            beat_by_dialogue[dia_id] = beat
    if set(beat_by_dialogue) != {line["dia_id"] for line in lines}:
        raise ValueError("Coverage dialogue IDs do not match the 41 voice-bound lines")

    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    planned_segments = 0
    for line in lines:
        beat = beat_by_dialogue[line["dia_id"]]
        prompt_path = prompt_dir / f"{line['dia_id']}_{line['speaker']}_prompt.txt"
        prompt_path.write_text(render_prompt(line, beat), encoding="utf-8")
        refs = [BEAT_VISUALS[beat["beat_id"]]]
        identity = CANONICAL_REFERENCES.get(line["speaker"])
        if identity:
            refs.insert(0, identity)
        if beat["beat_id"] in EXTRA_BEAT_VISUALS and line["dia_id"] in {"DIA-007", "DIA-008", "DIA-009", "DIA-010"}:
            refs.append(EXTRA_BEAT_VISUALS[beat["beat_id"]])
        planned = 2 if line["dia_id"] in TWO_ASR_SEGMENT_LINES else 1
        planned_segments += planned
        try:
            bound_prompt_path = str(prompt_path.relative_to(ROOT))
        except ValueError:
            bound_prompt_path = str(prompt_path)
        tasks.append({
            "dialogue_id": line["dia_id"],
            "source_id": f"E18R-{line['dia_id']}-MM-R1",
            "beat_id": beat["beat_id"],
            "speaker": line["speaker"],
            "text": line["text"],
            "voice_asset_id": line["voice_asset_id"],
            "planned_asr_segments": planned,
            "status": "READY_TO_SUBMIT" if beat["beat_id"] == ready_beat else "PLANNED_NOT_ACTIVE_BATCH",
            "prompt_path": bound_prompt_path,
            "prompt_sha256": sha256(prompt_path),
            "reference_images": refs,
            "model": "seedance-2.0-pro",
            "duration": 4,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "force_resubmit": False,
            "designated_static_beat": False,
        })

    silence_seconds = sum(float(row["duration_seconds"]) for row in (coverage.get("silence_windows") or []))
    if not silence_seconds:
        silence_seconds = 12.0
    runtime = len(tasks) * 4 + silence_seconds
    metrics = {
        "line_count": len(tasks),
        "pilot_task_count": sum(1 for row in tasks if row["status"] == "READY_TO_SUBMIT"),
        "planned_asr_segment_count": planned_segments,
        "line_video_seconds": len(tasks) * 4,
        "motivated_silence_seconds": silence_seconds,
        "planned_runtime_seconds": runtime,
        "planned_asr_segments_per_minute": round(planned_segments * 60 / runtime, 4),
        "density_gate_target": 15.0,
    }
    if metrics["planned_asr_segments_per_minute"] < 15.0:
        raise ValueError("Planned ASR segment density is below 15 segments/minute")
    return tasks, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binding", default=ROOT / "configs/e18r_dialogue_voice_binding_manifest_v1_20260716.json", type=Path)
    parser.add_argument("--coverage", default=ROOT / "configs/e18r_coverage_manifest_v1_20260716.json", type=Path)
    parser.add_argument("--prompt-dir", default=ROOT / "workflow/prompts/e18r_41line_multimodal_r1_20260716", type=Path)
    parser.add_argument("--manifest", default=ROOT / "configs/e18r_41line_multimodal_giggle_task_manifest_v1_20260716.json", type=Path)
    parser.add_argument("--preflight", default=ROOT / "qa/e18_final_package_pending_20260715/ci/E18R_41LINE_MULTIMODAL_PREFLIGHT_V1_20260716.json", type=Path)
    parser.add_argument("--script-gate-report", default=ROOT / "qa/e18_final_package_pending_20260715/ci/E18_REMAKE_SCRIPT_V2_READINESS_GATE_20260716.json", type=Path)
    parser.add_argument("--ready-beat", default="B01", choices=["B01", "B02", "B03", "B04", "B05", "B06"])
    args = parser.parse_args()

    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    coverage = json.loads(args.coverage.read_text(encoding="utf-8"))
    coverage["silence_windows"] = json.loads((ROOT / "configs/e18_remake_dialogue_beat_sheet_v1_20260716.json").read_text(encoding="utf-8")).get("silence_windows", [])
    tasks, metrics = compile_tasks(binding, coverage, args.prompt_dir, args.ready_beat)
    manifest = {
        "schema": "qingshan.giggle_task_manifest.v1",
        "episode": "E18R",
        "authorization_ref": "ROGER-20260716-E18-REMAKE",
        "prompt_constitution_version": "v1",
        "episode_total_prompt_count": 41,
        "script_gate": {
            "beat_sheet": "configs/e18_remake_dialogue_beat_sheet_v1_20260716.json",
            "report": str(args.script_gate_report.relative_to(ROOT)),
        },
        "pilot_policy": f"Only {args.ready_beat} tasks are READY_TO_SUBMIT in this batch manifest. Final source lock remains blocked until watch/listen QA.",
        "planning_metrics": metrics,
        "tasks": tasks,
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {
        "schema": "qingshan.e18r_41line_multimodal_preflight.v1",
        "episode": "E18R",
        "status": f"PASS_{args.ready_beat}_BATCH_READY_REMAINING_BEATS_STAGED",
        "authorization_ref": "ROGER-20260716-E18-REMAKE",
        "manifest": str(args.manifest),
        "metrics": metrics,
        "dialogue_text_in_visual_section": 0,
        "standalone_audio_generation_allowed": False,
        "final_density_requires_measured_asr": True,
        "release_rule": "Pilot generation does not authorize final source lock, edit, package or upload.",
    }
    args.preflight.parent.mkdir(parents=True, exist_ok=True)
    args.preflight.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": preflight["status"], **metrics}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
