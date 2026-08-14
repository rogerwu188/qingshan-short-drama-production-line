#!/usr/bin/env python3
"""Build E20's no-padding AgentCut rough project from admitted dialogue and coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE = ROOT / "configs/e20_dialogue_performance_manifest_v2_20260716.json"
BEAT_SHEET = ROOT / "configs/e20_dialogue_beat_sheet_v1_script_readiness_20260716.json"
COVERAGE_ADMISSION = ROOT / "configs/e20_non_speaking_ordered_admission_v1_20260718.json"
ANTI_PADDING = ROOT / "configs/e20_agentcut_anti_padding_contract_v1_20260718.json"
ASR_BATCH = ROOT / "qa/e20_missing_34_multimodal_dialogue_batch_v1_20260718/E20_TECH_ASR_BATCH_QA_V2.json"
ASR_EXISTING_FOUR = ROOT / "qa/e20_missing_34_multimodal_dialogue_batch_v1_20260718/E20_EXISTING_4_ASR_TIMING_QA.json"
ASR_STORY_DURATION_CORRECTION = ROOT / "qa/e20_story_duration_correction_v2_20260718/E20_TECH_ASR_QA.json"
ASR_DIA006_CADENCE_R3 = ROOT / "qa/e20_story_duration_correction_v2_20260718/E20_DIA006_CADENCE_R3_TECH_ASR_QA.json"
OUTPUT = ROOT / "configs/e20_agentcut_project_v1_no_padding_rough_20260718.json"
RENDER = ROOT / "exports/e20/agentcut_v1_no_padding_rough_20260718/E20_AGENTCUT_V1_NO_PADDING_ROUGH_NOT_FINAL.mp4"

BASE_DIALOGUE = ROOT / "working_assets/e20_missing_34_multimodal_dialogue_batch_v1_20260718"
EXISTING_DIALOGUE = ROOT / "working_assets/e20_multimodal_bgm_decoupled_20260718"
EXISTING_DIA017 = ROOT / "working_assets/e20_multimodal_dia017_prompt_only_fallback_20260718/DIA-017.mp4"
PICTURE_SALVAGE = ROOT / "working_assets/e20_visual_salvage_picture_v1_20260718"
QA_RETRY_TWO = ROOT / "working_assets/e20_qa_failed_2_retry_v1_20260718"
ASR_RETRY_DIA018 = ROOT / "working_assets/e20_dia018_asr_failed_single_ref_retry_v2_20260718"
AUDIO_RETRY_FIVE = ROOT / "working_assets/e20_audio_exactness_failed_5_prompt_only_retry_v1_20260718"
STORY_DURATION_CORRECTION = ROOT / "working_assets/e20_story_duration_correction_merged_v2_20260718"
DIA006_CADENCE_R3 = ROOT / "working_assets/e20_story_duration_correction_dia006_cadence_r3_20260718"

STORY_DURATION_CORRECTION_IDS = {
    "DIA-003",
    "DIA-006",
    "DIA-007",
    "DIA-013",
    "DIA-021",
    "DIA-022",
    "DIA-032",
    "DIA-V2-004",
    "DIA-V2-006",
}

VISUAL_SALVAGE_IDS = {
    "DIA-004",
    "DIA-007",
    "DIA-013",
    "DIA-022",
    "DIA-026",
    "DIA-030",
    "DIA-V2-001",
}
AUDIO_RETRY_IDS = {"DIA-007", "DIA-013", "DIA-022", "DIA-030", "DIA-V2-001"}

# Retry sources differ from the original batch reports and keep explicit windows.
OVERRIDE_AUDIO_WINDOWS = {
    "DIA-004": (2.50, 1.563),
    "DIA-007": (2.70, 3.36),
    "DIA-013": (2.30, 1.763),
    "DIA-018": (3.00, 3.06),
    "DIA-022": (3.30, 2.76),
    "DIA-026": (2.70, 1.363),
    "DIA-030": (3.20, 2.68),
    "DIA-V2-001": (3.20, 2.86),
}

SCENE_ID = "E20-S01-PATROL-TO-SEALED-COFFIN-ROUTE"
LIGHT_KEY = "DEEP_NIGHT_COOL_AMBIENT_WITH_MOVING_WARM_PATROL_LANTERNS"
AXIS_LINE = "COFFIN_ROUTE_CHENJI_RIGHT_PATROL_LEFT"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def asr_windows() -> dict[str, tuple[float, float]]:
    windows: dict[str, tuple[float, float]] = {}
    for report_path in (ASR_BATCH, ASR_EXISTING_FOUR):
        for row in read(report_path).get("results", []):
            if row["dialogue_id"] in STORY_DURATION_CORRECTION_IDS:
                continue
            segments = row.get("segments") or []
            if not segments:
                continue
            speech_in = min(float(segment["start"]) for segment in segments)
            speech_out = max(float(segment["end"]) for segment in segments)
            source = original_dialogue_source(row["dialogue_id"])
            source_duration = duration(source)
            source_in = max(0.0, speech_in - 0.14)
            source_out = min(source_duration, speech_out + 0.20)
            windows[row["dialogue_id"]] = (
                round(source_in, 6),
                round(source_out - source_in, 6),
            )
    windows.update(OVERRIDE_AUDIO_WINDOWS)
    correction_rows = read(ASR_STORY_DURATION_CORRECTION).get("results", [])
    correction_rows += read(ASR_DIA006_CADENCE_R3).get("results", [])
    for row in correction_rows:
        if row["dialogue_id"] not in STORY_DURATION_CORRECTION_IDS:
            continue
        if row["dialogue_id"] == "DIA-006" and row["path"] != str(DIA006_CADENCE_R3 / "DIA-006.mp4"):
            continue
        segments = row.get("segments") or []
        if not segments:
            continue
        speech_in = min(float(segment["start"]) for segment in segments)
        speech_out = max(float(segment["end"]) for segment in segments)
        source = audio_source(row["dialogue_id"])[0]
        source_duration = duration(source)
        source_in = max(0.0, speech_in - 0.14)
        source_out = min(source_duration, speech_out + 0.20)
        windows[row["dialogue_id"]] = (
            round(source_in, 6),
            round(source_out - source_in, 6),
        )
    return windows


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def original_dialogue_source(dialogue_id: str) -> Path:
    if dialogue_id == "DIA-017":
        return EXISTING_DIA017
    existing = EXISTING_DIALOGUE / f"{dialogue_id}.mp4"
    return existing if existing.is_file() else BASE_DIALOGUE / f"{dialogue_id}.mp4"


def audio_source(dialogue_id: str) -> tuple[Path, bool]:
    if dialogue_id in STORY_DURATION_CORRECTION_IDS:
        candidate = (
            DIA006_CADENCE_R3 / "DIA-006.mp4"
            if dialogue_id == "DIA-006"
            else STORY_DURATION_CORRECTION / f"{dialogue_id}.mp4"
        )
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate, False
    if dialogue_id == "DIA-018":
        candidate = ASR_RETRY_DIA018 / "DIA-018.mp4"
        if candidate.is_file():
            return candidate, False
        return QA_RETRY_TWO / "DIA-018.mp4", True
    if dialogue_id == "DIA-029":
        return QA_RETRY_TWO / "DIA-029.mp4", False
    if dialogue_id == "DIA-013":
        # The retry said "泥沙". The original's "你尚" is the exact acoustic
        # homophone of script-locked "泥上" and is the safer contextual take.
        return original_dialogue_source(dialogue_id), False
    if dialogue_id in AUDIO_RETRY_IDS:
        candidate = AUDIO_RETRY_FIVE / f"{dialogue_id}.mp4"
        if candidate.is_file():
            return candidate, False
        return original_dialogue_source(dialogue_id), True
    return original_dialogue_source(dialogue_id), False


def video_source(dialogue_id: str, audio: Path) -> Path:
    if dialogue_id in VISUAL_SALVAGE_IDS:
        return PICTURE_SALVAGE / f"{dialogue_id}.mp4"
    return audio


def main() -> None:
    performance = read(PERFORMANCE)
    beat_sheet = read(BEAT_SHEET)
    coverage = read(COVERAGE_ADMISSION)
    structure = {row["beat_id"]: row for row in beat_sheet["structure"]}
    coverage_by_beat = {row["beat_id"]: row for row in coverage["order"]}
    audio_windows = asr_windows()

    lines = performance["lines"]
    if len(lines) != 38:
        raise ValueError(f"E20 requires 38 dialogue lines, got {len(lines)}")
    if set(coverage_by_beat) != set(structure):
        raise ValueError("Coverage admission does not contain exactly B01-B06")

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    pending_audio_ids: list[str] = []
    cursor = 0.0
    previous_speaker: str | None = None

    for index, line in enumerate(lines):
        dialogue_id = line["dia_id"]
        speaker = line["speaker"]
        beat_id = line["beat_id"]
        audio, pending = audio_source(dialogue_id)
        picture = video_source(dialogue_id, audio)
        for path in (audio, picture):
            if not path.is_file():
                raise FileNotFoundError(path)
        if pending:
            pending_audio_ids.append(dialogue_id)

        if dialogue_id not in audio_windows:
            raise ValueError(f"Missing ASR timing window for {dialogue_id}")
        audio_in, requested_duration = audio_windows[dialogue_id]
        picture_in = audio_in if picture == audio else 0.0
        clip_duration = round(
            min(
                requested_duration,
                duration(audio) - audio_in,
                duration(picture) - picture_in,
            ),
            6,
        )
        if clip_duration < 1.0:
            raise ValueError(f"Dialogue source too short for {dialogue_id}: {clip_duration}")
        if index == 0:
            cut_reason = "ESTABLISH_ONCE"
            reason_fields = {
                "establishes": "Patrol lanterns are already closing on the coffin route as the search order lands."
            }
        elif speaker != previous_speaker:
            cut_reason = "SPEAKER_CHANGE"
            reason_fields = {"speaker": speaker}
        else:
            cut_reason = "NEW_INFORMATION"
            reason_fields = {"new_information": line["function"]}

        metadata = {
            "episode": "E20",
            "beat_id": beat_id,
            "dialogue_id": dialogue_id,
            "speaker": speaker,
            "exact_dialogue": line["text"],
            "dialogue_function": line["function"],
            "new_information": line["function"],
            "source_qa": "PENDING_AUDIO_RETRY_QA" if pending else "PASS_EDIT_ADMISSION",
            "cut_reason": cut_reason,
            "narrative_function": line["function"],
            "semantic_group": f"{beat_id}_{dialogue_id}",
            "fallback_only": False,
            "scene_id": SCENE_ID,
            "light_key": LIGHT_KEY,
            "axis_line": AXIS_LINE,
            "eyeline": f"{speaker}_TO_CURRENT_LISTENER",
            "visual_policy": (
                "LOCKED_STILL_MOTIVATED_INSERT_WRONG_ACTOR_VIDEO_REJECTED"
                if dialogue_id in VISUAL_SALVAGE_IDS
                else "NATIVE_MULTIMODAL_DIALOGUE_PICTURE"
            ),
            **reason_fields,
        }
        video_clips.append(
            {
                "id": f"E20-{dialogue_id}-VIDEO",
                "source": str(picture),
                "start": round(cursor, 6),
                "in": round(picture_in, 6),
                "duration": clip_duration,
                "metadata": metadata,
            }
        )
        audio_clips.append(
            {
                "id": f"E20-{dialogue_id}-AUDIO",
                "source": str(audio),
                "start": round(cursor, 6),
                "in": round(audio_in, 6),
                "duration": clip_duration,
                "volume": 0.72,
            }
        )
        cursor += clip_duration
        previous_speaker = speaker

        next_beat = lines[index + 1]["beat_id"] if index + 1 < len(lines) else None
        if beat_id == next_beat:
            continue
        coverage_row = coverage_by_beat[beat_id]
        coverage_source = ROOT / coverage_row["media"]
        if not coverage_source.is_file():
            raise FileNotFoundError(coverage_source)
        coverage_duration = round(min(duration(coverage_source), 4.0), 6)
        new_information = structure[beat_id]["new_information"]
        must_show = "; ".join(structure[beat_id]["must_show"])
        video_clips.append(
            {
                "id": f"E20-{beat_id}-MOTIVATED-COVERAGE",
                "source": str(coverage_source),
                "start": round(cursor, 6),
                "in": 0.0,
                "duration": coverage_duration,
                "metadata": {
                    "episode": "E20",
                    "beat_id": beat_id,
                    "source_qa": coverage_row["status"],
                    "cut_reason": "NEW_INFORMATION",
                    "new_information": new_information,
                    "insert_reason": f"Show the script-required evidence/action: {must_show}",
                    "narrative_function": structure[beat_id]["function"],
                    "semantic_group": f"{beat_id}_MOTIVATED_COVERAGE",
                    "fallback_only": False,
                    "scene_id": SCENE_ID,
                    "light_key": LIGHT_KEY,
                    "axis_line": AXIS_LINE,
                    "eyeline": f"{beat_id}_EVIDENCE_INSERT",
                    "audio_policy": "NATIVE_SFX_AMBIENCE_NO_DIALOGUE_NO_EXTERNAL_BGM",
                },
            }
        )
        audio_clips.append(
            {
                "id": f"E20-{beat_id}-MOTIVATED-COVERAGE-AUDIO",
                "source": str(coverage_source),
                "start": round(cursor, 6),
                "in": 0.0,
                "duration": coverage_duration,
                "volume": 0.6,
            }
        )
        cursor += coverage_duration

    project = {
        "version": "1.0",
        "requireCutReason": True,
        "background": "black",
        "runtimePolicy": {
            "allowShorter": True,
            "paddingForbidden": True,
            "onCoverageGap": "fail",
        },
        "metadata": {
            "episode": "E20",
            "status": "ROUGH_STRUCTURE_NOT_FINAL_PENDING_FAILED_ONLY_AUDIO_QA"
            if pending_audio_ids
            else "ROUGH_STRUCTURE_READY_FOR_FULL_QA",
            "script_authority": str(BEAT_SHEET),
            "performance_authority": str(PERFORMANCE),
            "coverage_admission": str(COVERAGE_ADMISSION),
            "story_duration_correction_qa": str(ASR_STORY_DURATION_CORRECTION),
            "dia006_cadence_retry_qa": str(ASR_DIA006_CADENCE_R3),
            "anti_padding_contract": str(ANTI_PADDING),
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "no_padding": True,
            "runtimePolicy": {
                "allowShorter": True,
                "paddingForbidden": True,
                "onCoverageGap": "fail",
            },
            "runtime_seconds": round(cursor, 6),
            "pending_audio_retry_ids": pending_audio_ids,
            "rejected_visual_ids": sorted(VISUAL_SALVAGE_IDS),
            "rejected_visual_policy": "wrong-identity videos supply audio only; locked beat imagery supplies picture",
        },
        "output": {
            "path": str(RENDER),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "timeline": {
            "videoTracks": [{"id": "E20_DIALOGUE_AND_MOTIVATED_COVERAGE", "clips": video_clips}],
            "audioTracks": [{"id": "E20_NATIVE_AUDIO", "clips": audio_clips}],
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
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(OUTPUT),
                "runtime_seconds": round(cursor, 6),
                "video_clip_count": len(video_clips),
                "pending_audio_retry_ids": pending_audio_ids,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
