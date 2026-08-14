#!/usr/bin/env python3
"""Build the E27 Writer Agent v0.4 24-shot AgentCut v14 project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SELECTION = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/production/final_video_source_selection/E27_WRITER_AGENT_V040_FINAL_VIDEO_SOURCE_SELECTION.json"
COMPILED = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/"
    "outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json"
)
PROJECT = ROOT / "configs/e27_agentcut_project_v14_writer_agent_v040_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v14_writer_agent_v040_20260720/E27_AGENTCUT_V14_WRITER_AGENT_V040_NOT_FINAL.mp4"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    compiled = json.loads(COMPILED.read_text(encoding="utf-8"))
    shots = {row["shot_id"]: row for row in compiled["shot_contracts"]}
    dialogues = {row["dialogue_id"]: row for row in compiled["dialogue_contracts"]}
    video_clips = []
    audio_clips = []
    cursor = 0.0
    previous_scene = None
    for selected in selection["items"]:
        shot = shots[selected["shot_id"]]
        duration = float(shot["duration_seconds"])
        scene_id = shot["scene_id"]
        if previous_scene is None:
            cut_reason = "ESTABLISH_ONCE"
        elif previous_scene != scene_id:
            cut_reason = "SCENE_TRANSITION"
        else:
            cut_reason = "NEW_INFORMATION"
        lines = [dialogues[line_id] for line_id in shot.get("dialogue_ids", [])]
        light = shot.get("continuity", {}).get("in", {}).get("light", shot.get("key_light", "LOCKED_SCENE_LIGHT"))
        common = {
            "episode": "E27",
            "source_id": shot["shot_id"],
            "shot_id": shot["shot_id"],
            "scene_id": scene_id,
            "source_sha256": selected["sha256"],
            "source_variant": selected["source_variant"],
            "source_admission": selected["admission"]["status"],
            "source_admission_confidence": selected["admission"]["confidence"],
            "cut_reason": cut_reason,
            "narrative_function": shot["action"],
            "new_information": shot["visual"],
            "semantic_group": shot["shot_id"],
            "fallback_only": False,
            "scene_id": scene_id,
            "light_key": str(light).upper().replace(" ", "_"),
            "axis_line": f"{scene_id}::LOCKED_ACTION_AXIS",
            "eyeline": f"{shot['shot_id']}::PRIMARY_ACTION_TARGET",
            "dialogue_ids": shot.get("dialogue_ids", []),
            "dialogue_lines": [
                {"dialogue_id": row["dialogue_id"], "speaker_id": row["speaker_id"], "text": row["text"]}
                for row in lines
            ],
            "expected_text": "".join(row["text"] for row in lines),
            "camera_motion": shot["camera_motion"],
            "shot_scale": shot["shot_scale"],
            "time_of_day": shot.get("continuity", {}).get("time_of_day"),
        }
        video_clips.append({
            "id": f"{shot['shot_id']}-VIDEO",
            "source": selected["path"],
            "start": cursor,
            "in": 0.0,
            "duration": duration,
            "metadata": common,
        })
        audio_clips.append({
            "id": f"{shot['shot_id']}-AUDIO",
            "source": selected["path"],
            "start": cursor,
            "in": 0.0,
            "duration": duration,
            "volume": 0.82,
            "metadata": {
                **common,
                "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            },
        })
        cursor += duration
        previous_scene = scene_id
    if round(cursor, 3) != 170.0:
        raise SystemExit(f"expected 170 seconds, got {cursor}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "requireCutReason": True,
        "output": {
            "path": str(OUTPUT),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True,
            "limiter": True,
            "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 3.0,
            "loudnessTargetLufs": -16,
            "loudnessRangeLu": 11,
            "maxClippedSamples": 0,
        },
        "metadata": {
            "episode": "E27",
            "status": "AGENTCUT_V14_WRITER_AGENT_V040_NOT_FINAL_FULL_QA_PENDING",
            "writer_agent_version": compiled["agent_version"],
            "writer_agent_schema": compiled["schema_version"],
            "compiled_contract": str(COMPILED),
            "compiled_contract_sha256": sha256(COMPILED),
            "source_selection": str(SELECTION),
            "source_selection_sha256": sha256(SELECTION),
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "no_padding": True,
            "runtime_seconds": cursor,
            "runtimePolicy": {"allowShorter": False, "paddingForbidden": True, "onCoverageGap": "fail"},
        },
        "timeline": {
            "videoTracks": [{"id": "E27_WRITER_AGENT_V040_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E27_WRITER_AGENT_V040_NATIVE_AUDIO", "clips": audio_clips}],
            "subtitleTracks": [],
        },
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = ROOT / "workflow/tasks/E27_AGENTCUT_V14_WRITER_AGENT_V040_BUILD_RECEIPT_20260720.json"
    receipt.write_text(json.dumps({
        "episode": "E27",
        "status": "READY_VALIDATE_COMPILE_RENDER",
        "agentcut_runtime_required": "0.9.7",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "shot_count": len(video_clips),
        "audio_clip_count": len(audio_clips),
        "runtime_seconds": cursor,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "shots": len(video_clips),
        "runtime_seconds": cursor,
        "output": str(OUTPUT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
