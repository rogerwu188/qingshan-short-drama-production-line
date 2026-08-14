#!/usr/bin/env python3
"""Build a non-release E28 AgentCut rough cut with the failed U09 left as a gap."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E28_13_VIDEO_UNIT_BATCH_V3_SUBMIT_RECEIPT_20260721.json"
PROJECT = ROOT / "configs/e28_agentcut_v1_cl2x517_u09_hold_20260721.json"
OUTPUT = ROOT / "exports/e28/agentcut_v1_cl2x517_u09_hold_20260721/E28_AGENTCUT_V1_CL2X517_U09_HOLD_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V1_CL2X517_U09_HOLD_BUILD_RECEIPT_20260721.json"
CADENCE_DIR = ROOT / "qa/e28_cl2x517_video_units_v3_frame_cadence_20260721"
FAILED_UNIT = "E28-CW-U09"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def light_key(scene_id: str) -> str:
    if "S01" in scene_id:
        return "COLD_DAYLIGHT_TO_DUSK"
    if "S02" in scene_id:
        return "DUSK_TO_EARLY_NIGHT"
    return "MOONLESS_SNOW_NIGHT"


def main() -> int:
    batch = json.loads(RECEIPT.read_text(encoding="utf-8"))
    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    source_manifest: list[dict] = []
    cursor = 0.0
    placeholder: dict | None = None

    for order, task in enumerate(batch["tasks"], 1):
        duration = float(task["duration_seconds"])
        unit_id = task["unit_id"]
        if unit_id == FAILED_UNIT:
            placeholder = {
                "order": order,
                "unit_id": unit_id,
                "start": cursor,
                "duration": duration,
                "end": cursor + duration,
                "render_behavior": "BLACK_BACKGROUND_GAP",
                "reason": "Three generated candidates failed severe identity/story-fact gates; no candidate is admitted.",
                "replacement_required": True,
            }
            cursor += duration
            continue

        if task.get("qa_decision") not in {"PASS_BATCH_QA", "CONDITIONAL_MACHINE_ADMISSION"}:
            raise RuntimeError(f"unit is not admitted: {unit_id} ({task.get('qa_decision')})")
        source = Path(task["output_path"])
        expected_sha = task["output_sha256"]
        if not source.is_file() or sha256(source) != expected_sha:
            raise RuntimeError(f"source SHA mismatch: {source}")
        qa_report = Path(task["qa_report"])
        cadence_report = CADENCE_DIR / f"{unit_id}_FRAME_CADENCE.json"
        if not qa_report.is_file() or not cadence_report.is_file():
            raise RuntimeError(f"missing QA evidence: {unit_id}")

        admission = task["qa_decision"]
        metadata = {
            "episode": "E28",
            "scene_id": task["scene_id"],
            "source_id": unit_id,
            "unit_id": unit_id,
            "source_sha256": expected_sha,
            "source_variant": "CL2X517_ENTITY_REFERENCE_SEQUENCE_V3",
            "source_admission": admission,
            "source_admission_confidence": float(task.get("qa_confidence", 0.85)),
            "cut_reason": "LOCKED_ENTITY_SEQUENCE_UNIT_BOUNDARY",
            "narrative_function": f"Render locked action unit {unit_id} in canonical order.",
            "new_information": f"Canonical E28 CL2X-517 action progression for {unit_id}.",
            "semantic_group": unit_id,
            "fallback_only": False,
            "axis_line": f"{task['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{unit_id}::PRIMARY_ACTION_TARGET",
            "light_key": light_key(task["scene_id"]),
            "action_required": True,
            "action_trajectory": {
                "windup": "The unit begins from its first bound reference state.",
                "contact": "The primary scripted action reaches visible contact.",
                "force": "Force transfers through actors, props, and environment.",
                "result": "The final bound state resolves before the unit boundary.",
            },
            "source_reference_mode": "generated_video",
            "cadence_report_path": str(cadence_report),
            "ocr_report_path": str(qa_report),
        }
        clip_id = f"{unit_id}-VIDEO"
        video_clips.append(
            {
                "id": clip_id,
                "source": str(source),
                "start": cursor,
                "in": 0.0,
                "duration": duration,
                "metadata": metadata,
            }
        )
        audio_clips.append(
            {
                "id": f"{unit_id}-AUDIO",
                "source": str(source),
                "start": cursor,
                "in": 0.0,
                "duration": duration,
                "volume": 0.82,
                "metadata": {
                    "episode": "E28",
                    "unit_id": unit_id,
                    "source_sha256": expected_sha,
                    "cut_reason": "NATIVE_AUDIO_FOLLOWS_ENTITY_REFERENCE_UNIT",
                    "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
                },
            }
        )
        source_manifest.append(
            {
                "order": order,
                "unit_id": unit_id,
                "path": str(source),
                "sha256": expected_sha,
                "start": cursor,
                "duration": duration,
                "admission": admission,
            }
        )
        cursor += duration

    if placeholder is None:
        raise RuntimeError(f"missing expected placeholder unit: {FAILED_UNIT}")

    project = {
        "version": "1.0",
        "background": "black",
        "requireCutReason": True,
        "sourceAdmissionPolicy": {
            "enabled": False,
            "requirePerShotCadence": False,
            "requireActionTrajectory": True,
            "singleStillAction": "block",
            "maxActionNearDuplicateRatio": 0.20,
            "roughAssemblyException": "U09_HOLD_NON_RELEASE_PREVIEW_ONLY",
        },
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
            "loudnessTargetLufs": -16.0,
            "loudnessRangeLu": 11.0,
            "maxClippedSamples": 0,
        },
        "metadata": {
            "episode": "E28",
            "status": "V1_CL2X517_U09_HOLD_NOT_FINAL",
            "runtime_seconds": cursor,
            "contract_runtime_seconds": 172.0,
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "platformUploadAllowed": False,
            "releaseAllowed": False,
            "hold_reason": "E28-CW-U09 has no admitted full-duration candidate.",
            "source_admission_enforced_at_release": True,
        },
        "timeline": {
            "videoTracks": [{"id": "E28_CL2X517_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E28_CL2X517_NATIVE_AUDIO", "clips": audio_clips}],
        },
        "qingshanAudit": {
            "episode": "E28",
            "pipelineStage": "CL2X517_12_UNIT_ROUGH_ASSEMBLY_U09_HOLD",
            "final": False,
            "platformUploadAllowed": False,
            "sourceUnitCount": len(source_manifest),
            "expectedRuntimeSeconds": cursor,
            "contractRuntimeSeconds": 172.0,
            "placeholder": placeholder,
            "releaseBlock": "REPLACE_U09_AND_RERUN_FULL_QA",
            "roughAssemblyException": {
                "sourceAdmissionPolicyEnabled": False,
                "reason": "Three existing periodic-cadence conditional admissions must remain visible in a non-release full-cut review; raw FAIL reports are preserved and linked per source.",
                "affectedConditionalUnits": ["E28-CW-U02", "E28-CW-U03", "E28-CW-U11"],
                "releaseCondition": "Restore strict source admission and pass full-cut cadence before any final or platform action.",
            },
        },
    }

    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BUILD_RECEIPT.write_text(
        json.dumps(
            {
                "schema": "qingshan.agentcut.cl2x517-u09-hold-build.v1",
                "episode": "E28",
                "status": "BUILT_NOT_RENDERED",
                "project": str(PROJECT),
                "output": str(OUTPUT),
                "runtime_seconds": cursor,
                "source_unit_count": len(source_manifest),
                "placeholder": placeholder,
                "sources": source_manifest,
                "credit_spent": 0,
                "platform_upload_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "project": str(PROJECT), "runtime_seconds": cursor, "sources": len(source_manifest), "placeholder": placeholder}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
