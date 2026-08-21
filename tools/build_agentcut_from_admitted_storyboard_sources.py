#!/usr/bin/env python3
"""Build a fresh AgentCut project from admitted storyboard source slots."""

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.audio_postproduction_contract import PROFILE_CONFIG, validate_audio_profile
    from tools.sound_cue_contract import evaluate as evaluate_sound_cues
except ModuleNotFoundError:  # Direct execution from tools/.
    from audio_postproduction_contract import PROFILE_CONFIG, validate_audio_profile  # type: ignore
    from sound_cue_contract import evaluate as evaluate_sound_cues  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


def _abs(path):
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(episode, receipts, review_results, out_project, out_admission, output_video, expected_slots):
    if isinstance(review_results, (str, Path)):
        review_results = [review_results]
    passed_paths = set()
    for review_result in review_results:
        review = json.loads(_abs(review_result).read_text())
        passed_paths.update(str(Path(row["path"]).resolve()) for row in review.get("passed_items", []))
    admitted = {}
    latest_non_silent_audio = {}
    for receipt_path in receipts:
        receipt = json.loads(_abs(receipt_path).read_text())
        for task in receipt.get("tasks", []):
            source_id = task.get("source_id") or task.get("dialogue_id")
            output_path = task.get("output_path")
            if not source_id or not output_path or not _abs(output_path).is_file():
                continue
            metadata = task.get("metadata") or {}
            if not metadata.get("silent_visual_replacement"):
                latest_non_silent_audio[source_id] = task
            if task.get("status") == "qa_pass" or str(_abs(output_path).resolve()) in passed_paths:
                admitted[source_id] = task

    if len(admitted) != expected_slots:
        raise ValueError(f"expected {expected_slots} admitted slots, found {len(admitted)}: {sorted(admitted)}")
    missing_review = [source_id for source_id, task in admitted.items() if str(_abs(task["output_path"]).resolve()) not in passed_paths]
    if missing_review:
        raise ValueError(f"admitted sources missing AI-review PASS: {missing_review}")

    video_clips = []
    audio_clips = []
    admissions = []
    cursor = 0.0
    for source_id, task in sorted(admitted.items()):
        source = _abs(task["output_path"])
        duration = float(task.get("duration") or 4.0)
        metadata = task.get("metadata") or {}
        dialogue_lines = metadata.get("selected_dialogue") or []
        expected_text = "".join(str(row.get("text") or "") for row in dialogue_lines)
        silent = bool(metadata.get("silent_visual_replacement"))
        audio_task = latest_non_silent_audio.get(source_id) if silent else task
        if not audio_task or not _abs(audio_task["output_path"]).is_file():
            raise ValueError(f"missing admitted dialogue audio source for {source_id}")
        audio_source = _abs(audio_task["output_path"])
        audio_metadata = audio_task.get("metadata") or {}
        audio_dialogue_lines = audio_metadata.get("selected_dialogue") or []
        audio_expected_text = "".join(str(row.get("text") or "") for row in audio_dialogue_lines)
        if silent and audio_expected_text.strip():
            raise ValueError(
                f"speaking silent-visual replacement for {source_id} cannot reuse dialogue audio "
                "from another multimodal candidate"
            )
        clip_metadata = {
            "episode": episode,
            "source_id": source_id,
            "multimodal_task_id": task.get("task_id"),
            "beat_id": metadata.get("beat_id"),
            "source_qa": "PASS_OBJECTIVE_AND_AI_REVIEW",
            "visual_replacement_only": silent,
            "audio_source_preserved": silent,
            "source_review_batches": [str(_abs(path)) for path in review_results],
        }
        video_clips.append({
            "id": f"{episode}-{source_id}-VIDEO",
            "source": str(source),
            "start": round(cursor, 6),
            "in": 0.0,
            "duration": duration,
            "metadata": clip_metadata,
        })
        audio_clips.append({
            "id": f"{episode}-{source_id}-AUDIO",
            "source": str(audio_source),
            "start": round(cursor, 6),
            "in": 0.0,
            "duration": duration,
            "volume": 0.78,
            "metadata": {
                "source_id": source_id,
                "multimodal_task_id": audio_task.get("task_id"),
                "beat_id": metadata.get("beat_id"),
                "dialogue_lines": dialogue_lines,
                "expected_text": expected_text,
                "audio_origin": "NATIVE_MULTIMODAL_SOURCE",
                "dialogue_classification": "SPEAKING" if expected_text.strip() else "NON_SPEAKING",
                "reused_for_silent_visual": silent,
            },
        })
        admissions.append({
            "source_id": source_id,
            "video_path": str(source),
            "video_sha256": task.get("sha256") or sha256(source),
            "audio_path": str(audio_source),
            "audio_sha256": audio_task.get("sha256") or sha256(audio_source),
            "silent_visual_replacement": silent,
            "status": "PASS",
        })
        cursor += duration

    project_path = _abs(out_project)
    admission_path = _abs(out_admission)
    output_path = _abs(output_video)
    project_path.parent.mkdir(parents=True, exist_ok=True)
    admission_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {
            "episode": episode,
            "status": "STANDARD_STORYBOARD_AGENTCUT_NOT_FINAL",
            "source_review_batches": [str(_abs(path)) for path in review_results],
            "audio_policy": "PRESERVE_NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_WITH_SELECTIVE_BGM_BY_CUE",
            "source_audio_policy": "PRESERVE_NATIVE_MULTIMODAL_AUDIO",
            "audio_profile_id": "NATIVE_MULTIMODAL_SELECTIVE_BGM",
            "audio_profile_contract": str(PROFILE_CONFIG.relative_to(ROOT)),
            "sound_design_contract": {
                "mode": "NATIVE_EMBEDDED",
                "required_layers": ["DIALOGUE", "FOLEY", "AMBIENCE", "SFX"],
                "source_track_ids": [f"{episode}_NATIVE_AUDIO"],
                "external_bgm_allowed": True,
            },
            "no_padding": True,
            "runtime_seconds": round(cursor, 6),
            "change_scope": "Assemble all admitted storyboard slots; silent visual repairs reuse the latest non-silent source audio for the same slot.",
        },
        "output": {
            "path": str(output_path),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "audioSampleRate": 48000,
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
            "sampleRateHz": 48000,
        },
        "timeline": {
            "videoTracks": [{"id": f"{episode}_STANDARD_STORYBOARD_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": f"{episode}_NATIVE_AUDIO", "clips": audio_clips}],
            "subtitleTracks": [],
        },
    }
    profile_failures = validate_audio_profile(project)
    if profile_failures:
        raise ValueError(f"audio profile contract failed: {profile_failures}")
    sound_report = evaluate_sound_cues(project, root=ROOT)
    if sound_report["status"] != "PASS":
        raise ValueError(f"sound cue contract failed: {sound_report['failures']}")
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    admission_path.write_text(json.dumps({
        "schema": "qingshan.standard_storyboard_agentcut_admission.v1",
        "episode": episode,
        "status": "PASS",
        "review_results": [str(_abs(path)) for path in review_results],
        "project": str(project_path),
        "output": str(output_path),
        "runtime_seconds": round(cursor, 6),
        "sources": admissions,
    }, ensure_ascii=False, indent=2) + "\n")
    return {"status": "PASS", "episode": episode, "slots": len(admissions), "runtime_seconds": round(cursor, 6), "project": str(project_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--receipt", action="append", required=True)
    parser.add_argument("--review-result", action="append", required=True)
    parser.add_argument("--out-project", required=True)
    parser.add_argument("--out-admission", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--expected-slots", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.episode, args.receipt, args.review_result, args.out_project, args.out_admission, args.output_video, args.expected_slots), ensure_ascii=False))


if __name__ == "__main__":
    main()
