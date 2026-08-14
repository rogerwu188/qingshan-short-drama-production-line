#!/usr/bin/env python3
"""Compile E16 listener-reaction coverage plans into UI-ready video prompts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_prompt(clip: dict) -> str:
    camera = clip["camera"]
    scale = clip["scale_and_posture"]
    actions = " -> ".join(clip["action_arc"])
    expression = clip["expression_arc"]
    duration = clip["duration_seconds"]
    return "\n".join(
        [
            f"E16 silent {clip['coverage']} coverage, source {clip['coverage_source_id']}.",
            f"Scene continuity: {clip['scene_id']}; {clip['light_key']}.",
            f"Listener: {clip['listener']}. The off-screen speaker remains outside frame.",
            (
                f"Camera: {camera['lens_mm']}mm lens, {camera['angle']}, vertical 9:16; "
                f"{camera['depth']}; axis {clip['axis_line']}; eyeline {clip['eyeline']}."
            ),
            (
                f"Framing and scale: human frame occupancy {scale['human_frame_occupancy']}; "
                f"Chenji height baseline {scale['chenji_height_cm']}cm; "
                f"Chenji posture, if present: {scale['chenji_posture']}; "
                f"Wuyun, if present: {scale['wuyun_if_present']}."
            ),
            (
                f"Performance arc across exactly {duration} seconds: facial expression starts as "
                f"{expression['start']}; exactly when {expression['trigger']}, the face visibly changes "
                f"and settles as {expression['end']}. Facial delta is primary; eyeline delta is secondary; "
                f"body action is tertiary. Blocking/action progression: {actions}. Preserve identity, "
                f"screen direction and spatial continuity throughout."
            ),
            clip["expression_prompt"],
            (
                "Timing: 0.0-0.4s established listening state; 0.4-1.8s the first visible reaction "
                "develops; 1.8-4.0s the reaction settles into a changed final state. "
                "No repeated gesture and no second action unit."
            ),
            f"Motion rule: {clip['motion']}; {clip['positive_speed']}.",
            clip.get("large_expression_unlock", "Natural readable expression change; no neutral-mask performance."),
            (
                "Sound rule: silent reaction coverage only, closed mouth, no dialogue, no lip-sync, "
                "no subtitles. This source will be used under a J/L-cut dialogue bridge."
            ),
            "World lock: Song/Ming Chinese period drama, physically plausible natural movement, exquisite cinematic image quality.",
            f"Negative prompt: {clip['negative_prompt']}",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-bindings", type=Path)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    data = json.loads(args.plan.read_text(encoding="utf-8"))
    asset_data = (
        json.loads(args.asset_bindings.read_text(encoding="utf-8"))
        if args.asset_bindings
        else {"characters": {}}
    )
    coverage_data = (
        json.loads(args.coverage.read_text(encoding="utf-8"))
        if args.coverage
        else {"beats": []}
    )
    beats = {beat["dialogue_beat_id"]: beat for beat in coverage_data.get("beats", [])}
    clips = data.get("clips", [])
    if not clips:
        raise SystemExit("coverage plan has no clips")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "qingshan.b_coverage_ui_prompt_package.v1",
        "episode": data.get("episode"),
        "source_plan": str(args.plan),
        "clip_count": len(clips),
        "status": "READY_FOR_UI_SUBMIT",
        "submission_policy": {
            "model": "Seedance 2.0 Fast",
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "duration_seconds": 4,
            "batch_size": 5,
            "preserve_manifest_order": True,
        },
        "clips": [],
    }

    required_negatives = (
        "slow motion",
        "modern police uniform",
        "English letters",
        "central bold dialogue text",
    )
    for clip in clips:
        missing = [term for term in required_negatives if term not in clip["negative_prompt"]]
        if missing:
            raise SystemExit(f"{clip['coverage_source_id']} missing negatives: {missing}")
        if clip["duration_seconds"] != 4:
            raise SystemExit(f"{clip['coverage_source_id']} must be exactly 4 seconds")
        if len(clip["serves_dialogue_beats"]) > clip["max_final_uses"]:
            raise SystemExit(f"{clip['coverage_source_id']} exceeds reuse limit")
        if set(clip.get("expression_arc", {})) != {"start", "trigger", "end"}:
            raise SystemExit(f"{clip['coverage_source_id']} missing constrained expression arc")

        source_id = clip["coverage_source_id"]
        listener = clip["listener"]
        references = []
        character_keys = {
            "陈迹": "CHAR-陈迹-古装",
            "白鲤": "CHAR-白鲤-古装",
            "验尸官": "CHAR-验尸官",
            "乌云": "CHAR-乌云-猫",
        }
        for token, key in character_keys.items():
            if token in listener:
                character = asset_data.get("characters", {}).get(key, {})
                for field in ("reference_image", "body_reference"):
                    if character.get(field) and character[field] not in references:
                        references.append(character[field])
        source_shots = []
        for beat_id in clip["serves_dialogue_beats"]:
            beat = beats.get(beat_id, {})
            shot_id = beat.get("A", {}).get("source_shot_id")
            if shot_id and shot_id not in source_shots:
                source_shots.append(shot_id)
        for shot_id in source_shots:
            candidates = sorted(
                (Path.cwd() / "assets/reference/e16_visual_locks_20260711").glob(
                    f"shot_{shot_id}_visual_lock.*"
                )
            )
            if candidates:
                scene_ref = str(candidates[0])
                if scene_ref not in references:
                    references.append(scene_ref)
        if not references:
            fallback_shot = (
                "19" if "后院" in clip["scene_id"] else "01"
            )
            fallback = (
                Path.cwd()
                / f"assets/reference/e16_visual_locks_20260711/shot_{fallback_shot}_visual_lock.jpg"
            )
            if fallback.exists():
                references.append(str(fallback))

        prompt_path = args.output_dir / f"{source_id.lower().replace('-', '_')}_ui.txt"
        prompt_path.write_text(build_prompt(clip) + "\n", encoding="utf-8")
        manifest["clips"].append(
            {
                "coverage_source_id": source_id,
                "serves_dialogue_beats": clip["serves_dialogue_beats"],
                "listener": listener,
                "reference_images": references,
                "prompt_file": str(prompt_path),
                "output_dir": f"working_assets/e16_api_20260711/ui_fallback/b_coverage/{source_id}",
                "qa_dir": f"qa/e16_ui_fallback_20260712/b_coverage/{source_id}",
                "status": "READY_FOR_UI_SUBMIT",
            }
        )

    for index, clip in enumerate(manifest["clips"]):
        clip["submission_batch"] = index // manifest["submission_policy"]["batch_size"] + 1

    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"compiled {len(clips)} prompts: {manifest_path}")


if __name__ == "__main__":
    main()
