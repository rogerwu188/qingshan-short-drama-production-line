#!/usr/bin/env python3
"""Replace every remaining E37 dialogue camera-motion source with fixed-composition media."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v17_long_take_bgm_subtitles_nalu_outro_20260804.json"
OUTPUT = ROOT / "configs/e37_agentcut_v18_full_episode_fixed_camera_long_take_bgm_subtitles_nalu_outro_20260804.json"
RENDER_OUTPUT = ROOT / "exports/e37/agentcut_v18_full_episode_camera_repair_20260804/E37_AGENTCUT_V18_FULL_EPISODE_CAMERA_REPAIR_NOT_FINAL.mp4"

V15 = ROOT / "working_assets/e37_v15_fixed_camera_repair_20260804/video"
V16 = ROOT / "working_assets/e37_v16_failed_only_dialogue_retry_20260804/outputs"
QA15 = ROOT / "qa/e37_v15_fixed_camera_repair_20260804/per_source_machine"
QA16 = ROOT / "qa/e37_v16_failed_only_dialogue_retry_20260804"

REPLACEMENTS = {
    "U03-S1": (V16 / "task-001.mp4", QA16 / "U03_S1_CADENCE.json", "V16_THREE_FIXED_COMPOSITIONS"),
    "U03-S2": (V16 / "task-002.mp4", QA16 / "U03_S2_CADENCE.json", "V16_THREE_FIXED_COMPOSITIONS"),
    "U03-S3": (V15 / "E37_U03_S3_FIXED_TWO_COMPOSITIONS_V15_57b93ce3-25fa-42ba-ab64-5bccdf2a1f02.mp4", QA15 / "U03_S3_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U03-S4": (V15 / "E37_U03_S4_FIXED_TWO_COMPOSITIONS_V15_03e5410d-8c2e-43a0-8710-6a04cc58e267.mp4", QA15 / "U03_S4_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U07-S1": (V16 / "task-003.mp4", QA16 / "U07_S1_CADENCE.json", "V16_THREE_FIXED_COMPOSITIONS"),
    "U07-S2": (V15 / "E37_U07_S2_FIXED_TWO_COMPOSITIONS_V15_767fa688-b43e-4d51-851b-d3c577b2645d.mp4", QA15 / "U07_S2_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U07-S3": (V15 / "E37_U07_S3_FIXED_TWO_COMPOSITIONS_V15_c0ba239d-3d94-479c-91c9-696572dcca5f.mp4", QA15 / "U07_S3_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U07-S4": (V15 / "E37_U07_S4_FIXED_TWO_COMPOSITIONS_V15_272f297e-0987-4a80-ab02-d2831e3b47e5.mp4", QA15 / "U07_S4_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U07-S5": (V15 / "E37_U07_S5_FIXED_TWO_COMPOSITIONS_V15_88e3d047-2655-4b96-a848-bfd403c1aa0d.mp4", QA15 / "U07_S5_CADENCE.json", "V15_TWO_FIXED_COMPOSITIONS"),
    "U07-S6": (V16 / "task-004.mp4", QA16 / "U07_S6_CADENCE.json", "V16_THREE_FIXED_COMPOSITIONS"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    project = json.loads(SOURCE.read_text())
    repaired = copy.deepcopy(project)
    repaired["output"]["path"] = str(RENDER_OUTPUT)
    replaced = []
    forbidden_source_shas = set()

    for track in repaired["timeline"]["videoTracks"]:
        for clip in track.get("clips", []):
            metadata = clip.setdefault("metadata", {})
            segment_id = metadata.get("segment_id")
            if segment_id not in REPLACEMENTS:
                continue
            media, cadence, generation = REPLACEMENTS[segment_id]
            if not media.is_file() or not cadence.is_file():
                raise FileNotFoundError(media if not media.is_file() else cadence)
            cadence_data = json.loads(cadence.read_text())
            if cadence_data.get("status") != "PASS":
                raise RuntimeError(f"{segment_id} cadence is not PASS: {cadence}")

            old_source = clip["source"]
            old_source_path = Path(old_source)
            if old_source_path.is_file():
                forbidden_source_shas.add(sha256(old_source_path))
            clip["source"] = str(media)
            metadata.update(
                {
                    "source_sha256": sha256(media),
                    "admission": "PASS_FIXED_COMPOSITION_CAMERA_REPAIR_V18",
                    "camera_policy": "LOCKED_TRIPOD_COMPOSITIONS_HARD_CUTS_NO_PAN_NO_TILT_NO_DOLLY_NO_ORBIT_NO_ROAM",
                    "camera_generation": generation,
                    "cadence_report_path": str(cadence),
                    "cadence_report_sha256": sha256(cadence),
                    "replacement_required": False,
                    "replacement_condition": "SATISFIED_BY_V15_V16_FIXED_COMPOSITION_SHA",
                    "source_reference_mode": "generated_video",
                    "cut_reason": "DIALOGUE_BEAT_FIXED_COMPOSITION_REPAIR",
                    "shot_recipe_superseded": metadata.get("shot_recipe"),
                    "shot_recipe": None,
                    "v18_original_source": old_source,
                }
            )
            replaced.append({
                "clip_id": clip.get("id"), "segment_id": segment_id, "source": str(media),
                "replacement_source_sha256": sha256(media),
            })

    expected = {segment for segment in REPLACEMENTS}
    observed = {item["segment_id"] for item in replaced}
    if observed != expected:
        raise RuntimeError(f"segment coverage mismatch: expected={sorted(expected)} observed={sorted(observed)}")

    repaired.setdefault("metadata", {}).update(
        {
            "version": "V18_FULL_EPISODE_FIXED_CAMERA_LONG_TAKE",
            "parent_project": str(SOURCE),
            "camera_repair_policy": "ZERO_LEGACY_ROAMING_VIDEO_SOURCES_IN_U03_U07",
            "camera_repair_segments": sorted(expected),
            "camera_repair_clip_count": len(replaced),
            "audio_policy": "PRESERVE_EXISTING_NATIVE_DIALOGUE_AUDIO_BGM_AND_MASTERING",
            "release_status": "NOT_FINAL_PENDING_FRESH_RENDER_AND_FULL_EPISODE_QA",
            "replacementBindingPolicy": {
                "enabled": True,
                "expectedTargetCount": len(replaced),
                "targets": [
                    {
                        "clipId": item["clip_id"],
                        "replacementSourceSha256": item["replacement_source_sha256"],
                        "segmentId": item["segment_id"],
                    }
                    for item in replaced
                ],
                "forbiddenSourceSha256": sorted(forbidden_source_shas),
                "forbiddenPathTokens": ["SMOOTH_ROAM", "OVERHEAD_REVEAL", "CONTINUOUS_REFRAME"],
                "failureAction": "BLOCK_COMPILE_RENDER_FINAL_VISUAL_RELEASE_AND_UPLOAD",
            },
        }
    )
    OUTPUT.write_text(json.dumps(repaired, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "output": str(OUTPUT), "replaced_clip_count": len(replaced), "segments": sorted(expected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
