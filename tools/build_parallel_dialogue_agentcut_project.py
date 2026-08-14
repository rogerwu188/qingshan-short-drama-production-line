#!/usr/bin/env python3
"""Build an auditable AgentCut rough-cut project from a completed dialogue batch."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


TOOL_VERSION = "0.2.1"


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    probe = json.loads(result.stdout)
    durations = [
        float(stream["duration"])
        for stream in probe.get("streams", [])
        if stream.get("codec_type") in {"video", "audio"} and stream.get("duration")
    ]
    if not durations and (probe.get("format") or {}).get("duration"):
        durations.append(float(probe["format"]["duration"]))
    if not durations:
        raise ValueError(f"no measurable media duration: {path}")
    # A clip containing native video and audio can only use their shared range.
    return round(min(durations), 6)


def scene_lookup(scene_state: dict) -> dict[str, dict]:
    return {row["scene_id"]: row for row in scene_state.get("scene_state", [])}


def light_key(scene: dict) -> str:
    return f"{scene.get('time_of_day', 'UNSPECIFIED')}_{scene.get('weather', 'UNSPECIFIED')}".upper()


def subtitle_display_text(text: str) -> str:
    """Keep dialogue wording intact while avoiding FFmpeg drawtext quote parsing."""
    return re.sub(r"'([^']+)'", r"“\1”", text)


def cut_contract(task: dict, previous: dict | None, scene: dict) -> dict:
    speaker = task.get("speaker") or "UNSPECIFIED_SPEAKER"
    if previous is None or previous.get("scene_id") != task.get("scene_id"):
        reason = "ESTABLISH_ONCE"
    elif previous.get("speaker") != speaker:
        reason = "SPEAKER_CHANGE"
    else:
        reason = "NEW_INFORMATION"
    metadata = {
        "cut_reason": reason,
        "scene_id": task["scene_id"],
        "light_key": light_key(scene),
        "axis_line": f"{task['scene_id']}_PRIMARY_180_AXIS",
        "eyeline": f"{speaker}_TO_CURRENT_LISTENER",
        "speaker": speaker,
        "new_information": task.get("exact_dialogue"),
    }
    if reason == "ESTABLISH_ONCE":
        metadata["establishes"] = scene.get("event_summary") or scene.get("location") or task["scene_id"]
    return metadata


def build_project(receipt: dict, scene_state: dict, output_video: Path) -> dict:
    episode = receipt["episode"]
    scenes = scene_lookup(scene_state)
    tasks = receipt.get("tasks", [])
    if receipt.get("status") != "BATCH_COMPLETE":
        raise ValueError("dialogue batch is not complete")
    if not tasks or any(task.get("status") != "qa_pass" for task in tasks):
        raise ValueError("every dialogue task must be qa_pass")

    video_clips = []
    audio_clips = []
    subtitle_clips = []
    expected_ids = []
    cursor = 0.0
    previous = None
    for index, task in enumerate(tasks, start=1):
        task_metadata = task.get("metadata") or {}
        task = {
            **task,
            "beat_id": task.get("beat_id") or task_metadata.get("beat_id"),
            "dialogue_id": (
                task.get("dialogue_id")
                or task.get("dia_id")
                or task_metadata.get("dialogue_id")
                or task_metadata.get("dia_id")
            ),
            "speaker": task.get("speaker") or task_metadata.get("speaker"),
            "exact_dialogue": task.get("exact_dialogue") or task_metadata.get("exact_dialogue"),
        }
        source = Path(task["output_path"]).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        scene = scenes.get(task["scene_id"])
        if not scene:
            raise ValueError(f"missing scene authority for {task['scene_id']}")
        duration = media_duration(source)
        dialogue_id = task.get("dialogue_id") or task.get("dia_id")
        if not dialogue_id or not task.get("exact_dialogue"):
            raise ValueError(f"missing dialogue identity or exact dialogue: {task.get('task_key')}")
        expected_ids.append(dialogue_id)
        metadata = {
            "episode": episode,
            "beat_id": task.get("beat_id"),
            "dialogue_id": dialogue_id,
            "exact_dialogue": task.get("exact_dialogue"),
            "source_qa": "PASS_EDIT_ADMISSION",
            "narrative_function": task.get("exact_dialogue"),
            "semantic_group": f"{task.get('beat_id')}_{dialogue_id}",
            "fallback_only": False,
            "duration_plan": task.get("duration_plan"),
            **cut_contract(task, previous, scene),
        }
        video_clips.append(
            {
                "id": f"{episode}-{dialogue_id}-VIDEO",
                "source": str(source),
                "start": round(cursor, 6),
                "in": 0.0,
                "duration": duration,
                "metadata": metadata,
            }
        )
        audio_clips.append(
            {
                "id": f"{episode}-{dialogue_id}-AUDIO",
                "source": str(source),
                "start": round(cursor, 6),
                "in": 0.0,
                "duration": duration,
                "volume": 0.72,
            }
        )
        subtitle_inset = min(0.12, duration / 4.0)
        subtitle_clips.append(
            {
                "id": f"{episode}-CAP-{index:03d}",
                "dialogue_id": dialogue_id,
                "text": subtitle_display_text(task.get("exact_dialogue", "")),
                "start": round(cursor + subtitle_inset, 6),
                "duration": round(max(0.25, duration - 2 * subtitle_inset), 6),
                "metadata": {
                    "episode": episode,
                    "beat_id": task.get("beat_id"),
                    "speaker": task.get("speaker"),
                    "source": "approved_script_exact_dialogue",
                    "display_punctuation_normalized": subtitle_display_text(task.get("exact_dialogue", ""))
                    != task.get("exact_dialogue", ""),
                },
            }
        )
        cursor += duration
        previous = task

    return {
        "version": "1.0",
        "requireCutReason": True,
        "background": "black",
        "runtimePolicy": {"allowShorter": True, "paddingForbidden": True, "onCoverageGap": "fail"},
        "metadata": {
            "episode": episode,
            "status": "FULL_DIALOGUE_BATCH_ROUGH_CUT_NOT_FINAL",
            "builder_version": TOOL_VERSION,
            "source_receipt": receipt.get("config"),
            "scene_authority": scene_state.get("source_script"),
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "no_padding": True,
            "runtime_seconds": round(cursor, 6),
            "subtitle_contract": {
                "coverage": f"{len(expected_ids)}/{len(expected_ids)}",
                "ordered_dialogue_ids_match": True,
                "burned_in": True,
            },
        },
        "output": {
            "path": str(output_video.resolve()),
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
        "expectedDialogueIds": expected_ids,
        "timeline": {
            "videoTracks": [{"id": f"{episode}_FULL_DIALOGUE", "clips": video_clips}],
            "audioTracks": [{"id": f"{episode}_NATIVE_AUDIO", "clips": audio_clips}],
            "subtitleTracks": [
                {
                    "id": f"{episode}_ZH_CN_BURNIN_V1",
                    "enabled": True,
                    "style": {
                        "font": "/System/Library/Fonts/STHeiti Medium.ttc",
                        "size": 42,
                        "color": "#FFFFFF",
                        "outline": 3,
                        "outlineColor": "#000000",
                        "alignment": "bottom-center",
                        "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
                        "wrap": 15,
                    },
                    "clips": subtitle_clips,
                }
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="version", version=TOOL_VERSION)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--scene-state", type=Path, required=True)
    parser.add_argument("--output-video", type=Path, required=True)
    parser.add_argument("--output-project", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    state = json.loads(args.scene_state.read_text(encoding="utf-8"))
    project = build_project(receipt, state, args.output_video)
    args.output_project.parent.mkdir(parents=True, exist_ok=True)
    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    args.output_project.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(args.output_project), "clips": len(project["expectedDialogueIds"]), "runtime_seconds": project["metadata"]["runtime_seconds"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
