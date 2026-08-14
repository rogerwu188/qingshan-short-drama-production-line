#!/usr/bin/env python3
"""Build the E23 v4 135-second AgentCut project from admitted coverage."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e23_agentcut_project_v1_rough_20260719.json"
OUTPUT = ROOT / "configs/e23_agentcut_project_v2_v4_135s_20260719.json"
SCRIPT = ROOT / "configs/e23_dialogue_beat_sheet_v4_us_drama_council_density_20260719.json"
RENDER = ROOT / "exports/e23/agentcut_v2_v4_135s_20260719/E23_AGENTCUT_V2_V4_135S_NOT_FINAL.mp4"

COVERAGE = {
    "B01": ROOT / "working_assets/e23_motivated_coverage_video_wave_v1_20260719/candidates/E23-B01-COVERAGE-VIDEO.mp4",
    "B02": ROOT / "working_assets/e23_motivated_coverage_video_wave_r3_failed_only_20260719/candidates/E23-B02-COVERAGE-VIDEO-R3.mp4",
    "B03": ROOT / "working_assets/e23_motivated_coverage_video_wave_r2_failed_only_20260719/candidates/E23-B03-COVERAGE-VIDEO-R2.mp4",
    "B04": ROOT / "working_assets/e23_motivated_coverage_video_wave_v1_20260719/candidates/E23-B04-COVERAGE-VIDEO.mp4",
    "B05": ROOT / "working_assets/e23_motivated_coverage_video_wave_r3_failed_only_20260719/candidates/E23-B05-COVERAGE-VIDEO-R3.mp4",
    "B06": ROOT / "working_assets/e23_motivated_coverage_video_wave_v1_20260719/candidates/E23-B06-COVERAGE-VIDEO.mp4",
}


def coverage_video(beat_id: str, start: float) -> dict:
    source = COVERAGE[beat_id]
    return {
        "id": f"E23-{beat_id}-COVERAGE-VIDEO-ADMITTED",
        "source": str(source),
        "start": round(start, 6),
        "in": 0.0,
        "duration": 3.0,
        "metadata": {
            "episode": "E23",
            "beat_id": beat_id,
            "source_qa": "PASS_EDIT_ADMISSION",
            "cut_reason": "NEW_INFORMATION",
            "new_information": f"Script-locked motivated evidence/action insert for {beat_id}",
            "narrative_function": "motivated_coverage",
            "semantic_group": f"{beat_id}_COVERAGE",
            "fallback_only": False,
            "scene_id": "E23-S01-ZHANGXIA-ACCOUNT-ROOM",
            "light_key": "CLEAR_DUSK_WARM_ACCOUNT_ROOM",
            "axis_line": "ACCOUNT_TABLE_CHENJI_RIGHT_ZHANGXIA_LEFT",
            "eyeline": "EVIDENCE_INSERT_DOWNWARD_TO_ACCOUNT_TABLE",
            "audio_policy": "NATIVE_SFX_AMBIENCE_NO_DIALOGUE_NO_EXTERNAL_BGM",
        },
    }


def coverage_audio(beat_id: str, start: float) -> dict:
    return {
        "id": f"E23-{beat_id}-COVERAGE-AUDIO-ADMITTED",
        "source": str(COVERAGE[beat_id]),
        "start": round(start, 6),
        "in": 0.0,
        "duration": 3.0,
        "volume": 0.5,
    }


def main() -> None:
    for beat_id, path in COVERAGE.items():
        if not path.is_file():
            raise FileNotFoundError(f"Missing admitted coverage for {beat_id}: {path}")

    project = json.loads(SOURCE.read_text())
    old_video = project["timeline"]["videoTracks"][0]["clips"]
    old_audio = project["timeline"]["audioTracks"][0]["clips"]
    if len(old_video) != len(old_audio):
        raise ValueError("Dialogue video/audio clip counts differ")

    new_video: list[dict] = []
    new_audio: list[dict] = []
    cursor = 0.0
    for index, (video, audio) in enumerate(zip(old_video, old_audio)):
        video = copy.deepcopy(video)
        audio = copy.deepcopy(audio)
        video["start"] = round(cursor, 6)
        audio["start"] = round(cursor, 6)
        new_video.append(video)
        new_audio.append(audio)
        cursor += float(video["duration"])

        beat_id = video["metadata"]["beat_id"]
        next_beat = old_video[index + 1]["metadata"]["beat_id"] if index + 1 < len(old_video) else None
        if beat_id != next_beat:
            new_video.append(coverage_video(beat_id, cursor))
            new_audio.append(coverage_audio(beat_id, cursor))
            cursor += 3.0

    project["timeline"]["videoTracks"][0]["clips"] = new_video
    project["timeline"]["audioTracks"][0]["clips"] = new_audio
    project["metadata"].update(
        {
            "status": "V4_135S_COVERAGE_ROUGH_NOT_FINAL",
            "script_authority": str(SCRIPT),
            "runtime_seconds": round(cursor, 6),
            "coverage_policy": "six_admitted_script_locked_inserts_after_each_beat; 3.0s_each",
            "coverage_qa": str(ROOT / "workflow/tasks/E23_MOTIVATED_COVERAGE_VIDEO_WAVE_V1_20260719.json"),
            "no_padding": True,
        }
    )
    project["masterAudioPolicy"]["codecHeadroomDb"] = 2.8
    project["metadata"]["audio_gain_policy"] = (
        "native_audio_uniform_0.50; loudnorm_-16_LUFS; "
        "codec_headroom_2.8dB_for_AAC_true_peak_and_loudness_balance"
    )
    project["output"]["path"] = str(RENDER)
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")

    expected = 135.000008
    if abs(cursor - expected) > 0.001:
        raise ValueError(f"Unexpected runtime {cursor}; expected approximately {expected}")
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "runtime_seconds": round(cursor, 6), "video_clips": len(new_video), "audio_clips": len(new_audio)}))


if __name__ == "__main__":
    main()
